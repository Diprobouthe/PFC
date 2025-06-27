#!/usr/bin/env python3
"""
Flask wrapper for Django PFC Platform deployment
"""
import os
import sys
from django.core.wsgi import get_wsgi_application

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')

# Get Django WSGI application
application = get_wsgi_application()

if __name__ == '__main__':
    # For local testing
    from django.core.management import execute_from_command_line
    execute_from_command_line(['manage.py', 'runserver', '0.0.0.0:8000'])

