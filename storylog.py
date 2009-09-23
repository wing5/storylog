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
    slug = db.StringProperty(required=True)    

    def __init__(self, *args, **kwds):
        """Assigns the category's slug + the given author's key name
        as the category's key name.
        """
        kwds['key_name'] = kwds['author'].name() + kwds['slug']
        db.Model.__init__(self, *args, **kwds)

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
            return naming_error("Please change your story's title. Six other people already chose a very similar title.") # make this function!

    @staticmethod
    def user_has_access(user, story):
        return user.user_id() == story.author.key().name()
    
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
    def post(self):
        user = users.get_current_user()
        user_id = user.user_id()
        
        errors = []

        if not self.request.get('title'):
            errors.append('Please enter a title.')
        if not self.request.get('content'):
            errors.append('Please enter a story.')
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
                    author=author,
                    category_name=category_name,
                    slug=category_slug)
                category.put()

            title = cleanup(self.request.get('title'))
            slug = Story.make_unique_slug(title)
            content = db.Text(cleanup(self.request.get('content')))
            #change rand_id handling before launch
            rand_id = random()
            if not Story.all().get():
                rand_id = 1.0

            story = Story(
                key_name = slug,
                author=author,
                title=title,
                content=content,
                category=category,
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

        if not user or not story or not story.user_has_access(user, story):
            errors.append("You don't have access to edit this story")
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
        
        #if not story or story.user_has_access(user, story):

        author = Author.get_by_key_name(user_id)
        if not author:
            author_error("You haven't created any stories yet.") # create this function!
            

        new_category_name = cleanup(self.request.get('category_name'))
        category = Category.load(author, new_category_name)
        Category.remove_if_empty(author, story.category)
        
        content = db.Text(cleanup(self.request.get('content')))

        title = cleanup(self.request.get('title'))
        new_slug = slugify(title)

        if story.slug == new_slug or '-'.join(new_slug.split('-')[:-1]):
            story.delete()
            story = Story.load_new(author, title, new_slug, content, category)
        else:
            story = Story.load_existing(story, author, title, content, category)

        self.redirect('/%s' % (story.slug.title()))

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

class AuthorPage(BaseRequestHandler):
    def get(self, user_id):
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
            self.generate('author_page.html', {
                'errors' : errors,
                })
        else:
            author = Author.get_by_key_name(user_id)
            categories = author.categories #set max num of stories/categories?

        self.generate('author_page.html', {
            'author' : author,
            'categories': categories,
            })

class SingleStoryPage(BaseRequestHandler):
    def get(self, slug):
        story = Story.get_by_key_name(slug.lower())
        
        if not story:
            self.error(404)
            return
            
        self.generate('single_story.html', {
            'story': story,
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

