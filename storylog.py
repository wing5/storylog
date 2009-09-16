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

    def __init__(self, *args, **kwargs):
        """Automatically sets an Author key's name to the current
        user's ID.
        """
        kwargs['key_name'] = users.get_current_user().user_id()
        db.Model.__init__(self, *args, **kwargs)

    @staticmethod
    def load(user, name = ''):
        """Returns a new or existing Author entity for the specified
        user. If name is given, Author's name is changed to that.
        """
        name = name.strip()
        author = Author.get_by_key_name(user.user_id())
        if author and not name:
            return author
        elif author and name:
            if author.name == name:
                return author
            else:
                author.name = name
                author.put()
                return author
        else:
            author = Author(
                name = name or user.nickname(),
                )
            author.put()
            return author

class Category(db.Model): 
    name = db.StringProperty()
    slug = db.StringProperty(required=True)
    author = db.ReferenceProperty(Author,
                                  collection_name='categories')

    def __init__(self, *args, **kwargs):
        """Automatically sets a Category's key name to the category's
        slug concatenated to the current user's ID.
        """
        user_id = kwargs['author'].name()
        cat_slug = kwargs['slug']
        kwargs['key_name'] = user_id + cat_slug
        db.Model.__init__(self, *args, **kwargs)

    @staticmethod
    def load(author, cat_name):
        """Takes an Author and a cleaned up Category name as parameters;
        returns an existing Category if one with the same name and Author
        exists. Otherwise, a new Category is created.
        """
        user_id = author.key().name()
        cat_slug = slugify(cat_name)
        category = Category.get_by_key_name(user_id + (cat_slug or 'uncategorized'))
        if category:
            return category
        else:
            category = Category(
                name = cat_name,
                slug = cat_slug or 'uncategorized',
                author = author,
            )
            category.put()
            return category
 
    @staticmethod
    def remove_if_empty(author, category):
        if not category.stories.filter('author =', author).get():
            category.delete()


class Story(db.Model):
    title         = db.StringProperty(required=True, indexed=False)
    slug          = db.StringProperty(required=True)
    content       = db.TextProperty(required=True) 
    date          = db.DateTimeProperty(auto_now_add=True)
    rand_id       = db.FloatProperty(required=True)
    #rating_mean  = db.RatingProperty() # only 0-100
    #rating_count = db.RatingProperty(indexed=False) # only 0-100
    category      = db.ReferenceProperty(Category,
                                         collection_name='stories')
    author        = db.ReferenceProperty(Author,
                                         collection_name='stories') # necessary?

    def __init__(self, *args, **kwargs):
        kwargs['key_name'] = kwargs['slug']
        kwargs['rand_id'] = random()
        db.Model.__init__(self, *args, **kwargs)
        
    @staticmethod
    def load_new(author, title, slug, content, category):
        slug = Story.make_unique_slug(slug)
        story = Story(
            author = author,
            title = title,
            slug = slug,
            content = content,
            category = category,
            )
        story.put()
        return story

    @staticmethod
    def load_existing(story, author, title, content, category):
        story.author = author
        story.title = title
        story.content = content
        story.category = category
        story.put()
        return story

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
        """Returns 'slug-' + (1-5) or an error if none of those slugs
        are available.
        """
        new_slug = slug + '-' + attempt
        story = Story.get_by_key_name(new_slug)
        if not story:
            return new_slug
        elif attempt < 5:            
            attempt += 1
            return Story.find_unique_slug(new_slug, attempt)
        else:
            return naming_error("Please pick a different title.") # make this function!

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
        story = Story.gql("WHERE rand_id > :rand ORDER BY rand_id", rand=random()).get()
    
        self.generate('base.html', {
            'story': story,})

class CreateStoryPage(BaseRequestHandler):
    @login_required
    def get(self):
        self.generate('create_story.html')

class CreateStoryAction(BaseRequestHandler):
    def post(self):
        user = users.get_current_user()

        nickname = cleanup(self.request.get('nickname'))
        author = Author.load(user, nickname)

        category_name = cleanup(self.request.get('category_name'))
        category = Category.load(author, category_name)
        
        content = db.Text(cleanup(self.request.get('content')))

        title = cleanup(self.request.get('title'))
        slug = slugify(title)

        story = Story.load_new(author, title, slug, content, category)

        self.redirect('/Story:%s' % (story.slug.title()))


class EditStoryPage(BaseRequestHandler):
    @login_required
    def get(self, slug):
        user = users.get_current_user()
        story = Story.get_by_key_name(slug.lower())

        if not story or not story.user_has_access(user, story):
            self.error(403)
            return
        
        self.generate('edit_story.html', {
            'story': story,
            })

class EditStoryAction(BaseRequestHandler):
    def post(self):
        user = users.get_current_user()
        story_key = self.request.get('story')
        
        story = Story.get(story_key)
        
        #if not story or story.user_has_access(user, story):

        nickname = cleanup(self.request.get('nickname'))
        author = Author.load(user, nickname)

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
    def get(self, *args):
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
        else:
            self.error(404)
            return

        self.generate('author_page.html', {
            'author': author,
            })

class UserProfilePage(BaseRequestHandler):
    @login_required
    def get(self):
        user = users.get_current_user()

        if user:
            author = Author.load(user)
        else:
            self.error(403)
            return

        self.generate('author_page.html', {
            'author': author,
            })

class SingleStoryPage(BaseRequestHandler):
    def get(self, slug):
        story = Story.get_by_key_name(slug.lower())
        
        if not story:
            self.error(404)
            return
            
        self.generate('base.html', {
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

