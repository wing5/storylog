import os
import re
from utils import slugify, cleanup
from random import random
import itertools
import functools

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app, login_required
from google.appengine.ext import db

webapp.template.register_template_library( 'utils.templatefilters')

TITLE_LENGTH = 35

class NotUniqueError(Exception):
    """Raised by Story.make_unique_slug if slug isn't unique."""

class Human(db.Model):
    """key_name = user_id"""
    nickname = db.StringProperty(required=True, indexed=False)
    favorite_stories = db.StringListProperty(indexed=False) #list of slugs
    favorite_collections = db.StringListProperty(indexed=False) #list of slugs
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

class Collection(db.Model):
    """
    key_name = collection_slug
    parent = human
    """
    user = db.UserProperty(auto_current_user_add=True, indexed=False)
    title = db.StringProperty(indexed=False, required=True)
    stories = db.StringListProperty(indexed=False) #list of slugs, should index?
    favorite_count = db.IntegerProperty(default=0, indexed=False)



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

    def favorited_by_current_user(self):
        user = users.get_current_user()
        if user:
            return UserFavorite.get_by_key_name(user.user_id(), parent=self)

class Story(db.Model):
    """key_name = story_slug""" 
    user = db.UserProperty(auto_current_user_add=True, indexed=False)
    title = db.StringProperty(required=True, indexed=False)
    content = db.TextProperty(required=True)
    rand_id = db.FloatProperty(indexed=True)
    date = db.DateTimeProperty(auto_now_add=True, indexed=False) #not used
    favorite_count = db.IntegerProperty(default=0, indexed=False)
    author_name = db.StringProperty(required=True, indexed=False)
    #following used when editing nickname
    human = db.ReferenceProperty(Human, required=True,
                                 collection_name='stories')

    def author_url(self):
        return '/Author/%s' % (self.user.user_id())
    
    def url(self):
        return '/%s' % (self.key().name().title())

    def deleted(self):
        return self.rand_id == None

    def belongs_to_current_user(self):
        return users.get_current_user() == self.user

    def favorited_by_current_user(self):
        user = users.get_current_user()
        if user:
            return UserFavorite.get_by_key_name(user.user_id(), parent=self)

    @staticmethod
    def make_unique_slug(title):
        """A Story's title is transformed into a slug. If this slug
        hasn't been taken already, it is returned. Otherwise,
        an error is returned.
        """
        story_slug = slugify(title)
        story = Story.get_by_key_name(story_slug)
        if not story:
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

class UserFavorite(db.Model):
    """
    To see if an item has been favorited.

    key_name = user_id
    parent = story or collection
    """
    pass


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

class MainPage(BaseRequestHandler):
    def get(self):
        story = Story.all().order('rand_id').filter('rand_id >', random()).get()
        
        self.generate('main.html', {
            'story': story,})

class StoryPage(BaseRequestHandler):
    def get(self, slug):
        # all incoming urls should be made lowercase
        story = Story.get_by_key_name(slug.lower())
        errors = []
       
        if not story:
            errors.append("Couldn't find this story. Sorry.")
        if not errors:
            self.generate('story.html', {
                'story': story,
                 })
        else:
            self.generate('story.html', {
                'errors': errors,
                })

class Write(BaseRequestHandler):
    #Author created here or w/ EditAuthorAction or w/ FavoriteStoryAction
    @login_required
    def get(self):
        errors = []

        story_slug = self.request.get('story')

        if not story_slug:
            self.generate('write.html')
            return
        else:
            #all incoming urls should be made lowercase
            story = Story.get_by_key_name(story_slug.lower())

            if not story:
                errors.append("Couldn't find this story. Sorry.")
            else:
                if not story.belongs_to_current_user():
                    errors.append("You cannot edit this story.")
            if not errors:
                story_key = story.key()
                title = story.title
                content = story.content
            
                self.generate('write.html', {
                    'story_key': story_key,
                    'title': title,
                    'content': content,
                    })
            else:
                self.generate('write.html', {
                    'errors': errors,
                    })
            
    def post(self):
        errors = []
        
        user = users.get_current_user()
        story_key = self.request.get('story_key')

        if not story_key:
            title = cleanup(self.request.get('title'))
            if title:
                if len(title) > 35:
                    errors.append("Please enter a title with 35 letters or less.")
                try:
                    slug = Story.make_unique_slug(title)
                except NotUniqueError:
                    errors.append("Please change your story's title. Someone else has already chosen a very similar title.")
            else:
                errors.append('Please enter a title.')
        else:
            existing_story = Story.get(story_key)
            if not existing_story or not existing_story.belongs_to_current_user():
                errors.append("You cannot edit this story.")
            else:
                action = self.request.get('action')
                if action in ['Save Story', 'Delete']:
                    if action == 'Delete':
                        human = Human.get_by_key_name(user.user_id())
                        collections = human.get_collections()
                        updated = []
                        for collection in collections:
                            if existing_story.key().name() in collection.stories:
                                collection.stories.remove(existing_story.key().name())
                                updated.append(collection)
                        db.put(updated)
                        existing_story.delete()
                        self.redirect('/You')
                        return                        
                else:
                    errors.append("Story action could not be determined, sorry. Please report this problem to the website owner.")
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if not errors:
            content = db.Text(cleanup(self.request.get('content')))
            if not story_key:
                human, collection = human_and_collection_from_user(user)
                
                #change this rand_id handling before launch
                rand_id = random()
                if not Story.all(keys_only=True).get():
                    rand_id = 1.0
                    
                story = Story(
                    key_name = slug,
                    title = title,
                    content = content,
                    rand_id = rand_id,
                    author_name = human.nickname,
                    human = human)

                collection.stories.append(slug)

                db.put([story, collection])

                self.redirect(story.url())
                return
            else:
                if action == "Save Story":
                    existing_story.content = content
                    existing_story.put()

                    self.redirect(existing_story.url())
                    return
        else:
            self.generate('write.html', {
                'errors': errors,
                'story_key': story_key,
                'title': self.request.get('title'),
                'content': self.request.get('content'),
                })

class HumanPage(BaseRequestHandler):
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
                errors.append("This is not a valid author page. Sorry.")
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
        errors = []
        user_id = users.get_current_user().user_id()
        human = Human.get_by_key_name(user_id)
        if not human:
            errors.append("You can't change your name before writing a story.")
        if not errors:
            self.generate('edit_name.html', {
                'human': human,
                })
            return
        else:
            self.generate('edit_name.html', {
                'errors': errors,
                })
        
    def post(self):
        human = Human.get(self.request.get('human_key'))
        nickname = cleanup(self.request.get('nickname'))
        errors = []

        if not nickname:
            errors.append('Please enter a name.')
        if not len(nickname) < 24:
            errors.append('Please enter a name with 23 letters or less.')
        if not human or not  human.belongs_to_current_user():
            errors.append("You cannot edit this user. Sorry.")
        if not errors:
            stories = human.stories.fetch(1000)
            updated = []
            for story in stories:
                story.author_name = nickname
                updated.append(story)
            human.nickname = nickname
            updated.append(human)
            db.put(updated)
            self.redirect('/You')
            return
        else:
            self.generate('edit_name.html', {
                'human': human,
                'errors': errors,
                })

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
        stories_new_string = cleanup(self.request.get('new_collection_input'))
        stories_new = stories_new_string.split(',')
        title_new_long = cleanup(self.request.get('new_title_input'))
        title_new = title_new_long[:TITLE_LENGTH]
        slug_new = slugify(title_new)
        if not title_new or not slug_new:
            title_new = "Collection Title"
            slug_new = "collection-title"

        collections_current = human.get_collections() #Collection instances
        lists_of_stories = (c.stories for c in collections_current)
        all_stories = set(itertools.chain(*lists_of_stories))

        all_stories_new = [] #list of story slugs
        updated_collections = [] #list of Collection instances
        for collection in collections_current:
            arg = collection.key().name() + '_input'
            stories_string = cleanup(self.request.get(arg))
            stories = stories_string.split(',')
            valid_stories = [s for s in stories if s in all_stories]
            collection.stories = valid_stories
            updated_collections.append(collection)
            all_stories_new.extend(valid_stories)

        #why check for missing stories? just in case something goes wrong
        valid_stories_new = [s for s in stories_new if s in all_stories]
        all_stories_new.extend(valid_stories_new)
        missing_stories = all_stories.difference(all_stories_new)
        updated_collections[0].stories.extend(missing_stories) #main collection
        
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
    
        self.redirect('/You')

class EditCollection(BaseRequestHandler):
    @login_required
    def get(self):
        errors = []
        human = Human.get_by_key_name(users.get_current_user().user_id())
        if human:
            name = self.request.get('collection')
            collection = Collection.get_by_key_name(name, parent=human)
        if not human or not collection or not collection.belongs_to_current_user():
            errors.append("You cannot edit this collection. Sorry.")
        else:
            if collection.key().name() == 'main-collection':
                errors.append("This is your main collection. It cannot be deleted")
        if not errors:
            self.generate('edit_collection.html', {
                'collection_key': collection.key(),
                'collection_title': collection.title,
                })
        else:
            self.generate('edit_collection.html', {
                'errors': errors,
                })
    @human_needed
    def post(self, human):
        errors = []
        collection = Collection.get(self.request.get('collection_key'))
        action = self.request.get('action')
        title = cleanup(self.request.get('collection_title'))
        slug = slugify(title)

        if not collection or not collection.belongs_to_current_user():
            errors.append("You cannot edit this collection. Sorry.")
        else:
            if collection.key().name() == 'main-collection':
                errors.append("This is your main collection. It cannot be edited.")
            else:
                if action not in ['Save Collection Title', 'Delete Collection']:
                    errors.append("Couldn't determine collection action. Please contact website owner.")
                else:
                    if action == "Delete Collection":
                        stories = collection.stories
                        main_col = Collection.get_by_key_name('main-collection', parent=human)
                        main_col.stories.extend(stories)
                        human.collections.remove(collection.key().name())
                        db.put([main_col, human])
                        collection.delete()
                        self.redirect('/You')
                        return
        if not title:
            errors.append("Please enter a title.")
        if len(title) > 33:
            errors.append("Please enter a title with 33 letters or less.")
        if not slug:
            errors.append("Please enter a title with at least one letter or number in it.")
        if not errors:
            stories = collection.stories
            if slug == collection.key().name():
                self.redirect('/You')
                return
            existing_col = Collection.get_by_key_name(slug, parent=human)
            if not existing_col:
                new_col = Collection(
                    parent = human,
                    key_name = slug,
                    title = title,
                    stories = stories)
                human.collections.append(slug)
                human.collections.remove(collection.key().name())
                db.put([new_col, human])
                collection.delete()
                self.redirect('/You')
            else:
                existing_col.stories.extend(stories)
                human.collections.remove(collection.key().name())
                db.put([existing_col, human])
                collection.delete()
                self.redirect('/You')
        else:
            col_key = collection.key()
            self.generate('edit_collection.html', {
                'errors': errors,
                'collection_key': collection.key(),
                'collection_title': collection.title,
                })
                
#####                
class CollectionPage(BaseRequestHandler):
    def get(self, user_id, slug):
        human = Human.get_by_key_name(user_id)
        collection = Collection.get_by_key_name(slug.lower(), parent=human)
        errors = []

        if not human:
            errors.append("This is not a valid Author page. Sorry.")
        if not collection:
            errors.append("This is not a valid Collection page. Sorry.")
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



# be careful if you want to rearrange the pages: make sure the urls
# with the broader matches go toward the bottom
application = webapp.WSGIApplication(
    [('/', MainPage),
     ('(?i)/You', HumanPage),
     ('(?i)/Author/([^/]+)', HumanPage),
     ('(?i)/Author/([^/]+)/Collection/([^/]+)', CollectionPage),
     ('(?i)/You/Organize', Organize),
     ('(?i)/Author/([^/]+)/Favorites', Favorites),
     ('(?i)/Write', Write),
     ('(?i)/Edit', EditCollection),
     ('(?i)/You/EditName', EditName),
     ('/([^/]+)', StoryPage)],
    debug=True)

def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()

