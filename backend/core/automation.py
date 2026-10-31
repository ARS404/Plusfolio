"""API credential lifecycle. Domain operations remain in the existing services."""
from django.contrib.auth import authenticate
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .authentication import create_token, throttle_credentials, token_data
from .models import ApiToken
from . import services as s


@sensitive_variables('password', 'data')
def verified_credentials(request, *, own=False):
    data = request.data
    if not isinstance(data, dict):
        raise ValidationError('Передайте JSON-объект с логином и паролем.')
    login = request.user.email if own else data.get('login', data.get('email', ''))
    password = data.get('password', '')
    if not isinstance(login, str) or not isinstance(password, str) or len(login) > 254 or len(password) > 1024:
        raise ValidationError('Некорректный логин или пароль.')
    login = login.strip().lower()
    throttle_credentials(request, login)
    return authenticate(request=request._request, email=login, password=password)


@sensitive_variables('secret', 'data')
def issue_result(user, data):
    token, secret = create_token(user, data)
    from .api import user_data
    return Response({'access_token': secret, 'token_type': 'Bearer', 'token': token_data(token),
                     'user': user_data(user)}, status=201)


@sensitive_post_parameters('password')
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def token_issue(request):
    user = verified_credentials(request)
    if user is None:
        return Response({'detail': 'Неверный логин или пароль.'}, status=401,
                        headers={'WWW-Authenticate': 'Bearer realm="Plusfolio API"'})
    return issue_result(user, request.data)


@sensitive_post_parameters('password')
@api_view(['GET', 'POST'])
def tokens(request):
    if request.method == 'POST':
        user = verified_credentials(request, own=True)
        if user is None:
            return Response({'detail': 'Текущий пароль неверен.'}, status=400)
        return issue_result(user, request.data)
    return Response([token_data(token) for token in ApiToken.objects.filter(user=request.user).select_related('user').order_by('-created_at')[:100]])


@api_view(['DELETE'])
def token_revoke(request, pk=None):
    token = (request.auth if isinstance(request.auth, ApiToken) else None) if pk is None else ApiToken.objects.filter(pk=pk, user=request.user).first()
    if token is None:
        raise NotFound('Токен недоступен.')
    ApiToken.objects.filter(pk=token.pk, user=request.user, revoked_at=None).update(revoked_at=timezone.now())
    s.audit(request.user, 'api_token.revoke', {'id': str(token.pk)})
    return Response({'ok': True})


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def invitation_accept(request, token):
    invitation = s.valid_invitation(token)
    from .models import User
    from .api import user_data
    if invitation.role == 'student' and not request.user.is_authenticated:
        raise PermissionDenied('Приглашение школьника нужно принять на сайте.')
    if request.method == 'GET':
        recipient = User.objects.filter(email=invitation.email).first()
        return Response({'email': invitation.email, 'role': invitation.role,
                         'circle': invitation.circle.name if invitation.circle else None,
                         'registered': recipient is not None,
                         'student_profile_required': invitation.role == 'student' and (recipient is None or 'student' not in recipient.roles)})
    user = s.accept_invitation(token, request.data, request.user if request.user.is_authenticated else None)
    # API acceptance deliberately creates no browser session and no API token.
    return Response({'user': user_data(user), 'accepted': True})
