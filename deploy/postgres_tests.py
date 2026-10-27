"""Native PostgreSQL regression tests, isolated in a precreated disposable database."""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.core.management import call_command
settings.DEMO=True
settings.DEBUG=True
settings.SECURE_SSL_REDIRECT=False
settings.ALLOWED_HOSTS=['testserver','localhost','127.0.0.1']
settings.TRUST_PROXY_CLIENT_IP=False
# Tests provide their own SMTP mock. Nothing is sent to external addresses.
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
call_command('test','core.test_worksheets','core.test_search','core.test_catalogue_search','core.test_api_v1','core.test_server',
             interactive=False,keepdb=True)
