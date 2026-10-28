import os
from .release import release_info
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

@require_GET
def ready(request):
    checks={}
    try:
        with connection.cursor() as cursor:cursor.execute('SELECT 1');cursor.fetchone()
        checks['database']=True
    except Exception:checks['database']=False
    checks['frontend']=(settings.BASE_DIR/'frontend/dist/index.html').is_file()
    if not settings.DEMO:
        from .tex_remote import request as tex_request
        from urllib.request import build_opener,ProxyHandler
        try:checks['tex']=tex_request(settings.TEX_SOCKET,{'health':True}).get('ok') is True
        except Exception:checks['tex']=False
        try:
            with build_opener(ProxyHandler({})).open(settings.EMBEDDING_URL+'/health',timeout=2) as response:checks['search']=response.status==200
        except Exception:checks['search']=False
        checks['mail_configuration']=bool(settings.EMAIL_HOST and settings.DEFAULT_FROM_EMAIL)
    return JsonResponse({'ok':all(checks.values()),'checks':checks,'release':release_info(),'instance':os.environ.get('PLUSFOLIO_INSTANCE_ID','demo')},status=200 if all(checks.values()) else 503)
