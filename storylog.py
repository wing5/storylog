import os
import re
from utils import slugify, cleanup
from config import error, STORY_LENGTH, COL_LENGTH, USER_LENGTH
from random import random
import itertools
import functools

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app, login_required
from google.appengine.ext import db

webapp.template.register_template_library( 'utils.templatefilters')

class NotUniqueError(Exception):
    """Raised by Story.make_unique_slug if slug isn't unique."""

class Human(db.Model):
    """key_name = user_id"""
    nickname = db.StringProperty(required=True, indexed=False)
    collections = db.StringListProperty(indexed=False) #list of slugs

    def belongs_to_current_user(self):
        user = users.get_current_user()
        if user:
            return user.user_id() == self.key().name()

    def url(self):
        return '/Author/%s' % self.key().name()

    def get_collections(self):
        return Collection.get_by_key_name(self.collections, parent=self)

def human_and_collection_from_user(user):
    """
    Returns a user's info and default collection
    Use whenever a new user may need to be created
    """
    user_id = user.user_id()
    human = Human.get_by_key_name(user_id)
    if not human:
        nickname = user.nickname().split('@')[0]
        human = Human(
            key_name = user_id,
            nickname = nickname)
        human.put()
        collection = Collection(
            parent = human.key(),
            key_name = 'main-collection',
            title = 'Main Collection')
        collection.put()
        human.collections.append(collection.key().name())
        human.put()
        return human, collection
    else:
        return human, Collection.get_by_key_name('main-collection', parent = human)

def human_needed(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        user = users.get_current_user()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
            return
        human = Human.get_by_key_name(user.user_id())
        if not human:
            self.error(403)
            return
        return method(self, human, *args, **kwargs)
    return wrapper

class Collection(db.Model):
    """
    key_name = collection_slug
    parent = human
    """
    user = db.UserProperty(auto_current_user_add=True, indexed=False)
    title = db.StringProperty(indexed=False, required=True)
    stories = db.StringListProperty(indexed=False) #list of slugs, should index?
    fav_count = db.IntegerProperty(default=0, indexed=False)

    def profile_stories(self):
        if self.key().name() == 'main-collection':
            return self.stories
        else:
            return self.stories[:5]
    
    def author_url(self):
        return '/Author/%s' % (self.user.user_id())

    def url(self):
        return '/Author/%s/Collection/%s' % (self.user.user_id(), self.key().name().title())

    def belongs_to_current_user(self):
        return users.get_current_user() == self.user

class Story(db.Model):
    """key_name = story_slug""" 
    user = db.UserProperty(auto_current_user_add=True)
    title = db.StringProperty(required=True, indexed=False)
    content = db.TextProperty(required=True)
    rand_id = db.FloatProperty(indexed=True)
    date = db.DateTimeProperty(auto_now_add=True, indexed=False) #not used
    fav_count = db.IntegerProperty(required=True, default=0, indexed=False)
    author_name = db.StringProperty(indexed=False)

    def author_url(self):
        return '/Author/%s' % (self.user.user_id())
    
    def url(self):
        return '/%s' % (self.key().name().title())

    def deleted(self):
        return self.rand_id == None

    def belongs_to_current_user(self):
        return users.get_current_user() == self.user

    def favorited_by_current_user(self):
        return False

    @staticmethod
    def make_unique_slug(title):
        """A Story's title is transformed into a slug. If this slug
        hasn't been taken already, it is returned. Otherwise,
        an error is returned.
        """
        story_slug = slugify(title)
        story = Story.get_by_key_name(story_slug)
        if story_slug and not story:
            return story_slug
        else:
            raise NotUniqueError

class FavoriteIndex(db.Model):
    """
    To get a list of people who favorited an item.

    key_name = item's key name
    parent = story or collection
    """
    favorited_by = db.StringListProperty() #list of uids

class BaseRequestHandler(webapp.RequestHandler):
    def generate(self, template_name, template_values={}):
        if users.get_current_user():
            url = users.create_logout_url("/")
            url_linktext = 'Logout'
        else:
            url = users.create_login_url(self.request.uri)
            url_linktext = 'Login with Google'
            
        values = {
            'user': users.get_current_user(),
            'url': url,
            'url_linktext': url_linktext,
            }
        values.update(template_values)
        path = os.path.join(os.path.dirname(__file__), template_name)
        self.response.out.write(template.render(path, values))
        
    def request_clean(self, input_name, max_length = None):
        if max_length:
            return cleanup(self.request.get(input_name))[:max_length]
        else:
            return cleanup(self.request.get(input_name))

class MainPage(BaseRequestHandler):
    def get(self):
        story = Story.all().order('rand_id').filter('rand_id >', random()).get()
        
        self.generate('main.html', {
            'story': story,})

class StoryPage(BaseRequestHandler):
    def get(self, slug):
        slug = slug.lower() #lowercase incoming 
        story = Story.get_by_key_name(slug)
        errors = []
       
        if not story:
            errors.append(error['story?'])
        if not errors:
            self.generate('story.html', {
                'story': story,
                 })
        else:
            self.generate('story.html', {
                'errors': errors,
                })

class NewStory(BaseRequestHandler):
    @login_required
    def get(self):
        self.generate('edit_story.html')
        
    def post(self):
        errors = []

        title = self.request_clean('title', STORY_LENGTH)
        try:
            slug = Story.make_unique_slug(title)
        except NotUniqueError:
            errors.append(error['unique'])
        if slug in ['you', 'new']:
            errors.append(error['unique'])

        content = self.request_clean('content')
        if not content:
            errors.append(error['content'])

        if not errors:
            user = users.get_current_user()
            human, collection = human_and_collection_from_user(user)

            rand_id = random()
            if not Story.all().get():
                rand_id = 1.0

            story = Story(
                key_name = slug,
                title = title,
                content = db.Text(content),
                rand_id = rand_id,
                author_name = human.nickname)

            collection.stories.append(slug)
            db.put([story, collection])
            self.redirect(story.url())
        else:
            self.generate('edit_story.html', {
                'errors': errors,
                'title': title,
                'content': content,
                })

class EditStory(BaseRequestHandler):
    @login_required
    def get(self, slug):
        errors = []

        story = Story.get_by_key_name(slug.lower()) #lowercase
        if not story:
            errors.append(error['story'])
        elif not story.belongs_to_current_user():
            errors.append(error['story access'])
        if not errors:
            self.generate('edit_story.html', {
                'slug': slug.lower(),
                'title': story.title,
                'content': story.content,
                })
        else:
            self.generate('edit_story.html', {
                'errors': errors,
                })
    def post(self, slug):
        story = Story.get_by_key_name(self.request.get('slug').lower())
        if not story or not story.belongs_to_current_user():
            self.error(403)
            return
        action = self.request.get('action')
        if not action in ['Save Story', 'Delete']:
            self.error(403)
            return
        if action == 'Delete':
            uid = users.get_current_user().user_id()
            human = human.get_by_key_name(uid)
            collections = human.get_collections()
            updated = []
            for col in collections:
                if story.key().name() in col.stories:
                    col.stories.remove(story)
                    updated.append(col)
            db.put(updated)
            story.delete()
            self.redirect('/You')
        else: #Save Story
            errors = []
            content = self.request_clean('content')
            if not content:
                errors.append(error['content'])
            if not errors:
                story.content = db.Text(content)
                story.put()
                self.redirect(story.url())
            else:
                self.generate('edit_story.html', {
                    'errors': errors,
                    'slug': slug,
                    'title': title,
                    'content': content,
                    })
            
class HumanPage(BaseRequestHandler):
    """Handles both:
    * Public-facing profile:  /Author/{{ uid }}
    * Current author's page:  /You
    """
    def get(self, user_id = None):
        if not user_id:
            user = users.get_current_user()
            if not user:
                self.redirect(users.create_login_url(self.request.uri))
                return 
            user_id = user.user_id()
            human = Human.get_by_key_name(user_id)
            if human:
                collections = human.get_collections()
                self.generate('human.html', {
                    'nickname': human.nickname,
                    'human': human,
                    'collections': collections,
                    })
            else:
                self.generate('human.html', {
                    'nickname': user.nickname().split('@')[0], 
                    })
        else:
            human = Human.get_by_key_name(user_id)
            errors = []

            if not human:
                errors.append(error['author?'])
            if not errors:
                collections = human.get_collections()
                self.generate('human.html', {
                    'nickname': human.nickname,
                    'human': human,
                    'collections': collections,
                    })
            else:
                self.generate('human.html', {
                    'errors': errors,
                    'nickname': "No Author",
                    })

class EditName(BaseRequestHandler):
    @login_required
    def get(self):
        user_id = users.get_current_user().user_id()
        human = Human.get_by_key_name(user_id)
        if not human:
            self.error(403)
            return
        self.generate('edit_name.html', {
            'human': human,
            })

    @human_needed
    def post(self, human):
        if not nickname:
            errors.append(error['nickname'])
        if not errors:
            user = users.get_current_user()
            stories = Story.all().filter('user =', user).fetch(1000)
            updated = []
            for story in stories:
                story.author_name = nickname
                updated.append(story)
            human.nickname = nickname
            updated.append(human)
            db.put(updated)
            self.redirect('/You')
        else:
            self.generate('edit_name.html', {
                'human': human,
                'errors': errors,
                })

class Organize(BaseRequestHandler):
    @login_required
    def get(self):
        errors = []
        user_id = users.get_current_user().user_id()
        human = Human.get_by_key_name(user_id)
        if not human:
            errors.append("Cannot organize stories before writing a story.")
        if not errors:
            collections = human.get_collections()
            self.generate('organize.html', {
                'nickname': human.nickname,
                'human': human,
                'collections': collections,
                })
        else:
            self.generate('organize.html', {
                'errors': errors,
                'nickname': user.nickname().split('@')[0], 
                })

    @human_needed
    def post(self, human):
        stories_new_string = cleanup(self.request.get('new'))
        stories_new = stories_new_string.split(',')
        title_new = self.request_clean('new_title', COL_LENGTH)
        slug_new = slugify(title_new)
        if not slug_new:
            title_new = "Collection Title"
            slug_new = "collection-title"

        collections_current = human.get_collections() #Collection instances
        lists_of_stories = (c.stories for c in collections_current)
        all_stories = set(itertools.chain(*lists_of_stories))

        all_stories_new = [] #list of story slugs
        updated_collections = [] #list of Collection instances
        for collection in collections_current:
            stories_string = cleanup(self.request.get(collection.key().name()))
            stories = stories_string.split(',')
            valid_stories = [s for s in stories if s in all_stories]
            collection.stories = valid_stories
            updated_collections.append(collection)
            all_stories_new.extend(valid_stories)

        valid_stories_new = [s for s in stories_new if s in all_stories]
        all_stories_new.extend(valid_stories_new)
        #why check for missing stories? in case something goes wrong!!
        missing_stories = all_stories.difference(all_stories_new)
        #main collection gets missing stories:
        updated_collections[0].stories.extend(missing_stories) 

        if valid_stories_new:
            if slug_new not in human.collections:
                human.collections.append(slug_new)
                collection_new  = Collection(
                    parent = human,
                    key_name = slug_new,
                    title = title_new,
                    stories = valid_stories_new)
                updated_collections.extend([human, collection_new])
                db.put(updated_collections)
            else:
                index = human.collections.index(slug_new)
                updated_collections[index].stories.extend(valid_stories_new)
                db.put(updated_collections)
        else:
            db.put(updated_collections)
    
        self.redirect('/You')

class EditCollection(BaseRequestHandler):
    @login_required
    def get(self, slug):
        errors = []
        human = Human.get_by_key_name(users.get_current_user().user_id())
        if human:
            slug = slug.lower()
            collection = Collection.get_by_key_name(slug, parent=human)
        elif not collection.belongs_to_current_user():
            errors.append(error['collection access'])
        elif collection.key().name() == 'main-collection':
            errors.append(error['main collection'])
        if not errors:
            self.generate('edit_collection.html', {
                'slug': collection.key().name(),
                'title': collection.title,
                })
        else:
            self.generate('edit_collection.html', {
                'errors': errors,
                })
    @human_needed
    def post(self, human, slug):
        errors = []
        slug = self.request.get('slug')
        collection = Collection.get_by_key_name(slug, parent = human)
        title = self.request_clean('title', COL_LENGTH)
        slug = slugify(unicode(title))
        action = self.request.get('action')
        if action not in ['Save Collection Title', 'Delete Collection']:
            self.error(403)
            return
        if not collection or not collection.belongs_to_current_user():
            errors.append(error['collection access'])
        elif collection.key().name() == 'main-collection':
            errors.append(error['main collection'])
        if action == "Save Collection Title":
            if not title:
                errors.append(error['title'])
            elif not slug:
                errors.append(error['slug'])
        if not errors:
            if action == "Delete Collection":
                main= Collection.get_by_key_name('main-collection',parent=human)
                main.stories.extend(collection.stories)
                human.collections.remove(collection.key().name())
                db.put([main, human])
                collection.delete()
                self.redirect('/You')
                return
            else:
                if slug == collection.key().name():
                    self.redirect('/You')
                existing_col = Collection.get_by_key_name(slug, parent=human)
                if not existing_col:
                    new_col = Collection(
                        parent = human,
                        key_name = slug,
                        title = title,
                        stories = collection.stories)
                    human.collections.append(slug)
                    human.collections.remove(collection.key().name())
                    db.put([new_col, human])
                    collection.delete()
                    self.redirect('/You')
                else:
                    existing_col.stories.extend(collection.stories)
                    human.collections.remove(collection.key().name())
                    db.put([existing_col, human])
                    collection.delete()
                    self.redirect('/You')
        else: #errors
            self.generate('edit_collection.html', {
                'errors': errors,
                'slug': slug,
                'title': title,
                })
                
class CollectionPage(BaseRequestHandler):
    def get(self, user_id, slug):
        human = Human.get_by_key_name(user_id)
        collection = Collection.get_by_key_name(slug.lower(), parent=human)
        errors = []

        if not human:
            errors.append(error['author'])
        if not collection:
            errors.append(error['collection'])
        if not errors:
            if collection.key().name() == 'main-collection':
                self.redirect(human.url())
                return
            collections = [collection,]
            self.generate('collection.html', {
                'nickname': human.nickname,
                'human': human,
                'collections': collections,
                })
        else:
            self.generate('collection.html', {
                'errors': errors,
                })
###
class Favorites(BaseRequestHandler):
    def get(self, user_id):
        author = Author.get_by_key_name(user_id)
        errors = []

        if not author:
            errors.append("This is not a valid Author page. Sorry.")
        if not errors:
            self.generate('favorites_page.html', {
                'author': author,
                })
        else:
            self.generate('favorites_page.html', {
                'errors': errors,
                })



# be careful if you want to rearrange these pages: make sure the urls
# with the broader matches go toward the bottom
application = webapp.WSGIApplication(
    [('/', MainPage),
     ('(?i)/New', NewStory),
     ('(?i)/Edit/([^/]+)', EditStory),     
     ('(?i)/You', HumanPage),
     ('(?i)/You/Organize', Organize),
     ('(?i)/You/EditName', EditName),
     ('(?i)/Author/([^/]+)', HumanPage),
     ('(?i)/Author/([^/]+)/Favorites', Favorites),
     ('(?i)/Author/([^/]+)/Collection/([^/]+)', CollectionPage),     
     ('(?i)/EditCollection/([^/]+)', EditCollection),
     ('/([^/]+)', StoryPage)],
    debug=True)

def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()

