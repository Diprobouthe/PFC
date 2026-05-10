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
DEBUG = os.environ.get("DEBUG", "True") == "True"

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
ALLOWED_HOSTS = [
    # Local development
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    # Manus sandbox testing domains
    '8000-il5kjf1wne3gydpvqrj08-3f2b35cd.us2.manus.computer',
    '8000-i74m7mthbo918tehvjxcd-2d30372b.us2.manus.computer',
    '8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer',
    '8000-ijxeiz39tjyehkdgrirle-008a7025.manusvm.computer',
    '8000-isph4jv5jdr6izr1ytqe3-1f3945c4.manusvm.computer',
    # Production domains
    'pfc.events',
    'www.pfc.events',
    'pfc-e1ce.onrender.com',
    'pfc-platform.onrender.com',
    '8000-i3s0rjhjuovyc5djxtgnl-3bf937d8.us2.manus.computer',
]
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
# CSRF settings - Updated for current sandbox environment
CSRF_TRUSTED_ORIGINS = [
    'https://8000-il5kjf1wne3gydpvqrj08-3f2b35cd.us2.manus.computer',
    'http://8000-il5kjf1wne3gydpvqrj08-3f2b35cd.us2.manus.computer',
    'https://8000-i74m7mthbo918tehvjxcd-2d30372b.us2.manus.computer',
    'http://8000-i74m7mthbo918tehvjxcd-2d30372b.us2.manus.computer',
    'https://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer',
    'http://8000-i3h5t5fooex7a987mj80g-e785601b.manusvm.computer',
    'https://8000-ijxeiz39tjyehkdgrirle-008a7025.manusvm.computer',
    'http://8000-ijxeiz39tjyehkdgrirle-008a7025.manusvm.computer',
    'https://8000-isph4jv5jdr6izr1ytqe3-1f3945c4.manusvm.computer',
    'http://8000-isph4jv5jdr6izr1ytqe3-1f3945c4.manusvm.computer',
    'https://pfc-platform.onrender.com',
    'https://8000-i3s0rjhjuovyc5djxtgnl-3bf937d8.us2.manus.computer',
    'http://8000-i3s0rjhjuovyc5djxtgnl-3bf937d8.us2.manus.computer',
    'https://pfc.events',
    'https://www.pfc.events',
    'https://pfc-e1ce.onrender.com',
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

# Persistent session: ~6 months (180 days)
SESSION_COOKIE_AGE = 60 * 60 * 24 * 180  # 180 days in seconds
SESSION_SAVE_EVERY_REQUEST = True  # Refresh expiry on every request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Survive browser restarts

# Google OAuth credentials (set via environment variables in production)
GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '')
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get('GOOGLE_OAUTH_REDIRECT_URI', 'http://localhost:8000/player-auth/google/callback/')

# Application definition

INSTALLED_APPS = [
    "daphne",
    "channels",
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
    "player_auth",  # Player Identity System (Google + Email OTP)
    "pfc_events",    # Minimal WebSocket event layer for live match transitions
    "invites",       # Targeted invitation system (play + team build)
]

# ---------------------------------------------------------------------------
# Django Channels — Redis in production, InMemory for local dev
# Set REDIS_URL environment variable on Render to activate Redis.
# ---------------------------------------------------------------------------
_REDIS_URL = os.environ.get("REDIS_URL", "")
if _REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [_REDIS_URL],
            },
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

ASGI_APPLICATION = "pfc_core.asgi.application"

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
# On Render, the persistent disk is mounted at /var/media (set via MEDIA_ROOT env var).
# Locally falls back to BASE_DIR/media.
_RENDER_MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "")
MEDIA_ROOT = Path(_RENDER_MEDIA_ROOT) if _RENDER_MEDIA_ROOT else BASE_DIR / "media"

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

# ── Email configuration ──────────────────────────────────────────────────────
# Production (Render): set EMAIL_HOST in the environment to activate SMTP.
# Local / dev: EMAIL_HOST absent → emails printed to console, no SMTP needed.
#
# Brevo SMTP environment variables (set in Render dashboard):
#   EMAIL_HOST=smtp-relay.brevo.com
#   EMAIL_PORT=587
#   EMAIL_HOST_USER=<your-brevo-login>
#   EMAIL_HOST_PASSWORD=<your-brevo-smtp-key>
#   EMAIL_USE_TLS=True
#   DEFAULT_FROM_EMAIL=noreply@pfc.events
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND       = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST          = os.environ.get("EMAIL_HOST")
    EMAIL_PORT          = int(os.environ.get("EMAIL_PORT", 587))
    EMAIL_USE_TLS       = os.environ.get("EMAIL_USE_TLS", "True") == "True"
    EMAIL_HOST_USER     = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    DEFAULT_FROM_EMAIL  = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@pfc.events")
else:
    # Development fallback — emails printed to console, no SMTP required
    EMAIL_BACKEND      = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "noreply@pfc.events"
ADMINS = [("Admin", os.environ.get("ADMIN_EMAIL", "admin@pfc.events"))]

# ============================================================================
# FEATURE FLAGS
# ============================================================================

# Shot Accuracy Tracker Feature
FEATURE_SHOOT_TRACKER = True  # Enable/disable shot tracking functionality

# ---------------------------------------------------------------------------
# TEMPORARY: Admin OTP Inspection
# ---------------------------------------------------------------------------
# Allows Django admin to display plaintext OTP codes for EmailOTP records.
# Purpose: operational/testing aid during auth layer stabilisation only.
# Set to False (or remove this line) to hide codes from admin before going
# to production. Removing this flag requires no changes to auth logic.
# ---------------------------------------------------------------------------
ENABLE_ADMIN_OTP_INSPECTION = True

# ---------------------------------------------------------------------------
# Friendly Games — Default Court Complex
# ---------------------------------------------------------------------------
# PK of the CourtComplex used as the default when a player creates a friendly
# game without selecting a complex.  Set to None to fall back to the first
# complex in the database.  Change to match your actual CourtComplex PK.
# ---------------------------------------------------------------------------
FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID = 1

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
