from pathlib import Path
import os, secrets

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_DIR = BASE_DIR / '.local'
LOCAL_DIR.mkdir(exist_ok=True)
DEMO = os.environ.get('PLUSFOLIO_DEMO', '1') == '1'
keyfile = LOCAL_DIR / 'app.key'
if DEMO and not keyfile.exists():
    keyfile.write_text(secrets.token_urlsafe(48))
    keyfile.chmod(0o600)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or (keyfile.read_text().strip() if DEMO else '')
if not SECRET_KEY:
    raise RuntimeError('DJANGO_SECRET_KEY is required')
DEBUG = DEMO
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver'] if DEMO else os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')
INSTALLED_APPS = ['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.staticfiles','rest_framework','core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware','core.api.PrivateCacheMiddleware']
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
AUTH_USER_MODEL = 'core.User'
DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':LOCAL_DIR/'demo.sqlite3','OPTIONS':{'timeout':20}}}
if os.environ.get('POSTGRES_HOST'):
    DATABASES = {'default': {'ENGINE':'django.db.backends.postgresql','HOST':os.environ['POSTGRES_HOST'],'NAME':os.environ.get('POSTGRES_DB','plusfolio'),'USER':os.environ.get('POSTGRES_USER','plusfolio'),'PASSWORD':os.environ.get('POSTGRES_PASSWORD',''),'PORT':os.environ.get('POSTGRES_PORT','5432')}}
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
