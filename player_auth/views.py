"""
player_auth/views.py — Google OAuth + Email OTP auth views
"""

import json
import urllib.parse
import urllib.request
import secrets
import logging

from django.conf import settings
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

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v3/userinfo'


def _complete_login(request, pfc_user):
    pfc_user.record_login()
    if not pfc_user.player:
        request.session[_KEY_PAUTH_USER_ID] = pfc_user.id
        return redirect('player_auth:link')
    codename = pfc_user.codename
    if codename:
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


def login_page(request):
    if CodenameSessionManager.is_logged_in(request):
        return redirect('/')
    google_configured = bool(settings.GOOGLE_OAUTH_CLIENT_ID)
    return render(request, 'player_auth/login.html', {
        'google_configured': google_configured,
        'next': request.GET.get('next', '/'),
    })


def google_login(request):
    state = secrets.token_urlsafe(32)
    request.session[_KEY_PAUTH_STATE] = state
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'access_type': 'offline',
        'prompt': 'select_account',
    }
    url = GOOGLE_AUTH_URL + '?' + urllib.parse.urlencode(params)
    return redirect(url)


def google_callback(request):
    state = request.GET.get('state')
    if state != request.session.get(_KEY_PAUTH_STATE):
        messages.error(request, 'Authentication failed: invalid state. Please try again.')
        return redirect('player_auth:login')

    code = request.GET.get('code')
    if not code:
        error = request.GET.get('error', 'Unknown error')
        messages.error(request, f'Google login failed: {error}')
        return redirect('player_auth:login')

    token_data = {
        'code': code,
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
        'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
        'grant_type': 'authorization_code',
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
        logger.error(f"Google token exchange failed: {e}")
        messages.error(request, 'Google login failed. Please try again.')
        return redirect('player_auth:login')

    access_token = tokens.get('access_token')
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
        logger.error(f"Google userinfo fetch failed: {e}")
        messages.error(request, 'Could not retrieve your Google profile. Please try again.')
        return redirect('player_auth:login')

    email = user_info.get('email', '').lower().strip()
    google_sub = user_info.get('sub', '')
    display_name = user_info.get('name', '')
    avatar_url = user_info.get('picture', '')

    if not email:
        messages.error(request, 'Google did not provide an email address.')
        return redirect('player_auth:login')

    pfc_user = None
    if google_sub:
        pfc_user = PFCUser.objects.filter(google_sub=google_sub).first()
    if not pfc_user:
        pfc_user = PFCUser.objects.filter(email=email).first()
        if pfc_user and google_sub and not pfc_user.google_sub:
            pfc_user.google_sub = google_sub
            pfc_user.save(update_fields=['google_sub'])
    if not pfc_user:
        pfc_user = PFCUser.objects.create(
            email=email,
            provider=PFCUser.PROVIDER_GOOGLE,
            google_sub=google_sub,
            display_name=display_name,
            avatar_url=avatar_url,
        )
    else:
        pfc_user.display_name = display_name or pfc_user.display_name
        pfc_user.avatar_url = avatar_url or pfc_user.avatar_url
        pfc_user.save(update_fields=['display_name', 'avatar_url'])

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
    pfc_user = _get_pending_user(request)
    if not pfc_user:
        return redirect('player_auth:login')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'link':
            codename = request.POST.get('codename', '').strip().upper()
            if not codename:
                messages.error(request, 'Please enter your codename.')
                return render(request, 'player_auth/link.html', {'pfc_user': pfc_user})
            player, error = pfc_user.link_legacy_player(codename)
            if error:
                messages.error(request, error)
                return render(request, 'player_auth/link.html', {'pfc_user': pfc_user})
            return render(request, 'player_auth/link_confirm.html', {
                'pfc_user': pfc_user,
                'player': player,
                'codename': codename,
            })

        elif action == 'confirm':
            codename = pfc_user.codename
            if codename:
                CodenameSessionManager.login_player(request, codename)
            request.session.pop(_KEY_PAUTH_USER_ID, None)
            messages.success(request, f'Welcome back, {pfc_user.player.name}!')
            return redirect('/')

        elif action == 'skip':
            return redirect('player_auth:link_skip')

    return render(request, 'player_auth/link.html', {'pfc_user': pfc_user})


def link_skip(request):
    pfc_user = _get_pending_user(request)
    if not pfc_user:
        return redirect('player_auth:login')

    pfc_user.legacy_link_skipped = True
    pfc_user.save(update_fields=['legacy_link_skipped'])
    pfc_user.create_and_link_player()

    codename = pfc_user.codename
    if codename:
        CodenameSessionManager.login_player(request, codename)

    request.session.pop(_KEY_PAUTH_USER_ID, None)
    messages.success(request, f'Welcome to PFC, {pfc_user.player.name}!')
    return redirect('/')


def logout(request):
    CodenameSessionManager.logout_player(request)
    request.session.pop(_KEY_PAUTH_USER_ID, None)
    request.session.pop(_KEY_PAUTH_PENDING_EMAIL, None)
    request.session.pop(_KEY_PAUTH_STATE, None)
    messages.info(request, 'You have been logged out.')
    return redirect('player_auth:login')
