import cgi
import os
import re
import unicodedata
from random import random
from functools import wraps

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db

class Author(db.Model):
    name = db.StringProperty(indexed=False)
    user = db.UserProperty(required=True)

    @staticmethod
    def load(user, name = None):
        author = Author.get('user_' + user.user_id())
        return author or Author(
            key_name = 'user_' + user.user_id(),
            name = name or user.nickname(),
            user = user,
            )        

class Category(db.Model): # turn this into a list property?
    name = db.StringProperty()
    slug = db.StringProperty(required=True)
    author = db.ReferenceProperty(Author,
                                  collection_name='categories')

    @staticmethod
    def load(author, cat_name):
        user_id = author.key()
        slug = slugify(cat_name)
        category = Category.get('user_' + user_id + slug)
        return category or Category(
            key_name = 'user_' + user_id + slug
            name = cate_name,
            slug = slug or 'Uncategorized',
            author = author,
            )
 
    @staticmethod
    def remove_if_empty(author, category):
        if not category.stories.get():
            cat.delete()


class Story(db.Model):
    title      = db.StringProperty(required=True, indexed=False)
    safe_title = db.StringProperty(required=True)
    slug       = db.StringProperty(required=True)
    content    = db.TextProperty(required=True) 
    date       = db.DateTimeProperty(auto_now_add=True)
    rand_id    = db.FloatProperty(required=True)
    rating     = db.RatingProperty() # only 0-100
    category   = db.ReferenceProperty(Category,
                                      collection_name='stories')
    author     = db.ReferenceProperty(Author,
                                      collection_name='stories')

    @staticmethod
    def load(author, title, content, category)

    def current_user_has_access(self):
        return self.user_has_access(users.get_current_user())

    def user_has_access(self, user):
        if not user: return False
        query = db.Query(Story)
        query.filter('author =', user)
        return query.get()

    
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
    
        self.generate('index.html', {
            'story': story,})

class CreateStoryPage(BaseRequestHandler):
    def get(self):
        post_url = '/share'
        input_botton = 'Submit'

        self.generate('share.html'. {
            'post_url': post_url,
            'input_button': input_button,
            })

class CreateStoryAction(BaseRequestHandler):
    def post(self):
        

class EditStoryPage(BaseRequestHandler):
    def get(self):
        slug = self.request.get('slug')
        story = Story.get('slug_' + slug)

        if not story or not story.current_user_has_access():
            self.error(403)
            return
        
        post_url = '/edit/%s' % (story.key())
        input_button = 'Save'

        self.generate('share.html', {
            'story': story,
            'post_url': post_url,
            'input_button': input_button,
            })
        

    def post(self, editing = None):
        title = cleanup(self.request.get('title'))
        safe_title = slugify(title)
        slug = make_unique_slug(safe_title)
        content = cleanup(self.request.get('content'))
        author = users.get_current_user()
        category_name = cleanup(self.request.get('category_name'))

        if len(title) < 4 or len(content) < 300:
            self.error(403)
            return

        if not editing:
            category = Category.load(category_name, author)
            category.put()
            
            story = Story(
                author = author,
                author_id = author.user_id(),
                title = title,
                safe_title = safe_title,
                slug = slug,
                content = content,
                rand_id = random(),
                category = category,
                )

            story.put()
        else:
            query = Story.all()
            query.filter('author =', author)
            query.filter('slug =', editing)
            story = query.get()
            old_category_name = story.category.name

            if not story:
                self.error(403)
                return

            if story.safe_title != safe_title:
                story.safe_title = safe_title
                story.slug = make_unique_slug(safe_title)

            if old_category_name != category_name:
                category = Category.load(category_name, author)
                category.put()
                story.category = category
                
            story.title = title
            story.content = content
            story.put()
            Category.remove_if_empty(old_category_name, author)

        self.redirect('/story/%s' % (story.slug))


class UserPage(BaseRequestHandler):
    def get(self, author_id = None):

        if not author_id:
            categories = Category.all().filter('author =', users.get_current_user()).order('name').fetch(100)
            page_title = "Your Stories"
        else:
            categories = Category.all().filter('author_id =', author_id).order('name').fetch(100)
            page_title = users.User(_user_id=author_id).nickname()
    
        self.generate('userpage.html', {
            'categories': categories,
            'page_title': page_title,
            'author_id': author_id,
            })

class StoryPage(BaseRequestHandler):
    def get(self, slug):
        story = db.Query(Story).filter("slug =", slug).get()            
        
        if not story:
            self.error(404)
            return
            
        self.generate('index.html', {
            'story': story,
            })

  
application = webapp.WSGIApplication(
    [('/', MainPage),
     ('/share', Write),
     ('/you', UserPage),
     (r'/author/([^/]+)', UserPage),
     (r'/story/([^/]+)', StoryPage),
     (r'/edit/([^/]+)', Write)],
    debug=True)

def main():
  run_wsgi_app(application)

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).lower()) # removed strip()
    return re.sub('[-\s]+', '-', value)

def strip_tags(value):
    """Returns the given HTML with all tags stripped."""
    return re.sub(r'<[^>]*?>', '', value)

def cleanup(content):
            return strip_tags(content.strip())

def make_unique_slug(safe_title):
    same_title_count = Story.gql("WHERE safe_title = :1", safe_title).count()
    if same_title_count == 0:
        return safe_title
    if same_title_count > 0:
        return safe_title + "-%s" % (same_title_count)

if __name__ == "__main__":
  main()

