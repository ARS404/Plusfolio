from pathlib import Path
import os, secrets

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(os.environ.get('PLUSFOLIO_LOCAL_DIR',BASE_DIR / '.local'))
LOCAL_DIR.mkdir(exist_ok=True)
DEMO = os.environ.get('PLUSFOLIO_DEMO', '1') == '1'
def secret(name,default=''):
    path=os.environ.get(name+'_FILE')
    return Path(path).read_text().strip() if path else os.environ.get(name,default)

keyfile = LOCAL_DIR / 'app.key'
if DEMO and not keyfile.exists():
    keyfile.write_text(secrets.token_urlsafe(48))
    keyfile.chmod(0o600)
SECRET_KEY = secret('DJANGO_SECRET_KEY') or (keyfile.read_text().strip() if DEMO else '')
if not SECRET_KEY:
    raise RuntimeError('DJANGO_SECRET_KEY is required')
DEBUG = DEMO
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver'] if DEMO else os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
INSTALLED_APPS = ['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.staticfiles','rest_framework','core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','core.proxy.ClientIPMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware','core.api.PrivateCacheMiddleware']
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
AUTH_USER_MODEL = 'core.User'
DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':LOCAL_DIR/'demo.sqlite3','OPTIONS':{'timeout':20}}}
if os.environ.get('POSTGRES_HOST'):
    DATABASES = {'default': {'ENGINE':'django.db.backends.postgresql','HOST':os.environ['POSTGRES_HOST'],'NAME':os.environ.get('POSTGRES_DB','plusfolio'),'USER':os.environ.get('POSTGRES_USER','plusfolio'),'PASSWORD':secret('POSTGRES_PASSWORD'),'PORT':os.environ.get('POSTGRES_PORT','5432'),'DISABLE_SERVER_SIDE_CURSORS':os.environ.get('POSTGRES_DISABLE_SERVER_SIDE_CURSORS','0')=='1'}}
if not DEMO and DATABASES['default']['ENGINE'].endswith('sqlite3'):
    raise RuntimeError('Production requires PostgreSQL')
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator','OPTIONS':{'min_length':12}},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'}]
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES':['rest_framework.authentication.SessionAuthentication'],'DEFAULT_PERMISSION_CLASSES':['rest_framework.permissions.IsAuthenticated'],'EXCEPTION_HANDLER':'core.api.exception_handler'}
LANGUAGE_CODE='ru-ru'
TIME_ZONE='Europe/Moscow'
USE_TZ=True
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
STATIC_URL='/assets/'
STATICFILES_DIRS=[BASE_DIR/'frontend'/'dist'/'assets']
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE='Lax'
SESSION_COOKIE_SECURE=not DEMO
CSRF_COOKIE_SECURE=not DEMO
X_FRAME_OPTIONS='DENY'
SECURE_CONTENT_TYPE_NOSNIFF=True
EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend' if DEMO else 'django.core.mail.backends.smtp.EmailBackend'

TEX_COMPILER=os.environ.get('PLUSFOLIO_TEX_COMPILER',str(LOCAL_DIR/'tools'/'tectonic'))

# Private local CPU service; no third-party inference calls from web requests.
EMBEDDING_URL=os.environ.get('PLUSFOLIO_EMBEDDING_URL','http://127.0.0.1:8011')

# Server deployment: the proxy is the only public ingress; no direct web port.
PUBLIC_URL=os.environ.get('PLUSFOLIO_PUBLIC_URL','http://127.0.0.1:8000').rstrip('/')
CSRF_TRUSTED_ORIGINS=[PUBLIC_URL] if not DEMO else []
if not DEMO:
    if not PUBLIC_URL.startswith('https://'):raise RuntimeError('Production requires HTTPS PUBLIC_URL')
    if not all(ALLOWED_HOSTS):raise RuntimeError('DJANGO_ALLOWED_HOSTS is required')
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')
    SECURE_SSL_REDIRECT=True
    SECURE_REDIRECT_EXEMPT=[r'^healthz$']
    SECURE_HSTS_SECONDS=31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS=False
    SECURE_HSTS_PRELOAD=False
    # Domain-wide HSTS/preload are separate owner opt-ins; all other deploy checks remain fatal.
    SILENCED_SYSTEM_CHECKS=['security.W005','security.W021']
if os.environ.get('REDIS_URL'):
    CACHES={'default':{'BACKEND':'django.core.cache.backends.redis.RedisCache','LOCATION':os.environ['REDIS_URL']}}
EMAIL_HOST=os.environ.get('SMTP_HOST','')
EMAIL_PORT=int(os.environ.get('SMTP_PORT','587'))
EMAIL_HOST_USER=os.environ.get('SMTP_USER','')
EMAIL_HOST_PASSWORD=secret('SMTP_PASSWORD')
EMAIL_USE_TLS=os.environ.get('SMTP_TLS','1')=='1'
EMAIL_USE_SSL=os.environ.get('SMTP_SSL','0')=='1'
EMAIL_TIMEOUT=20
DEFAULT_FROM_EMAIL=os.environ.get('SMTP_FROM','')
TEX_SOCKET=os.environ.get('PLUSFOLIO_TEX_SOCKET','')

TRUST_PROXY_CLIENT_IP=os.environ.get('PLUSFOLIO_TRUST_PROXY_CLIENT_IP','0')=='1'
