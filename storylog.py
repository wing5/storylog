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
    user = db.UserProperty(required=True)
    favorites = db.ListProperty(db.Key) #implement

    def __init__(self, *args, **kwds):
        """Assigns a given user's id as the author's key name.
        Assigns a given user's nickname as the author's name.
        """
        db.Model.__init__(self, *args, **kwds)

    def user_has_access(self, user):
        return user.user_id() == self.key().name()

class Category(db.Model): 
    author = db.ReferenceProperty(Author,
                                  collection_name='categories')
    name = db.StringProperty(default='')
    slug = db.StringProperty(default='')    

    @staticmethod
    def remove_if_empty(author, category):
        if not category.stories.filter('author =', author).get():
            category.delete()

    def user_has_access(self, user):
        """get_value_for_datastore returns the author's key
        without a db lookup
        alternate: ...== self.author.key().name()
        """
        return user.user_id() == Category.author.get_value_for_datastore(self).name()


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
        """get_value_for_datastore returns the author's key without a db lookup
        alternate: ...== self.author.key().name()
        """
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
    #Author created here or w/ EditNicknameAction or w/ Favorite
    def post(self):
        user = users.get_current_user()
        user_id = user.user_id()
        title = cleanup(self.request.get('title'))
        if title:
            slug = Story.make_unique_slug(title) # sorta expensive db call
        
        errors = []

        if not title:
            errors.append('Please enter a title.')
        else:
            if slug == ' error ':
                errors.append("Please change your story's title. Exactly six other people have already chosen a very similar title.")
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if not errors:
            author = Author.get_by_key_name(user_id)
            if not author:
                nickname = user.nickname().split('@')[0]
                author = Author(
                    key_name = user_id,
                    user = user,
                    name = nickname)
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
        else:
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
        if title:
            slug = Story.make_unique_slug(title) # sorta expensive db call
        
        errors = []

        if not user or not story or not story.user_has_access(user):
            errors.append("You cannot edit this story.")
        if not title:
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
        else:
            self.generate('edit_story.html', {
                'errors': errors,
                'title': self.request.get('title'),
                'content': self.request.get('content'),
                'category_name': self.request.get('category_name'),
                })

class DeleteStoryPage(BaseRequestHandler):
    @login_required
    def get(self, slug):
        user = users.get_current_user()
        user_id = user.user_id()
        story = Story.get_by_key_name(slug.lower())
        errors = []

        if not user or not story or not story.user_has_access(user):
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
        user = users.get_current_user()
        user_id = user.user_id()
        author = Author.get_by_key_name(user_id)
        story = Story.get(self.request.get('story_key'))
        errors = []

        if not author or not story or not story.user_has_access(user):
            errors.append("You cannot delete this story.")
        if not errors:
            story_category = story.category
            story.delete()
            Category.remove_if_empty(author, story_category)
            self.redirect('/You')
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                })

class DeleteCategoryPage(BaseRequestHandler):
    @login_required
    def get(self, user_id, cat_slug):
        user = users.get_current_user()
        category = Category.get_by_key_name(user_id + cat_slug.lower())
        errors = []

        if not user or not category or not category.user_has_access(user):
            errors.append("You cannot delete this category.")
        if not errors:
            self.generate('delete_page.html', {
                'category': category,
                })
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                })

class DeleteCategoryAction(BaseRequestHandler):
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
            for story in stories:
                story.category = empty_cat
                story.put()
            category.delete()
            self.redirect('/You')
        else:
            self.generate('delete_page.html', {
                'errors': errors,
                })

class CategoryPage(BaseRequestHandler):
    def get(self, user_id, cat_slug):
        author = Author.get_by_key_name(user_id)
        category = Category.get_by_key_name(user_id + cat_slug.lower())
        errors = []

        if not author:
            errors.append("This is not a valid Author page. Sorry.")
        if not category:
            errors.append("This is not a valid Category page. Sorry.")
        if not errors:
            self.generate('category_page.html', {
                'author': author,
                'category': category,
                })
        else:
            self.generate('category_page.html', {
                'errors': errors,
                })

class AuthorPage(BaseRequestHandler):
    def get(self, user_id):
        author = Author.get_by_key_name(user_id)
        errors = []
        
        if not author:
            errors.append("This is not a valid author page. Sorry.")
        if not errors:
            categories = author.categories
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
            errors.append('Please enter a nickname.')
        if not author or not  author.user_has_access(user):
            errors.append('You cannot edit this nickname. Sorry.')
        if not errors:
            author.name = new_name
            author.put()
            self.redirect('/You')
        else:
            self.generate('edit_author.html', {
                'author': author,
                'errors': errors,
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
                    'author': author,
                    'categories': categories,
                    })
            else:
                #display the page even if user hasn't created a story yet
                self.generate('author_page.html')
        else:
            self.generate('author_page.html', {
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
     ('(?i)/Share', CreateStoryPage),
     ('/createstory.do', CreateStoryAction),
     ('/editstory.do', EditStoryAction),
     ('(?i)/Edit/([^/]+)', EditStoryPage),
     ('(?i)/Delete/([^/]+)', DeleteStoryPage),
     ('/deletestory.do', DeleteStoryAction),
     ('(?i)/DeleteCategory/([^/]+)/([^/]+)', DeleteCategoryPage),
     ('/deletecategory.do', DeleteCategoryAction),
     ('(?i)/Author/([^/]+)/Category/([^/]+)', CategoryPage),
     ('(?i)/Author/([^/]+)', AuthorPage),
     ('(?i)/EditAuthor', EditAuthorPage),
     ('/editauthor.do', EditAuthorAction),
     ('/([^/]+)', SingleStoryPage)],
    debug=True)

def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()

