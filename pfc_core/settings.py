"""
Django settings for pfc_core project.
"""

import os
from pathlib import Path
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# Get SECRET_KEY from environment variable
SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-pfc-platform-development-key-fallback")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Shot Accuracy Tracker Settings
SHOT_TRACKER_ENABLED = True
SHOT_TRACKER_BETA = True
SHOT_TRACKER_MIN_INTERVAL = 300  # milliseconds between shots
SHOT_TRACKER_ACHIEVEMENTS = True
SHOT_TRACKER_HAPTICS = True
SHOT_TRACKER_MAX_SESSIONS_PER_USER = 10  # max active sessions per user
SHOT_TRACKER_SESSION_TIMEOUT = 3600  # seconds (1 hour)
SHOT_TRACKER_RATE_LIMIT = '200/minute'  # API rate limiting

# ALLOWED_HOSTS configuration for Render and Sandbox
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*']
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
# CSRF settings - Updated for current sandbox environment
CSRF_TRUSTED_ORIGINS = [
    'https://8000-i74m7mthbo918tehvjxcd-2d30372b.us2.manus.computer',
    'http://8000-i74m7mthbo918tehvjxcd-2d30372b.us2.manus.computer',
    'https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer',
    'http://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer',
    'https://8000-ijxeiz39tjyehkdgrirle-008a7025.manusvm.computer',
    'http://8000-ijxeiz39tjyehkdgrirle-008a7025.manusvm.computer',
    'https://8000-isph4jv5jdr6izr1ytqe3-1f3945c4.manusvm.computer',
    'http://8000-isph4jv5jdr6izr1ytqe3-1f3945c4.manusvm.computer',
    'https://pfc-platform.onrender.com',
    'http://localhost:8000',
    'https://localhost:8000',
    'http://127.0.0.1:8000',
    'https://127.0.0.1:8000',
]

# Session and CSRF cookie settings for sandbox environment
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
CSRF_COOKIE_SECURE = False  # Set to True in production with HTTPS
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'SAMEORIGIN'

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic", # Add whitenoise
    "django.contrib.staticfiles",
    "rest_framework",
    # PFC Platform apps
    "tournaments",
    "matches",
    "teams",
    "leaderboards",
    "courts",
    "signin",
    "pfc_core",
    "billboard",  # Billboard module for player activity declarations
    "friendly_games",  # New parallel app for friendly games
    "simple_creator",  # Simple Tournament Creator with voucher system
    "shooting",  # Shot Accuracy Tracker
    "practice",  # Shooting Practice Module (v0.1)
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Shot Tracker Middleware
    'shooting.middleware.ShotTrackerSecurityMiddleware',
    'shooting.middleware.ShotTrackerRateLimitMiddleware',
    'shooting.middleware.ShotTrackerSessionCleanupMiddleware',
]

ROOT_URLCONF = "pfc_core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "pfc_core.context_processors.auth_context",
            ],
        },
    },
]

WSGI_APPLICATION = "pfc_core.wsgi.application"

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
# Use dj-database-url to parse the DATABASE_URL environment variable
DATABASES = {
    "default": dj_database_url.config(
        # Replace sqlite fallback with PostgreSQL if needed, but Render provides DATABASE_URL
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

# Feature Flags
FEATURE_SHOOT_TRACKER = True  # Shot Accuracy Tracker feature

# Shot Tracker Configuration
SHOT_TRACKER_SETTINGS = {
    'RATE_LIMIT_SHOTS_PER_MINUTE': 30,
    'SESSION_TIMEOUT_HOURS': 24,
    'MAX_SESSIONS_PER_USER': 5,
    'ENABLE_ACHIEVEMENTS': True,
    'ENABLE_STATISTICS': True,
}

SHOT_TRACKER_PERMISSIONS = {
    'REQUIRE_AUTHENTICATION': True,
    'ALLOW_ANONYMOUS_PRACTICE': False,
    'ALLOW_IN_GAME_TRACKING': True,
    'REQUIRE_MATCH_PARTICIPATION': True,
}

# CORS settings for shot tracker API
SHOT_TRACKER_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    # Add production domains here
]

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/
# https://whitenoise.readthedocs.io/en/stable/django.html

STATIC_URL = "static/"
# Following settings only used if collecting static files
STATIC_ROOT = BASE_DIR / "staticfiles"

# Static files directories
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

# Enable WhiteNoise's GZip compression and forever caching
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = "/var/media"

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Login URL
LOGIN_URL = "/admin/login/"


# Logging Configuration
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "matches": {  # Specific logger for the matches app
            "handlers": ["console"],
            "level": "INFO", # Use INFO for production, DEBUG if needed
            "propagate": True,
        },
        "tournaments": { # Also capture debug from tournaments if needed later
            "handlers": ["console"],
            "level": "INFO", # Use INFO for production, DEBUG if needed
            "propagate": True,
        },
    },
}

# Email settings (using console backend for development/testing)
# For production, configure a real email backend (e.g., SendGrid, Mailgun)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
ADMINS = [("Admin", "admin@example.com")] # Example admin email

# ============================================================================
# FEATURE FLAGS
# ============================================================================

# Shot Accuracy Tracker Feature
FEATURE_SHOOT_TRACKER = True  # Enable/disable shot tracking functionality

# Shot Tracker Settings
SHOT_TRACKER_SETTINGS = {
    'MAX_SESSIONS_PER_USER': 10,  # Maximum active sessions per user
    'MAX_SHOTS_PER_SESSION': 1000,  # Maximum shots per session
    'SESSION_TIMEOUT_HOURS': 24,  # Auto-end sessions after 24 hours
    'RATE_LIMIT_SHOTS_PER_MINUTE': 60,  # Rate limit for shot recording
    'ENABLE_ACHIEVEMENTS': True,  # Enable achievement system
    'ENABLE_PRACTICE_MODE': True,  # Enable practice mode
    'ENABLE_INGAME_MODE': True,  # Enable in-game mode
    'AUTO_END_MATCH_SESSIONS': True,  # Auto-end sessions when match completes
}

# Shot Tracker Permissions
SHOT_TRACKER_PERMISSIONS = {
    'REQUIRE_AUTHENTICATION': True,  # Require user login
    'ALLOW_ANONYMOUS_PRACTICE': False,  # Allow anonymous practice sessions
    'MATCH_PARTICIPANT_ONLY': True,  # Only match participants can track in-game
    'ADMIN_CAN_VIEW_ALL': True,  # Admins can view all sessions
    'USERS_CAN_DELETE_OWN': True,  # Users can delete their own sessions
}

# ============================================================================
# REST FRAMEWORK SETTINGS (for Shot Tracker API)
# ============================================================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'shot_events': SHOT_TRACKER_RATE_LIMIT,
        'shot_recording': '60/min',  # Specific rate limit for shot recording
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20
}
