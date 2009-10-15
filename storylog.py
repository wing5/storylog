import os
import re
from utils import slugify, cleanup
from random import random

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app, login_required
from google.appengine.ext import db

#register with webapp template filters
def slug_to_title(value):
    return value.replace('-',' ').title()

def get_human_and_collection(user):
    """
    Returns a user's info and default collection
    Use whenever a new user may need to be created
    """
    if isinstance(user, users.User):
        user_id = user.user_id()
        human = Human.get_by_key_name(user_id)
        if not human:
            nickname = user.nickname().split('@')[0]
            collection = Collection(
                key_name = user_id)
            collection.put()
            human = Human(
                key_name = user_id,
                nickname = nickname,
                collections = [collection.key()])
            human.put()
            return human, collection
        else:
            return human, Collection.get_by_key_name(user_id)
    else:
        return None, None

class Human(db.Model):
    """key_name = user_id"""
    nickname = db.StringProperty(required=True, indexed=False)
    favorite_stories = db.StringListProperty(indexed=False) #list of slugs
    favorite_collections = db.StringListProperty(indexed=False)
    collections = db.ListProperty(db.Key, indexed=False)

    def belongs_to_current_user(self):
        return users.get_current_user().user_id() == self.key().name()

    def url(self):
        return '/Author/%s' % self.key().name()

class FavoriteIndex(db.Model):
    """
    To get a list of people who favorited an item.

    key_name = item's key name
    parent = story or collection
    """
    favorited_by = db.StringListProperty(db.Key) #list of uids

class UserFavorite(db.Model):
    """
    To see if an item has been favorited.

    key_name = user_id
    parent = story or collection
    """
    pass

class Collection(db.Model):
    """key_name = user_id + ' ' + col_slug"""
    title = db.StringProperty(default='', indexed=False)
    stories = db.StringListProperty(required=True, indexed=False)
    favorite_count = db.IntegerProperty(default=0, indexed=False)

    def get_stories(self, num=None):
        return Story.get(self.stories[:num])

    def get_some_stories(self):
        return Story.get(self.stories[:5])

    def author_url(self):
        return '/Author/%s' % (self.key().name().split(' ')[0])

    def url(self):
        return '/Author/%s/Collection/%s' % tuple(self.key().name().split(' '))

    def belongs_to_current_user(self):
        user = users.get_current_user()
        if user:
            return user.user_id() == self.key().name().split(' ')[0]

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
        find_unique_slug is called.
        """
        story_slug = slugify(title)
        story = Story.get_by_key_name(story_slug)
        if not story:
            return story_slug
        else:
            return Story.find_unique_slug(story_slug, attempt=1)

    @staticmethod
    def find_unique_slug(slug, attempt=1):
        """Returns 'slug-' + '[1-5]' or an error if all of those slugs
        have been taken already.
        """
        new_slug = slug + '-%d' % attempt
        story = Story.get_by_key_name(new_slug)
        if not story:
            return new_slug
        elif attempt < 5:
            attempt += 1
            return Story.find_unique_slug(slug, attempt)
        else:
            return ' error '

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
        
        self.generate('base_story_page.html', {
            'story': story,})

class Write(BaseRequestHandler):
    #Author created here or w/ EditAuthorAction or w/ FavoriteStoryAction
    @login_required
    def get(self):
        errors = []

        story_slug = self.request.get('story')

        if not story_slug:
            self.generate('base_submit_page.html')
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
            
                self.generate('base_submit_page.html', {
                    'story_key': story_key,
                    'title': title,
                    'content': content,
                    })
            else:
                self.generate('base_submit_page.html', {
                    'errors': errors,
                    })
            
    def post(self):
        errors = []
        
        user = users.get_current_user()
        human, collection = get_human_and_collection(user)

        story_key = self.request.get('story_key')

        if not story_key:
            title = cleanup(self.request.get('title'))
            if title:
                if len(title) > 35:
                    errors.append("Please enter a title with 35 letters or less.")
                slug = Story.make_unique_slug(title)
                if slug == ' error ':
                    errors.append("Please change your story's title. Exactly six other people have already chosen a very similar title.")
            else:
                errors.append('Please enter a title.')
        else:
            existing_story = Story.get(story_key)
            if not existing_story.belongs_to_current_user():
                errors.append("You cannot edit this story.")
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if not errors:
            content = db.Text(cleanup(self.request.get('content')))
            if not story_key:
                #change this rand_id handling before launch
                rand_id = random()
                if not Story.all(keys_only=True).get():
                    rand_id = 1.0
                    
                story = Story(
                    key_name = slug,
                    user = user,
                    title = title,
                    content = content,
                    rand_id = rand_id,
                    author_name = human.nickname,
                    human = human)
                story.put()

                collection.stories.append(slug)
                collection.put()
            else:
                existing_story.content = content
                existing_story.put()

            self.redirect(story.url())
            return
        else:
            self.generate('base_submit_page.html', {
                'errors': errors,
                'story_key': story_key,
                'title': self.request.get('title'),
                'content': self.request.get('content'),
                })

#########################################
class DeleteStoryPage(BaseRequestHandler):
    @login_required
    def get(self, slug):
        user = users.get_current_user()
        user_id = user.user_id()
        story = Story.get_by_key_name(slug.lower())
        errors = []

        if not story:
            errors.append("Couldn't find this story. Sorry.")
        else:
            if not story.belongs_to_current_user():
                errors.append("You cannot delete this story.")
        if not errors:
            self.generate('delete_page.html', {
                'story': story,
                })
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                })

class DeleteStoryAction(BaseRequestHandler):
    def post(self):
        story = Story.get(self.request.get('story_key'))
        user = users.get_current_user()
        user_data = get_or_create_data_from_user(user)
        errors = []

        if not story:
            errors.append("Couldn't find this story. Sorry.")
        else:
            if not story.belongs_to_current_user():
                errors.append("You cannot delete this story.")
        if not errors:
            #remove story from all of its collections
            collections = Collection.all().ancestor(user_data).filter('stories =', story.key())
            
            updated = []
            for collection in collections:
                collection.stories.remove(story.key())
                updated.append(collection)
            db.put(updated)

            favorited = UserData.all(keys_only=True).filter('favorite_stories =', story.key()).get()
            
            if favorited:
                story.rand_id = None
                story.put()
            else:
                story.delete()
                
            self.redirect('/You')
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                'story': story,
                })

class DeleteCollectionPage(BaseRequestHandler):
    @login_required
    def get(self, user_id, cat_slug):
        user = users.get_current_user()
        user_data = UserData.get_by_key_name(user_id)
        collection = Collection.all().ancestor(user_data).filter('slug =', cat_slug).get()
        errors = []

        if not collection or not collection.belongs_to_current_user():
            errors.append("You cannot delete this category.")
        if not errors:
            self.generate('delete_page.html', {
                'category': category,
                })
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                })

class DeleteCollectionAction(BaseRequestHandler):
    def post(self):
        user = users.get_current_user()
        user_id = user.user_id()
        category = Category.get(self.request.get('category_key'))
        author = Author.get_by_key_name(user_id)
        errors = []

        if not author or not category or not category.user_has_access(user):
            errors.append("You cannot delete this category.")
        if not errors:
            empty_cat = Category.get_by_key_name(user_id)
            if not empty_cat:
                empty_cat = Category(
                    key_name = user_id,
                    author = author,
                    )
                empty_cat.put()
            stories = author.stories.filter('category =', category.key())
            updated_stories = []
            for story in stories:
                story.category = empty_cat
                updated_stories.append(story)
            db.put(updated_stories)
            category.delete()
            self.redirect('/You')
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                })

class CollectionPage(BaseRequestHandler):
    def get(self, user_id, cat_slug):
        author = Author.get_by_key_name(user_id)
        category = Category.get_by_key_name(user_id + cat_slug.lower())
        errors = []

        if not author:
            errors.append("This is not a valid Author page. Sorry.")
        if not category:
            errors.append("This is not a valid Category page. Sorry.")
        if not errors:
            categories = [category,]
            self.generate('category_page.html', {
                'author': author,
                'categories': categories,
                })
        else:
            self.generate('category_page.html', {
                'errors': errors,
                })

class FavoriteStoriesPage(BaseRequestHandler):
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

#combine with author page
class UserProfilePage(BaseRequestHandler):
    def get(self, user_id = None):
        if not user_id:
            user = users.get_current_user()
            if not user:
                self.redirect(users.create_login_url(self.request.uri))
                return 
            user_id = user.user_id()
            author = Author.get_by_key_name(user_id)
            if author:
                categories = author.categories.fetch(100)
                self.generate('author_page.html', {
                    'author': author,
                    'categories': categories,
                    })
            else:
                self.generate('author_page.html', {
                    'nickname': user.nickname(), #put into template
                    })
        else:
            author = Author.get_by_key_name(user_id)
            errors = []

            if not author:
                errors.append("This is not a valid author page. Sorry.")
            if not errors:
                categories = author.categories.fetch(100)
                self.generate('author_page.html', {
                    'author': author,
                    'categories': categories,
                    })
            else:
                self.generate('author_page.html', {
                    'errors': errors,
                    })
                
class AuthorPage(BaseRequestHandler):
    def get(self, user_id):
        author = Author.get_by_key_name(user_id)
        errors = []
        
        if not author:
            errors.append("This is not a valid author page. Sorry.")
        if not errors:
            categories = author.categories.fetch(100)
            self.generate('author_page.html', {
                'author': author,
                'categories': categories,
                })
        else:
            self.generate('author_page.html', {
                'errors': errors,
                })
            
class EditAuthorPage(BaseRequestHandler):
    @login_required
    def get(self):
        user = users.get_current_user()
        user_id = user.user_id()
        author = Author.get_by_key_name(user_id)
        if not author:
            nickname = user.nickname().split('@')[0]
            author = Author(
                Key_name = user_id,
                user = user,
                name = nickname)
            author.put()
        self.generate('edit_author.html', {
            'author': author,
            })

class EditAuthorAction(BaseRequestHandler):
    def post(self):
        user = users.get_current_user()
        author = Author.get(self.request.get('author_key'))
        new_name = cleanup(self.request.get('author_name'))
        errors = []

        if not new_name:
            errors.append('Please enter a name.')
        if not len(new_name) < 24:
            errors.append('Please enter a name with 23 letters or less.')
        if not author or not  author.user_has_access(user):
            errors.append("You cannot edit this author's name. Sorry.")
        if not errors:
            author.name = new_name
            author.put()
            self.redirect('/You')
        else:
            self.generate('edit_author.html', {
                'author': author,
                'errors': errors,
                })

class SingleStoryPage(BaseRequestHandler):
    def get(self, slug):
        # all incoming urls should be made lowercase
        story = Story.get_by_key_name(slug.lower())
        errors = []
       
        if not story:
            errors.append("This story does not exist.")
        if not errors:
            self.generate('single_story.html', {
                'story': story,
                 })
        else:
            self.generate('single_story.html', {
                'errors': errors,
                })

# be careful if you want to rearrange the pages: make sure the urls
# with the broader matches go toward the bottom
application = webapp.WSGIApplication(
    [('/', MainPage),
     ('(?i)/You', UserProfilePage),
     ('(?i)/Write', Write),
     ('(?i)/Delete/([^/]+)', DeleteStoryPage),
     ('/deletestory.do', DeleteStoryAction),
     ('(?i)/DeleteCategory/([^/]+)/([^/]+)', DeleteCollectionPage),
     ('/deletecategory.do', DeleteCollectionAction),
     ('(?i)/Author/([^/]+)/Favorites', FavoriteStoriesPage),
     ('(?i)/Author/([^/]+)/Category/([^/]+)', CollectionPage),
     ('(?i)/Author/([^/]+)', AuthorPage),
     ('(?i)/EditAuthor', EditAuthorPage),
     ('/editauthor.do', EditAuthorAction),
     ('/([^/]+)', SingleStoryPage)],
    debug=True)

def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()

