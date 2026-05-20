import os
import sys

# Add project path
sys.path.insert(0, os.path.dirname(__file__))

# Set Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ecommercesite.settings")

# Load Django WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()