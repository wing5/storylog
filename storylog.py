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
    user = db.UserProperty(required=True) #unnecessary? since key name is uid
    favorites = db.ListProperty(db.Key) #implement

    def favorite_stories(self):
        return Story.get(self.favorites)

    def some_favorite_stories(self):
        return Story.get(self.favorites[:5])

    def user_has_access(self, user):
        return user.user_id() == self.key().name()

def get_nickname_and_data(user):
    user_id = user.user_id()
    data = UserData.get_by_key_name(user_id)
    if not data:
        return user.nickname(), None
    else:
        return data.name, data

class UserData(db.Model):
    #key_name = user_id
    name = db.StringProperty(required=True, indexed=False)
    favorite_stories = db.ListProperty(db.Key)
    favorite_categories = db.ListProperty(db.Key)
    stories = db.ListProperty(db.key)

    def user_has_access(self, user):
        return user.user_id() == self.key().name()

    def get_favorite_stories(self, num=None):
        if num:
            return Story.get(self.favorite_stories[:num])
        else:
            return Story.get(self.favorite_stories)

    def get_favorite_categories(self, num):
        if num:
            return Story.get(self.favorite_categories[:num])
        else:
            return Story.get(self.favorite_categories)

class Category(db.Model): 
    author = db.ReferenceProperty(Author,
                                  collection_name='categories')
    name = db.StringProperty(default='')
    slug = db.StringProperty(default='')
    #nice to have for remove_if_empty and displaying a more link
    #story_count = db.IntegerProperty(required=True)

    def some_stories(self):
        return self.stories.fetch(5)

    def remove_if_empty(self, author):
        if not self.stories.filter('author =', author).get():
            self.delete()

    def user_has_access(self, user):
        """get_value_for_datastore returns the author's key
        without a db lookup
        alternate: ...== self.author.key().name()
        """
        return user.user_id() == Category.author.get_value_for_datastore(self).name()


class Story(db.Model):
    author = db.ReferenceProperty(Author,
                                  collection_name='stories')
    title = db.StringProperty(required=True, indexed=False)
    content = db.TextProperty(required=True) 
    category = db.ReferenceProperty(Category,
                                    collection_name='stories')
    rand_id = db.FloatProperty(required=True)
    date = db.DateTimeProperty(auto_now_add=True)
    #favorited_by = db.ListPropery(db.Key)

    def slug(self):
        return self.key().name().title()

    def favorited_by_current_user(self):
        user_id = users.get_current_user().user_id()
        author = Author.get_by_key_name(user_id)
        if author and (self.key() in author.favorites):
            return True
        else:
            return False

    def belongs_to_current_user(self):
        user_id = users.get_current_user().user_id()
        return user_id == Story.author.get_value_for_datastore(self).name()

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

    def user_has_access(self, user):
        """get_value_for_datastore returns the author's key without a db lookup
        alternate (with db lookup): ...== self.author.key().name()
        """
        return user.user_id() == Story.author.get_value_for_datastore(self).name()
    
class BaseRequestHandler(webapp.RequestHandler):
    def get_author_from_user(self, user):
        user_id = user.user_id()
        author = Author.get_by_key_name(user_id)
        if not author:
            nickname = user.nickname().split('@')[0]
            author = Author(
                key_name = user_id,
                user = user,
                name = nickname)
            author.put()
        return author
            
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

class FavoriteStoryAction(BaseRequestHandler):
    def post(self):
        user = users.get_current_user()
        story = Story.get(self.request.get('story'))
        # favoriting your own story isn't allowed
        if not user or story.belongs_to_current_user:
            self.redirect('/%s' % story.slug())
            return

        author = self.get_author_from_user(user)

        if story.key() in author.favorites:
            author.favorites.remove(story.key())
            author.put()
        else:
            author.favorites.append(story.key())
            author.put()
        
        self.redirect('/%s' % story.slug())

class CreateStoryPage(BaseRequestHandler):
    @login_required
    def get(self):
        self.generate('create_story.html')

class CreateStoryAction(BaseRequestHandler):
    #Author created here or w/ EditAuthorAction or w/ FavoriteAction
    def post(self):
        user = users.get_current_user()
        user_id = user.user_id()
        title = cleanup(self.request.get('title'))
        category_name = cleanup(self.request.get('category_name'))
        if title:
            slug = Story.make_unique_slug(title)
        
        errors = []

        if not title:
            errors.append('Please enter a title.')
        else:
            #if there's a title, there's a slug
            if slug == ' error ':
                errors.append("Please change your story's title. Exactly six other people have already chosen a very similar title.")
            if not len(title) < 36:
                errors.append('Please enter a title with 35 letters or less.')
        if category_name:
            if not len(category_name) < 36:
                errors.append('Please enter a category name with 35 letters or less.')
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if not errors:
            author = self.get_author_from_user(user)

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
            self.redirect('/%s' % (story.slug())) 

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
        category_name = cleanup(self.request.get('category_name'))
        slug = ''
        #you don't want to search for a new slug if you're using the same title
        if title and story.title != title:
            slug = Story.make_unique_slug(title)
        
        errors = []

        if not user or not story or not story.user_has_access(user):
            errors.append("You cannot edit this story.")
        if not title:
            errors.append('Please enter a title.')
        else:
            if slug == ' error ':
                errors.append("Please change your story's title. Six other people have already chosen a very similar title.")
            if not len(title) < 36:
                errors.append('Please enter a title with 35 letters or less.')
        if category_name:
            if not len(category_name) < 36:
                errors.append('Please enter a category name with 35 letters or less.')
        if not self.request.get('content'):
            errors.append('Please enter a story.')
        if not errors:
            content = db.Text(cleanup(self.request.get('content')))
            author = Author.get_by_key_name(user_id)
            if not author:
                self.redirect("/%s" % story.slug())
                return

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
            old_category.remove_if_empty(author)
            #all outgoing urls should be in title format
            self.redirect('/%s' % (story.key().name().title())) 
        else:
            self.generate('edit_story.html', {
                'errors': errors,
                'story_key': story_key,
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
            story_category.remove_if_empty(author)
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
     ('(?i)/Share', CreateStoryPage),
     ('/createstory.do', CreateStoryAction),
     ('/editstory.do', EditStoryAction),
     ('(?i)/Edit/([^/]+)', EditStoryPage),
     ('(?i)/Delete/([^/]+)', DeleteStoryPage),
     ('/deletestory.do', DeleteStoryAction),
     ('(?i)/DeleteCategory/([^/]+)/([^/]+)', DeleteCategoryPage),
     ('/deletecategory.do', DeleteCategoryAction),
     ('(?i)/Author/([^/]+)/Favorites', FavoriteStoriesPage),
     ('(?i)/Author/([^/]+)/Category/([^/]+)', CategoryPage),
     ('(?i)/Author/([^/]+)', AuthorPage),
     ('(?i)/EditAuthor', EditAuthorPage),
     ('/editauthor.do', EditAuthorAction),
     ('(?i)/Favorite', FavoriteStoryAction),
     ('/([^/]+)', SingleStoryPage)],
    debug=True)

def main():
  run_wsgi_app(application)


if __name__ == "__main__":
  main()

