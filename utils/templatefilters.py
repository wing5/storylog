from google.appengine.ext import webapp

register = webapp.template.create_template_register()

def title_from_slug(value):
    return value.replace('-',' ').title()

register.filter(title_from_slug)
