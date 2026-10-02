# quiz/middleware.py
"""
يحوّل توكن Supabase (Authorization: Bearer ...) إلى مستخدم Django،
فيشتغل request.user في submit_score وباقي الـ views.

التحقق بيتم عن طريق Supabase نفسه (/auth/v1/user)، فيشتغل مع أي نوع توقيع JWT.
"""
import hashlib
import logging

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60


def _verify_token(token):
    """يرجع dict ببيانات مستخدم Supabase أو None."""
    cache_key = 'sb_tok_' + hashlib.sha256(token.encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        resp = requests.get(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user",
            headers={
                'apikey': settings.SUPABASE_ANON_KEY,
                'Authorization': f'Bearer {token}',
            },
            timeout=5,
        )
    except requests.RequestException as exc:
        logger.warning('Supabase auth request failed: %s', exc)
        return None

    if resp.status_code != 200:
        # لو ظهر هنا 402 يبقى المشكلة في حساب/مشروع Supabase نفسه
        logger.warning('Supabase auth returned %s: %s', resp.status_code, resp.text[:200])
        return None

    data = resp.json()
    cache.set(cache_key, data, CACHE_SECONDS)
    return data


def _get_or_create_django_user(sb_user):
    email = (sb_user.get('email') or '').strip().lower()
    meta = sb_user.get('user_metadata') or {}
    full_name = (meta.get('full_name') or meta.get('name') or '').strip()

    # لو فيه مستخدم قديم بنفس الإيميل نستخدمه بدل ما نكرر
    if email:
        user = User.objects.filter(email__iexact=email).first()
        if user:
            return user

    username = (email or sb_user['id'])[:150]
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': email,
            'first_name': full_name[:150],
        },
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=['password'])
    return user


class SupabaseBearerAuthMiddleware:
    """ضعيه بعد AuthenticationMiddleware في settings.MIDDLEWARE"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            auth = request.headers.get('Authorization', '')
            if auth.lower().startswith('bearer '):
                token = auth[7:].strip()
                sb_user = _verify_token(token) if token else None
                if sb_user and sb_user.get('id'):
                    request.user = _get_or_create_django_user(sb_user)
        return self.get_response(request)