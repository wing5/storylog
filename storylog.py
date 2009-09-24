import os
import re
from utils import slugify, cleanup
from random import random

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app, login_required
from google.appengine.ext import db

class Author(db.Model):
    name = db.StringProperty(required=True,indexed=False)
    user = db.UserProperty(required=True,auto_current_user_add=True)

    def __init__(self, *args, **kwds):
        """Assigns a given user's id as the author's key name.
        Assigns a given user's nickname as the author's name.
        """
        kwds['key_name'] = kwds['user'].user_id()
        kwds['name'] = kwds['user'].nickname().split('@')[0]
        db.Model.__init__(self, *args, **kwds)

class Category(db.Model): 
    author = db.ReferenceProperty(Author,
                                  collection_name='categories')
    name = db.StringProperty(default='')
    slug = db.StringProperty(default='')    

    @staticmethod
    def remove_if_empty(author, category):
        if not category.stories.filter('author =', author).get():
            category.delete()


class Story(db.Model):
    author        = db.ReferenceProperty(Author,
                                         collection_name='stories')
    title         = db.StringProperty(required=True, indexed=False)
    content       = db.TextProperty(required=True) 
    category      = db.ReferenceProperty(Category,
                                         collection_name='stories')
    rand_id       = db.FloatProperty(required=True)
    date          = db.DateTimeProperty(auto_now_add=True)
    #rating_mean  = db.RatingProperty() # only 0-100
    #rating_count = db.RatingProperty(indexed=False) # only 0-100



    def __init__(self, *args, **kwds):
        """Assigns the story's slug as the story's key name. Assigns
        a random float to the story's random id.
        """
        db.Model.__init__(self, *args, **kwds)
        
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
            return Story.find_unique_slug(new_slug, attempt)
        else:
            return ' error '

    def user_has_access(self, user):
        #get_value_for_datastore returns the author's key without a db lookup
        #alternate: ...== story.author.key().name()
        return user.user_id() == Story.author.get_value_for_datastore(self).name()
    
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
        story = Story.all().filter('rand_id >', random()).get()
    
        self.generate('base.html', {
            'story': story,})

class CreateStoryPage(BaseRequestHandler):
    @login_required
    def get(self):
        self.generate('create_story.html')

class CreateStoryAction(BaseRequestHandler):
    #Author created here or w/ EditNicknameAction or w/ FavoriteStoryAction
    def post(self):
        user = users.get_current_user()
        user_id = user.user_id()
        title = cleanup(self.request.get('title'))
        slug = Story.make_unique_slug(title)
        
        errors = []

        if not title:
            errors.append('Please enter a title.')
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if slug == ' error ':
            errors.append("Please change your story's title. Six other people have chosen a very similar title.")
        if not errors:
            author = Author.get_by_key_name(user_id)
            if not author:
                author = Author(user=user)
                author.put()

            category_name = cleanup(self.request.get('category_name'))
            category_slug = slugify(category_name)
            category = Category.get_by_key_name(user_id + category_slug)
            if not category:
                category = Category(
                    key_name = user_id + category_slug,
                    author = author,
                    name = category_name,
                    slug = category_slug)
                category.put()

            content = db.Text(cleanup(self.request.get('content')))
            #change the following rand_id handling before launch
            rand_id = random()
            if not Story.all().get():
                rand_id = 1.0

            story = Story(
                key_name = slug,
                author = author,
                title = title,
                content = content,
                category = category,
                rand_id = rand_id)
            story.put()

            #all outgoing urls should be in title format
            self.redirect('/%s' % (story.key().name().title())) 

        self.generate('create_story.html', {
            'errors': errors,
            'title': self.request.get('title'),
            'content': self.request.get('content'),
            'category_name': self.request.get('category_name'),
            })

class EditStoryPage(BaseRequestHandler):
    @login_required
    def get(self, slug):
        user = users.get_current_user()
        user_id = user.user_id()   
        errors = []

        #all incoming urls should be made lowercase
        story = Story.get_by_key_name(slug.lower())

        if not user or not story or not story.user_has_access(user):
            errors.append("You cannot edit this story.")
        if not errors:
            story_key = story.key()
            title = story.title
            content = story.content
            category_name = story.category.name
            
            self.generate('edit_story.html', {
                'story_key': story_key,
                'title': title,
                'content': content,
                'category_name': category_name,
                })

        self.generate('edit_story.html', {
            'errors': errors,
            })

        

class EditStoryAction(BaseRequestHandler):
    def post(self):
        user = users.get_current_user()
        user_id = user.user_id()
        story_key = self.request.get('story')
        story = Story.get(story_key)
        title = cleanup(self.request.get('title'))
        slug = Story.make_unique_slug(title) # is this db call necessary before error display?
        
        errors = []

        if not user or not story or not story.user_has_access(user):
            errors.append("You cannot edit this story.")
        if not self.request.get('title'):
            errors.append('Please enter a title.')
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if slug == ' error ':
            errors.append("Please change your story's title. Six other people have already chosen a very similar title.")
        if not errors:
            content = db.Text(cleanup(self.request.get('content')))
            author = Author.get_by_key_name(user_id)
            if not author:
                self.error(403)
                return

            category_name = cleanup(self.request.get('category_name'))
            category_slug = slugify(category_name)            
            category = Category.get_by_key_name(user_id + category_slug)
            old_category = story.category
            if not category:
                category = Category(
                    key_name = user_id + category_slug,
                    author = author,
                    name = category_name,
                    slug = category_slug)
                category.put()

            if story.title != title:
                story.delete()
                #change the following rand_id handling before launch
                rand_id = random()
                if not Story.all().get():
                    rand_id = 1.0
                story = Story(
                    key_name = slug,
                    author = author,
                    title = title,
                    content = content,
                    category = category,
                    rand_id = rand_id)
                story.put()
            else:
                story.title = title
                story.content = content
                story.category = category
                story.put()

            #cleanup time
            Category.remove_if_empty(author, old_category)
            #all outgoing urls should be in title format
            self.redirect('/%s' % (story.key().name().title())) 

        self.generate('edit_story.html', {
            'errors': errors,
            'title': self.request.get('title'),
            'content': self.request.get('content'),
            'category_name': self.request.get('category_name'),
            })

#todo:
class CategoryPage(BaseRequestHandler):
    def get(self, author, cat_name):
        if user_id and cat_slug:
            author = Author.get_by_key_name(user_id)
            category = author.categories.filter('slug =', cat_slug).get()
        else:
            self.error(404)
            return

        self.generate('category_page.html', {
            'category': category,
            })

#todo: (finish userprofilepage first, use it as an example) 
class AuthorPage(BaseRequestHandler):
    def get(self, user_id):
        # dont display edit link on author pages
        if user_id:
            author = Author.get_by_key_name(user_id)
            categories = author.categories.fetch(100)
        else:
            self.error(404)
            return

        self.generate('author_page.html', {
            'author': author,
            'categories': categories,
            })

class UserProfilePage(BaseRequestHandler):
    @login_required
    def get(self):
        user = users.get_current_user()
        user_id = user.user_id()
        errors = []

        if not user:
            errors.append('Please login.')
        if not errors:
            author = Author.get_by_key_name(user_id)
            if author:
                categories = author.categories #set max categories/stories?
                self.generate('author_page.html', {
                    'author' : author,
                    'categories': categories,
                    })
            else:
                self.generate('author_page.html')
        else:
            self.generate('author_page.html', {
                'errors' : errors,
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

  
application = webapp.WSGIApplication(
    [('/', MainPage),
     ('/You', UserProfilePage),
     ('/Share', CreateStoryPage),
     ('/createstory.do', CreateStoryAction),
     ('/editstory.do', EditStoryAction),
     (r'/Edit/([^/]+)', EditStoryPage),
     (r'/Author/([^/]+)/Category/([^/]+)', CategoryPage),
     (r'/Author/([^/]+)', AuthorPage),
     (r'/([^/]+)', SingleStoryPage)],
    debug=True)

def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()

