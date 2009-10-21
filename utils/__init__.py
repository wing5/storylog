import unicodedata
import re

def slugify(value):
    """Normalizes an already stripped string, converts to lowercase,
    removes non-alpha characters, and converts spaces to hyphens. 
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).lower()) # removed strip()
    return re.sub('[-_\s]+', '-', value)

#def strip_tags(value):
#    """Returns the given HTML with all tags stripped."""
#    return re.sub(r'<[^>]*?>', '', value)

def escape(html):
    """    Returns the given HTML with ampersands, quotes and angle
    brackets encoded.
    """
    return html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

def cleanup(content):
    """Returns the given content with HTML escaped and extra whitespace
    padding removed.
    """
    return escape(content.strip())

def cleanup_all(unsafe_list):
    return [cleanup(item) for item in unsafe_list]
