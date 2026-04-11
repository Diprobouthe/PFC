#!/usr/bin/env python3
"""
Flask wrapper for Django PFC Platform deployment
"""
import os
import sys
from flask import Flask, request, Response
from werkzeug.serving import WSGIRequestHandler

# Add the project directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')

# Import Django
import django
django.setup()

from django.core.wsgi import get_wsgi_application

# Get Django WSGI application
django_app = get_wsgi_application()

# Create Flask app
app = Flask(__name__)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def proxy_to_django(path):
    """Proxy all requests to Django application"""
    environ = request.environ.copy()
    environ['PATH_INFO'] = '/' + path
    
    def start_response(status, headers):
        pass
    
    response_iter = django_app(environ, start_response)
    response_data = b''.join(response_iter)
    
    return Response(response_data, content_type='text/html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)

