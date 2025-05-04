#!/bin/bash

# Create necessary directories for media and static files
mkdir -p media/match_evidence
mkdir -p static

# Make migrations for all apps
python manage.py makemigrations tournaments
python manage.py makemigrations matches
python manage.py makemigrations teams
python manage.py makemigrations leaderboards

# Apply migrations
python manage.py migrate

# Create a superuser for admin access
echo "Creating superuser for admin access"
python manage.py createsuperuser --noinput --username admin --email admin@example.com

# Set password for the superuser
python manage.py shell -c "from django.contrib.auth.models import User; User.objects.filter(username='admin').update(password='pbkdf2_sha256\$600000\$VeVkLU8mZQhqbsXE\$U0Qp0MPQT7JyQSDD9ZJ5JNiQAgsE9OMJQp9q/QLRqGs=')"

# Collect static files
python manage.py collectstatic --noinput

# Run the development server
echo "Starting development server on port 8000"
python manage.py runserver 0.0.0.0:8000
