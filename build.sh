#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Collect static files
python pfc_platform/manage.py collectstatic --no-input

# Apply database migrations
python pfc_platform/manage.py migrate

