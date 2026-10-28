from django.conf import settings
from django.http import FileResponse,HttpResponse
from django.urls import path,re_path,include
from core import api,tex_api
from core.search_api import problem_search
from core.catalogue_search_api import catalogue_search

def frontend(request,path=''):
    root=(settings.BASE_DIR/'frontend'/'dist').resolve()
    target=(root/path).resolve()
    if not target.is_relative_to(root):return HttpResponse(status=404)
    if not target.is_file():target=root/'index.html'
    if not target.exists():return HttpResponse('Сначала выполните npm run build в frontend.',status=503)
    import mimetypes
    return FileResponse(target.open('rb'),content_type=mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

from core.health import ready

urlpatterns=[
    path('healthz',ready),
    path('api/tex/toolchain',tex_api.toolchain),
    path('api/tex/toolchain/archive',tex_api.archive),
    path('api/problem-search',problem_search),
    path('api/catalogue-search',catalogue_search),
    path('api/v1/',include('core.api_v1')),
    path('api/documentation',api.documentation),
    path('api/documentation/<slug:section_id>',api.documentation),
    path('api/session',api.session),path('api/login',api.auth_login),path('api/logout',api.auth_logout),
    path('api/account',api.account),path('api/account/password',api.account_password),
    path('api/my-materials/<str:kind>',api.my_materials),path('api/my-problems/<uuid:pk>',api.my_problem),
    path('api/my-issues/<int:issue_id>',api.my_issue_detail),path('api/my-issues/<int:issue_id>/<str:file_kind>',api.my_issue_document),
    path('api/materials/<str:kind>/<uuid:pk>/<str:file_kind>',api.material_document),
    path('api/worksheet-documents/<uuid:pk>',api.worksheet_document),
    path('api/worksheet-documents/<uuid:pk>/publish',api.worksheet_publish),
    path('api/worksheets/<uuid:pk>/copy',api.worksheet_copy),
    path('api/circles/<uuid:pk>/issues/<int:issue_id>',api.issue_detail),
    path('api/circles/<uuid:pk>/issues/<int:issue_id>/<str:file_kind>',api.issue_document),
    path('api/circles',api.circles),path('api/circles/<uuid:pk>',api.circle_detail),
    path('api/circles/<uuid:pk>/members',api.members),path('api/circles/<uuid:pk>/members/<int:student_id>',api.student_detail),path('api/circles/<uuid:pk>/teachers',api.teachers),
    path('api/circles/<uuid:pk>/student-search',api.student_search),
    path('api/circles/<uuid:pk>/issues',api.issues),
    path('api/circles/<uuid:pk>/journal',api.journal),path('api/circles/<uuid:pk>/journal/export',api.journal_export),path('api/circles/<uuid:pk>/journal/<int:issue_id>',api.journal),
    path('api/circles/<uuid:pk>/problems/<uuid:problem_id>/<str:kind>',api.mark),
    path('api/circles/<uuid:pk>/audit',api.audit),path('api/materials/<str:kind>',api.materials),
    path('api/materials/<str:kind>/<uuid:pk>',api.material_detail),path('api/topics',api.topics),path('api/topics/<uuid:pk>',api.topic_detail),
    path('api/tags',api.tags),path('api/analytics',api.analytics),path('api/invitations',api.invitations),
    path('api/invitations/<uuid:pk>',api.invitation_detail),path('api/accept/<str:token>',api.invitation_accept),
    path('api/mailbox',api.mailbox),path('api/users',api.users),
    re_path(r'^(?!api/)(?P<path>.*)$',frontend),
]
