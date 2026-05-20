import os
import sys

# Project path
project_home = os.path.dirname(__file__)
sys.path.insert(0, project_home)

# Django settings
os.environ['DJANGO_SETTINGS_MODULE'] = 'ecommercesite.settings'

# Activate virtual environment (IMPORTANT in cPanel)
activate_env = os.path.join(project_home, 'venv', 'bin', 'activate_this.py')
if os.path.exists(activate_env):
    with open(activate_env) as f:
        exec(f.read(), dict(__file__=activate_env))

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()