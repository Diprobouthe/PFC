"""
player_auth/views.py — Google OAuth + Email OTP auth views
"""

import json
import urllib.parse
import urllib.request
import secrets
import logging
import hashlib
import base64
import time

from django.conf import settings
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from pfc_core.session_utils import CodenameSessionManager
from .models import PFCUser, EmailOTP

logger = logging.getLogger(__name__)

_KEY_PAUTH_USER_ID = 'pauth_user_id'
_KEY_PAUTH_PENDING_EMAIL = 'pauth_pending_email'
_KEY_PAUTH_STATE = 'pauth_oauth_state'
_KEY_PAUTH_VERIFIER = 'pauth_oauth_verifier'
_KEY_PAUTH_STARTED = 'pauth_oauth_started'
_OAUTH_TTL = 600

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'


def _complete_login(request, pfc_user):
    """Finish authentication without exposing the legacy player-link screen.

    Any authenticated identity without a Player gets one automatically.  The
    legacy codename-link backend remains available for compatibility/recovery,
    but it is no longer part of normal Google/email onboarding.
    """
    if not pfc_user.is_active:
        messages.error(request, 'This account is unavailable.')
        return redirect('player_auth:login')
    pfc_user.record_login()

    if not pfc_user.player:
        try:
            with transaction.atomic():
                locked_user = PFCUser.objects.select_for_update().get(pk=pfc_user.pk)
                if not locked_user.player:
                    locked_user.legacy_link_skipped = True
                    locked_user.save(update_fields=['legacy_link_skipped'])
                    locked_user.create_and_link_player()
                pfc_user = locked_user
        except Exception:
            logger.exception(
                "Automatic Player creation failed for PFCUser %s",
                pfc_user.pk,
            )
            messages.error(
                request,
                "We could not finish creating your player profile. Please try again.",
            )
            return redirect('player_auth:login')

    request.session.pop(_KEY_PAUTH_USER_ID, None)
    codename = pfc_user.codename
    if not codename:
        messages.error(request, 'Could not resolve your player profile.')
        return redirect('player_auth:login')
    request.session.cycle_key()
    CodenameSessionManager.login_player(request, codename)
    return redirect('/')


def _get_pending_user(request):
    user_id = request.session.get(_KEY_PAUTH_USER_ID)
    if not user_id:
        return None
    try:
        return PFCUser.objects.get(id=user_id)
    except PFCUser.DoesNotExist:
        return None


def _google_configured():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET
                and settings.GOOGLE_OAUTH_REDIRECT_URI)


def login_page(request):
    if CodenameSessionManager.is_logged_in(request):
        return redirect('/')
    google_configured = _google_configured()
    return render(request, 'player_auth/login.html', {
        'google_configured': google_configured,
        'next': request.GET.get('next', '/'),
    })


@require_http_methods(['GET'])
def google_login(request):
    if not _google_configured():
        messages.error(request, 'Google login is not configured.')
        return redirect('player_auth:login')
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    request.session[_KEY_PAUTH_STATE] = state
    request.session[_KEY_PAUTH_VERIFIER] = verifier
    request.session[_KEY_PAUTH_STARTED] = time.time()
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'prompt': 'select_account',
    }
    url = GOOGLE_AUTH_URL + '?' + urllib.parse.urlencode(params)
    return redirect(url)


@require_http_methods(['GET'])
def google_callback(request):
    state = request.GET.get('state')
    expected = request.session.pop(_KEY_PAUTH_STATE, None)
    verifier = request.session.pop(_KEY_PAUTH_VERIFIER, None)
    started = request.session.pop(_KEY_PAUTH_STARTED, None)
    if (not _google_configured() or not state or not expected or not verifier
            or not isinstance(started, (int, float)) or not 0 <= time.time() - started <= _OAUTH_TTL
            or not secrets.compare_digest(state.encode(), expected.encode())):
        messages.error(request, 'Authentication failed: invalid state. Please try again.')
        return redirect('player_auth:login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, 'Google login was cancelled or failed.')
        return redirect('player_auth:login')

    token_data = {
        'code': code,
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
        'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
        'grant_type': 'authorization_code',
        'code_verifier': verifier,
    }
    try:
        req = urllib.request.Request(
            GOOGLE_TOKEN_URL,
            data=urllib.parse.urlencode(token_data).encode(),
            method='POST',
        )
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        with urllib.request.urlopen(req, timeout=10) as resp:
            tokens = json.loads(resp.read())
    except Exception as e:
        logger.warning('Google token exchange failed (%s)', type(e).__name__)
        messages.error(request, 'Google login failed. Please try again.')
        return redirect('player_auth:login')

    access_token = tokens.get('access_token') if isinstance(tokens, dict) else None
    if not access_token:
        messages.error(request, 'Google login failed: no access token received.')
        return redirect('player_auth:login')

    try:
        req2 = urllib.request.Request(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            user_info = json.loads(resp2.read())
    except Exception as e:
        logger.warning('Google userinfo fetch failed (%s)', type(e).__name__)
        messages.error(request, 'Could not retrieve your Google profile. Please try again.')
        return redirect('player_auth:login')

    if not isinstance(user_info, dict):
        messages.error(request, 'Invalid Google profile.')
        return redirect('player_auth:login')
    raw_email = user_info.get('email')
    google_sub = user_info.get('sub')
    email = raw_email.lower().strip() if isinstance(raw_email, str) else ''
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Google did not provide a valid email address.')
        return redirect('player_auth:login')
    if (len(email) > 254 or not isinstance(google_sub, str) or not google_sub
            or len(google_sub) > 128 or user_info.get('email_verified') is not True):
        messages.error(request, 'Google did not provide a verified identity.')
        return redirect('player_auth:login')

    display_name = user_info.get('name')
    display_name = display_name.strip()[:100] if isinstance(display_name, str) else ''
    avatar_url = user_info.get('picture')
    avatar_url = avatar_url[:200] if isinstance(avatar_url, str) and avatar_url.startswith('https://') else ''
    # Google is authoritative for Gmail and verified Workspace identities,
    # but not necessarily for third-party email addresses.
    authoritative_email = email.endswith('@gmail.com') or bool(user_info.get('hd'))
    try:
        with transaction.atomic():
            pfc_user = PFCUser.objects.select_for_update().filter(google_sub=google_sub).first()
            if not pfc_user:
                pfc_user = PFCUser.objects.select_for_update().filter(email=email).first()
                if pfc_user:
                    if pfc_user.google_sub or not authoritative_email:
                        messages.error(request, 'Use your existing PFC login method.')
                        return redirect('player_auth:login')
                    if not pfc_user.is_active:
                        messages.error(request, 'This account is unavailable.')
                        return redirect('player_auth:login')
                    pfc_user.google_sub = google_sub
                    pfc_user.save(update_fields=['google_sub'])
                else:
                    # For non-authoritative email addresses, require the existing
                    # email login path rather than creating a Google-linked identity.
                    if not authoritative_email:
                        messages.error(request, 'Please sign in with your email code.')
                        return redirect('player_auth:login')
                    pfc_user = PFCUser.objects.create(
                        email=email, provider=PFCUser.PROVIDER_GOOGLE,
                        google_sub=google_sub, display_name=display_name,
                        avatar_url=avatar_url,
                    )
            if not pfc_user.is_active:
                messages.error(request, 'This account is unavailable.')
                return redirect('player_auth:login')
            pfc_user.display_name = display_name or pfc_user.display_name
            pfc_user.avatar_url = avatar_url or pfc_user.avatar_url
            pfc_user.save(update_fields=['display_name', 'avatar_url'])
    except IntegrityError:
        messages.error(request, 'Could not link your Google account. Please try again.')
        return redirect('player_auth:login')

    return _complete_login(request, pfc_user)


def email_login(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').lower().strip()
        if not email or '@' not in email:
            messages.error(request, 'Please enter a valid email address.')
            return render(request, 'player_auth/email_step1.html')
        otp = EmailOTP.create_for_email(email)
        _send_otp_email(email, otp.code)
        request.session[_KEY_PAUTH_PENDING_EMAIL] = email
        messages.success(request, f'A 6-digit code has been sent to {email}')
        return redirect('player_auth:email_verify')
    return render(request, 'player_auth/email_step1.html')


def email_verify(request):
    email = request.session.get(_KEY_PAUTH_PENDING_EMAIL)
    if not email:
        messages.error(request, 'Session expired. Please start again.')
        return redirect('player_auth:email_login')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        otp = EmailOTP.objects.filter(
            email=email, code=code, used=False,
        ).order_by('-created_at').first()

        if not otp or not otp.is_valid():
            messages.error(request, 'Invalid or expired code. Please try again.')
            return render(request, 'player_auth/email_step2.html', {'email': email})

        otp.consume()
        request.session.pop(_KEY_PAUTH_PENDING_EMAIL, None)

        pfc_user = PFCUser.objects.filter(email=email).first()
        if not pfc_user:
            pfc_user = PFCUser.objects.create(
                email=email,
                provider=PFCUser.PROVIDER_EMAIL,
            )

        return _complete_login(request, pfc_user)

    return render(request, 'player_auth/email_step2.html', {'email': email})


def _send_otp_email(email, code):
    try:
        send_mail(
            subject='Your PFC Login Code',
            message=(
                f'Your PFC login code is: {code}\n\n'
                f'This code expires in 10 minutes.\n\n'
                f'If you did not request this, please ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {e}")


def link_player(request):
    """Compatibility route: never expose the retired legacy-link interface."""
    pfc_user = _get_pending_user(request)
    if not pfc_user:
        return redirect('player_auth:login')
    return _complete_login(request, pfc_user)


def link_skip(request):
    """Backward-compatible alias for stale links/bookmarks."""
    pfc_user = _get_pending_user(request)
    if not pfc_user:
        return redirect('player_auth:login')
    return _complete_login(request, pfc_user)


def logout(request):
    CodenameSessionManager.logout_player(request)
    request.session.pop(_KEY_PAUTH_USER_ID, None)
    request.session.pop(_KEY_PAUTH_PENDING_EMAIL, None)
    request.session.pop(_KEY_PAUTH_STATE, None)
    request.session.pop(_KEY_PAUTH_VERIFIER, None)
    request.session.pop(_KEY_PAUTH_STARTED, None)
    messages.info(request, 'You have been logged out.')
    return redirect('player_auth:login')
