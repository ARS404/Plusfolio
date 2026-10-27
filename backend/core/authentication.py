"""Revocable, expiring bearer credentials for the versioned API only."""
import hashlib
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, Throttled, ValidationError

from .models import ApiToken, User


def password_stamp(user):
    return salted_hmac('plusfolio.api.password', user.password, algorithm='sha256').hexdigest()


def throttle_credentials(request, login):
    """Bound password work by both caller address and account, without storing the login."""
    for label, value, limit in [('ip', request.META.get('REMOTE_ADDR', ''), 40), ('login', login, 15)]:
        key = 'api-credentials:' + label + ':' + hashlib.sha256(value.encode()).hexdigest()
        if cache.add(key, 1, timeout=300):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=300)
                count = 1
        if count > limit:
            raise Throttled(wait=300, detail='Слишком много попыток. Повторите через 5 минут.')


@transaction.atomic
@sensitive_variables('secret', 'data')
def create_token(user, data):
    if not isinstance(data, dict):
        raise ValidationError('Передайте JSON-объект.')
    name = data.get('name', 'Автоматизация')
    days = data.get('expires_in_days', 30)
    read_only = data.get('read_only', False)
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValidationError('Название токена — от 1 до 100 символов.')
    if type(days) is not int or not 1 <= days <= 90:
        raise ValidationError('Срок токена — целое число от 1 до 90 дней.')
    if type(read_only) is not bool:
        raise ValidationError('read_only должен быть true или false.')
    # Serialise creation per account, including concurrent clients.
    verified_stamp = password_stamp(user)
    user = User.objects.select_for_update().get(pk=user.pk)
    if not user.is_active:
        raise AuthenticationFailed('Аккаунт недоступен.')
    if not constant_time_compare(verified_stamp, password_stamp(user)):
        raise AuthenticationFailed('Пароль изменился. Повторите вход.')
    if ApiToken.objects.filter(user=user, revoked_at=None, expires_at__gt=timezone.now(), password_stamp=password_stamp(user)).count() >= 20:
        raise ValidationError('У аккаунта уже 20 действующих токенов. Отзовите ненужные.')
    secret = 'pf_' + secrets.token_urlsafe(32)
    token = ApiToken.objects.create(user=user, name=name.strip(), prefix=secret[:11],
        digest=hashlib.sha256(secret.encode()).hexdigest(), password_stamp=password_stamp(user),
        read_only=read_only, expires_at=timezone.now() + timedelta(days=days))
    from .services import audit
    audit(user, 'api_token.create', {'id': str(token.pk), 'name': token.name, 'read_only': read_only})
    return token, secret


def token_data(token):
    return {'id': str(token.pk), 'name': token.name, 'prefix': token.prefix + '…',
            'read_only': token.read_only, 'created_at': token.created_at.isoformat(),
            'expires_at': token.expires_at.isoformat(),
            'last_used_at': token.last_used_at.isoformat() if token.last_used_at else None,
            'revoked_at': token.revoked_at.isoformat() if token.revoked_at else None,
            'active': token.revoked_at is None and token.expires_at > timezone.now()
                      and constant_time_compare(token.password_stamp, password_stamp(token.user))}


class BearerAuthentication(BaseAuthentication):
    def authenticate_header(self, request):
        return 'Bearer realm="Plusfolio API"'

    def authenticate(self, request):
        header = get_authorization_header(request)
        if not header:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != b'bearer' or len(parts[1]) > 200:
            raise AuthenticationFailed('Используйте заголовок Authorization: Bearer <token>.')
        digest = hashlib.sha256(parts[1]).hexdigest()
        token = ApiToken.objects.select_related('user').filter(digest=digest, revoked_at=None, expires_at__gt=timezone.now()).first()
        if token is None or not token.user.is_active or not constant_time_compare(token.password_stamp, password_stamp(token.user)):
            raise AuthenticationFailed('Токен недействителен, истёк или отозван.')
        self_revoke = request.method == 'DELETE' and request.path == '/api/v1/auth/tokens/current'
        search_read = request.method == 'POST' and request.path == '/api/v1/problem-search'
        if token.read_only and not search_read and request.method not in {'GET', 'HEAD', 'OPTIONS'} and not self_revoke:
            raise PermissionDenied('Этот токен разрешает только чтение.')
        now = timezone.now()
        if token.last_used_at is None or token.last_used_at < now - timedelta(minutes=5):
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
        return token.user, token
