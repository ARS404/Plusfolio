import json
from datetime import date
from django.conf import settings
from django.contrib.auth import authenticate,login,logout
from django.core.exceptions import ValidationError as DjangoValidationError,ObjectDoesNotExist
from django.db import IntegrityError,transaction
from django.db.models import Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect,ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception
from .models import (
    AnalystGrant, AuditEvent, Circle, CircleTeacher, EmailOutbox, Enrollment,
    Invitation, Problem, ROLES, Solve, Student, Tag, Topic, TopicCatalogVersion,
    User, WorksheetIssue,
)
from . import services as s
from . import filters as f
from . import queries as read
from .identifiers import public_id, search_entities

def exception_handler(exc,context):
    if isinstance(exc,s.Conflict): return Response({'detail':str(exc)},status=409)
    if isinstance(exc,DjangoValidationError):return Response({'detail':' '.join(exc.messages)},status=400)
    if isinstance(exc,(ValueError,TypeError)):return Response({'detail':'Некорректные параметры запроса.'},status=400)
    if isinstance(exc,IntegrityError):return Response({'detail':'Запись уже существует или была изменена. Обновите данные.'},status=409)
    if isinstance(exc,ObjectDoesNotExist):return Response({'detail':'Запись не найдена.'},status=404)
    return drf_exception(exc,context)

class PrivateCacheMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        if request.path.startswith('/api/'):
            response['Cache-Control']='no-store';response['Referrer-Policy']='no-referrer'
        return response

def user_data(user):
    if not user.is_authenticated:return None
    from .people import student_profile_complete
    return {'id':user.pk,'public_id':public_id('user',user.pk),'student_public_id':public_id('student',user.student.pk) if hasattr(user,'student') else None,'teacher_public_id':public_id('teacher',user.teacher.pk) if hasattr(user,'teacher') else None,'name':user.name,'email':user.email,'roles':user.roles,'is_active':user.is_active,'student_id':user.student.pk if hasattr(user,'student') else None,**({**user.student.education_info(),'no_patronymic':user.student.no_patronymic,'profile_complete':student_profile_complete(user.student)} if hasattr(user,'student') else {})}

@ensure_csrf_cookie
@require_http_methods(['GET'])
def session(request):
    return JsonResponse({'user':user_data(request.user),'demo':settings.DEMO,'csrf':get_token(request)})

@api_view(['GET','PATCH'])
def account(request):
    from .account import overview, update_name
    if request.method=='PATCH':update_name(request.user,request.data)
    return Response({'user':user_data(request.user),**overview(request.user)})

@api_view(['POST'])
def account_password(request):
    from .account import change_password
    change_password(request,request.data)
    return Response({'ok':True})

@csrf_protect
@require_http_methods(['POST'])
def auth_login(request):
    from django.core.cache import cache
    key='login:'+request.META.get('REMOTE_ADDR','unknown')
    if cache.add(key,1,300):attempts=1
    else:
        try:attempts=cache.incr(key)
        except ValueError:cache.set(key,1,300);attempts=1
    if attempts>40:return JsonResponse({'detail':'Слишком много попыток. Повторите позже.'},status=429)
    try:data=json.loads(request.body)
    except (ValueError,UnicodeError):return JsonResponse({'detail':'Некорректный запрос.'},status=400)
    user=authenticate(request,email=str(data.get('email','')).strip().lower(),password=data.get('password',''))
    if not user:return JsonResponse({'detail':'Неверный email или пароль.'},status=400)
    login(request,user);return JsonResponse({'user':user_data(user),'csrf':get_token(request)})

@api_view(['POST'])
def auth_logout(request):logout(request);return Response({'ok':True})

def circle_data(circle,user):
    batched=hasattr(circle,'_current_teachers')
    analyse=(s.admin(user) or circle._teaches or circle._analyses) if batched else s.can_analyse_group(user,circle)
    write=(not circle.archived and (s.admin(user) or circle._teaches)) if batched else s.can_write(user,circle)
    teachers=circle._current_teachers if batched else circle.teaching.filter(ended_at=None).select_related('teacher__user')
    return {'id':str(circle.pk),'public_id':public_id('circle',circle.number_id),'name':circle.name,'description':circle.description,'city':circle.city,'region':circle.region,'archived':circle.archived,'tags':[{'id':tag.pk,'public_id':public_id('tag',tag.pk),'name':tag.name} for tag in circle.tags.all()],'teachers':[{'id':t.teacher.user_id,'public_id':public_id('teacher',t.teacher_id),'user_public_id':public_id('user',t.teacher.user_id),'name':t.teacher.user.name,'email':t.teacher.user.email if analyse else None} for t in teachers],'student_count':circle._student_count if batched else circle.enrollments.filter(left_at=None).count(),'worksheet_count':circle._worksheet_count if batched else circle.issues.count(),'can_write':write,'can_analyse_group':analyse,'can_manage_teachers':s.admin(user)}

@api_view(['GET','POST'])
def circles(request):
    if request.method=='POST':
        s.require(s.admin(request.user))
        d=request.data;name=str(d.get('name','')).strip()
        if not name:raise DjangoValidationError('Укажите название кружка.')
        tags=Tag.objects.filter(pk__in=d.get('tags',[]),kind='circle',archived=False)
        if tags.count()!=len(set(d.get('tags',[]))):raise DjangoValidationError('Недопустимые теги кружка.')
        with transaction.atomic():
            circle=Circle.objects.create(name=name,description=d.get('description',''),city=d.get('city',''),region=d.get('region',''),created_by=request.user)
            circle.tags.set(tags);s.audit(request.user,'circle.create',{'circle':str(circle.pk)},circle)
        return Response(circle_data(circle,request.user),status=201)
    return Response([circle_data(c,request.user) for c in read.circle_rows(search_entities(f.by_city(s.circles_for(request.user),f.query_values(request.query_params,'city')),request.query_params.get('q',''),'circle',text_fields=('name','city','region')),request.user)])

@api_view(['GET','PATCH'])
def circle_detail(request,pk):
    circle=s.get_circle(request.user,pk,write=request.method=='PATCH')
    if request.method=='PATCH':
        for field in ['name','description','city','region']:
            if field in request.data:setattr(circle,field,str(request.data[field]))
        if not circle.name.strip():raise DjangoValidationError('Укажите название.')
        if 'tags' in request.data:
            s.require(s.admin(request.user));tags=Tag.objects.filter(kind='circle',pk__in=request.data['tags'],archived=False)
            if tags.count()!=len(set(request.data['tags'])):raise DjangoValidationError('Недопустимые теги.')
            circle.tags.set(tags)
        circle.save();s.audit(request.user,'circle.update',{},circle)
    return Response(circle_data(circle,request.user))

@api_view(['GET','POST','DELETE'])
def members(request,pk):
    circle=s.get_circle(request.user,pk)
    if request.method=='POST':
        if request.data.get('student_id') is not None and request.data.get('email'):raise DjangoValidationError('Выберите школьника или укажите email.')
        s.enroll(request.user,circle,str(request.data.get('email','')),request.data.get('student_id'))
    if request.method=='DELETE':s.unenroll(request.user,circle,str(request.data.get('email','')))
    can_write=s.can_write(request.user,circle)
    return Response([{'id':m.student_id,'public_id':public_id('student',m.student_id),'user_public_id':public_id('user',m.student.user_id),'name':m.student.user.name,**m.student.education_info(),**({'email':m.student.user.email} if can_write else {})} for m in circle.enrollments.filter(left_at=None).select_related('student__user').order_by('student__user__name')])

@api_view(['GET'])
def student_search(request,pk):
    from django.db.models import Exists,OuterRef
    from .people import normalize_name,role_query,search_people,masked_email
    circle=s.get_circle(request.user,pk,write=True)
    text=request.query_params.get('q','')
    if not normalize_name(text):return Response([])
    qs=Student.objects.filter(user__is_active=True).filter(role_query(['student'],'user__')).select_related('user')
    qs=search_people(qs,text,'user__',email=False).annotate(already_enrolled=Exists(Enrollment.objects.filter(student_id=OuterRef('pk'),circle=circle,left_at=None)))
    return Response([{'id':student.pk,'public_id':public_id('student',student.pk),'user_public_id':public_id('user',student.user_id),'name':student.user.name,**student.education_info(),'email_hint':masked_email(student.user.email),'already_enrolled':student.already_enrolled} for student in qs.order_by('already_enrolled','user__name_search','pk')[:20]])

@api_view(['PATCH'])
def student_detail(request,pk,student_id):
    circle=s.get_circle(request.user,pk,write=True)
    student=s.update_student(request.user,circle,student_id,request.data)
    return Response({'id':student.pk,'public_id':public_id('student',student.pk),**student.education_info()})

@api_view(['POST','DELETE'])
def teachers(request,pk):
    circle=s.get_circle(request.user,pk)
    s.assign_teacher(request.user,circle,str(request.data.get('email','')),request.method=='DELETE')
    return Response(circle_data(circle,request.user))

@api_view(['GET','POST'])
def issues(request,pk):
    circle=s.get_circle(request.user,pk)
    if request.method=='POST':
        ids=s.selection_ids(request.data,'worksheet_ids','worksheet_id')
        with transaction.atomic():
            for worksheet_id in ids:s.issue_worksheet(request.user,circle,worksheet_id,date.fromisoformat(request.data.get('issued_on','')))
    from .catalogue_search import search_issued
    selected=f.by_tags(circle.issues.all(),f.query_values(request.query_params,'tag'),'worksheet','worksheet__tags')
    selected=search_issued(selected,request.query_params.get('q',''),request.query_params.get('mode')=='hybrid')
    return Response([issue_data(i) for i in read.issue_rows(selected).order_by('-issued_on','-pk')])

def material_data(material,user,detail=False,circle=None,allowed_solutions=None):
    result={'id':str(material.pk),'title':material.title,'description':material.description,'topics':[str(t.pk) for t in material.topics.all()],'tags':[{'id':tag.pk,'public_id':public_id('tag',tag.pk),'name':tag.name} for tag in material.tags.all()],'author':material.author.name,'archived':material.archived}
    if isinstance(material,Problem):
        result.update(title=material.display_title,custom_title=material.title,number=material.number_id,public_id=public_id('problem',material.number_id),
            source=material.source,source_id=material.source_id,source_url=material.source_url,attribution=material.attribution)
        result['statement']=material.statement
        from .documents import references
        result.update(references('/api/materials/problem/'+str(material.pk),material.display_title))
        if circle:
            for key in ['pdf_url','tex_url','project_url']:result[key]+='?circle='+str(circle.pk)
        result['source_format']='tex' if material.statement_tex else 'plain';result['statement_tex']=material.statement_tex
        show_solution=material.pk in allowed_solutions if allowed_solutions is not None else s.solution_allowed(user,material,circle)
        if show_solution:
            result['solution']=material.solution;result['solution_tex']=material.solution_tex
            result['solution_kind']='answer' if material.source=='problems.ru' and not material.source_metadata.get('has_detailed_solution',False) else 'solution'
    else:
        from .documents import references
        from .worksheets import metadata
        result.update(metadata(material,user))
        result.update(references('/api/materials/worksheet/'+str(material.pk),material.title));result['template_version']=material.template_version
        problem_ids=material._problem_ids if hasattr(material,'_problem_ids') else list(material.items.values_list('problem_id',flat=True))
        result['problem_count']=len(problem_ids)
        result['problem_ids']=[str(pk) for pk in problem_ids]
        if detail:
            problems=[i.problem for i in material.items.select_related('problem__author').prefetch_related('problem__topics','problem__tags')]
            visible=s.visible_solution_ids(user,[p.pk for p in problems],circle) if allowed_solutions is None else allowed_solutions
            result['problems']=[material_data(p,user,circle=circle,allowed_solutions=visible) for p in problems]
            result['solutions_available']=bool(visible)
    return result

def issue_data(issue,personal=False):
    from .documents import issue_references
    return {'id':issue.pk,'public_id':public_id('worksheet',issue.worksheet.document.number_id),'issue_public_id':public_id('issue',issue.pk),'worksheet_id':str(issue.worksheet_id),'document_id':str(issue.worksheet.document_id),'revision':issue.worksheet.revision,'title':issue.worksheet.title,'description':issue.worksheet.description,
        'tags':[{'id':tag.pk,'public_id':public_id('tag',tag.pk),'name':tag.name} for tag in issue.worksheet.tags.all()],
        'circle_id':str(issue.circle_id),'circle_public_id':public_id('circle',issue.circle.number_id),'circle_name':issue.circle.name,'city':issue.circle.city,
        'number':issue.number,'issued_on':issue.issued_on.isoformat(),'problem_count':issue._problem_count if hasattr(issue,'_problem_count') else issue.worksheet.items.count(),
        **issue_references(issue,personal)}

@api_view(['GET'])
def my_materials(request,kind):
    s.require('student' in request.user.roles)
    if kind not in ['problem','worksheet']:raise DjangoValidationError('Неизвестный вид материала.')
    tags=f.query_values(request.query_params,'tag');text=request.query_params.get('q','').strip()
    if kind=='worksheet':
        qs=WorksheetIssue.objects.filter(assignments__student__user=request.user).distinct()
        qs=f.by_tags(qs,tags,'worksheet','worksheet__tags')
        if text:
            from .catalogue_search import search_issued
            qs=search_issued(qs,text,request.query_params.get('mode')=='hybrid')
        return Response([issue_data(issue,True) for issue in read.issue_rows(qs).order_by('-issued_on','-pk')[:300]])
    qs=f.by_tags(s.my_problems_for(request.user),tags,'problem')
    qs=s.search_problems(qs,text)
    problems=list(qs.select_related('author').prefetch_related('topics','tags').order_by('title')[:300])
    visible=s.visible_solution_ids(request.user,[p.pk for p in problems])
    solved=set(Solve.objects.filter(student__user=request.user,problem__in=problems,solved=True).values_list('problem_id',flat=True))
    return Response([{**material_data(p,request.user,allowed_solutions=visible),'solved':p.pk in solved} for p in problems])

@api_view(['GET'])
def my_problem(request,pk):
    problem=s.my_problems_for(request.user).filter(pk=pk).first()
    if not problem:raise s.NotFound('Задача не назначалась вам.')
    return Response(material_data(problem,request.user,True))

def personal_issue(user,pk):
    s.require('student' in user.roles)
    issue=WorksheetIssue.objects.filter(pk=pk,assignments__student__user=user).select_related('circle','worksheet').first()
    if not issue:raise s.NotFound('Листок не назначался вам.')
    return issue

@api_view(['GET'])
def issue_detail(request,pk,issue_id):
    circle=s.get_circle(request.user,pk);issue=circle.issues.select_related('worksheet','circle').get(pk=issue_id)
    return Response({**material_data(issue.worksheet,request.user,True,circle),**issue_data(issue)})

@api_view(['GET'])
def my_issue_detail(request,issue_id):
    issue=personal_issue(request.user,issue_id)
    return Response({**material_data(issue.worksheet,request.user,True),**issue_data(issue,True)})

def document_response(request,material,kind,issue=None,personal=False,circle=None):
    from .documents import project_for,response
    if kind in ['tex','project']:s.require(s.admin(request.user) or 'teacher' in request.user.roles,'Выгрузка исходников доступна преподавателю и администратору.')
    if isinstance(material,Problem):
        from types import SimpleNamespace
        problems=[material];worksheet=SimpleNamespace(title=material.display_title,description=material.description,is_problem=True)
    else:
        worksheet=material;problems=[item.problem for item in material.items.select_related('problem').all()]
    visible=s.visible_solution_ids(request.user,[p.pk for p in problems],None if personal else issue.circle if issue else circle)
    source=project_for(worksheet,problems,visible,request.query_params.get('solutions')=='1',issue)
    return response(source,kind,request.query_params.get('download')=='1')

@api_view(['GET'])
def material_document(request,kind,pk,file_kind):
    if kind not in ['problem','worksheet']:raise DjangoValidationError('Неизвестный вид материала.')
    qs=s.problems_for(request.user) if kind=='problem' else s.worksheets_for(request.user)
    if 'student' in request.user.roles:
        own=s.my_problems_for(request.user) if kind=='problem' else s.my_worksheets_for(request.user)
        qs=(qs|own).distinct()
    circle=s.get_circle(request.user,request.query_params['circle']) if request.query_params.get('circle') else None
    if circle:qs=qs.filter(items__worksheet__issues__circle=circle) if kind=='problem' else qs.filter(issues__circle=circle)
    material=qs.filter(pk=pk).first()
    if not material:raise s.NotFound('Материал недоступен.')
    return document_response(request,material,file_kind,circle=circle)

@api_view(['GET'])
def issue_document(request,pk,issue_id,file_kind):
    circle=s.get_circle(request.user,pk);issue=circle.issues.select_related('worksheet','circle').get(pk=issue_id)
    return document_response(request,issue.worksheet,file_kind,issue)

@api_view(['GET'])
def my_issue_document(request,issue_id,file_kind):
    issue=personal_issue(request.user,issue_id)
    return document_response(request,issue.worksheet,file_kind,issue,True)

@api_view(['GET','POST'])
def materials(request,kind):
    if kind not in ['problem','worksheet']:raise DjangoValidationError('Неизвестный вид материала.')
    if request.method=='POST':return Response(material_data(s.create_material(request.user,kind,request.data),request.user),status=201)
    from .worksheets import catalogue
    qs=s.problems_for(request.user) if kind=='problem' else catalogue(request.user,request.query_params.get('scope','available'))
    qs=f.by_tags(qs,f.query_values(request.query_params,'tag'),kind)
    ids=s.topic_ids_in_branch(f.query_values(request.query_params,'topic'))
    if ids is not None:qs=qs.filter(topics__pk__in=ids).distinct()
    text=request.query_params.get('q','').strip()
    if text:
        q=Q(title__icontains=text)|Q(description__icontains=text)
        qs=s.search_problems(qs,text) if kind=='problem' else search_entities(qs,text,'worksheet','document__number_id',('title','description'),('pk','document_id'))
    paginated=kind=='problem' and request.query_params.get('pagination')=='1'
    if paginated:
        page=int(request.query_params.get('page','1'));size=int(request.query_params.get('page_size','50'))
        if not 1<=page<=1000000 or not 1<=size<=100:raise DjangoValidationError('Некорректная страница банка задач.')
        count=qs.count();offset=(page-1)*size
    else:offset=0;size=300
    materials=list(read.material_rows(qs,kind).order_by('-created_at','-pk')[offset:offset+size])
    if kind=='worksheet':read.load_worksheet_items(materials)
    visible=s.visible_solution_ids(request.user,[material.pk for material in materials]) if kind=='problem' else None
    result=[material_data(material,request.user,allowed_solutions=visible) for material in materials]
    return Response({'results':result,'count':count,'page':page,'page_size':size} if paginated else result)

@api_view(['GET'])
def material_detail(request,kind,pk):
    qs=s.problems_for(request.user) if kind=='problem' else s.worksheets_for(request.user)
    circle=s.get_circle(request.user,request.query_params['circle']) if request.query_params.get('circle') else None
    if circle is not None:
        qs=qs.filter(items__worksheet__issues__circle=circle) if kind=='problem' else qs.filter(issues__circle=circle)
    material=qs.filter(pk=pk).first()
    if not material:raise s.NotFound('Материал недоступен.')
    return Response(material_data(material,request.user,True,circle))

@api_view(['GET','PATCH'])
def worksheet_document(request,pk):
    from . import worksheets
    revision=worksheets.update(request.user,pk,request.data) if request.method=='PATCH' else worksheets.get_document(request.user,pk)
    return Response(material_data(revision,request.user,True))

@api_view(['POST'])
def worksheet_copy(request,pk):
    from .worksheets import copy
    return Response(material_data(copy(request.user,pk),request.user,True),status=201)

@api_view(['POST'])
def worksheet_publish(request,pk):
    from .worksheets import publish
    return Response(material_data(publish(request.user,pk,request.data),request.user,True))

@api_view(['GET'])
def journal(request,pk,issue_id=None):
    from .journal import select_issues, snapshot
    circle=s.get_circle(request.user,pk)
    selected=select_issues(circle,str(issue_id) if issue_id is not None else request.query_params.get('issues','all'))
    problem_ids={item.problem_id for issue in selected for item in issue.worksheet.items.all()}
    visible=s.visible_solution_ids(request.user,problem_ids,circle)
    result=snapshot(request.user,circle,selected,lambda problem,user:material_data(problem,user,circle=circle,allowed_solutions=visible),request.query_params.get('q',''))
    if issue_id is not None:
        # Preserve the original one-worksheet API for existing clients.
        result.update(result['blocks'][0])
    return Response(result)

@api_view(['GET'])
def journal_export(request,pk):
    from .journal import select_issues, snapshot
    from .journal_export import export
    circle=s.get_circle(request.user,pk)
    selected=select_issues(circle,request.query_params.get('issues','all'),for_export=True)
    data=snapshot(request.user,circle,selected,lambda problem,user:{'id':str(problem.pk),'title':problem.display_title},request.query_params.get('q',''))
    return export(data,request.query_params.get('file_format','xlsx'))

@api_view(['POST'])
def mark(request,pk,problem_id,kind):
    circle=s.get_circle(request.user,pk,write=True)
    if kind not in ['solve','discussion','solution-visibility']:raise DjangoValidationError('Неизвестный тип отметки.')
    return Response(s.mark(request.user,circle,problem_id,request.data,kind=='discussion',kind=='solution-visibility'))

@api_view(['GET','POST'])
def topics(request):
    if request.method=='POST':
        topic=s.add_topic(request.user,str(request.data.get('name','')),request.data.get('parent_id'))
        return Response({'id':str(topic.pk),'public_id':public_id('topic',topic.number_id)},status=201)
    version=TopicCatalogVersion.objects.order_by('-pk').values_list('pk',flat=True).first()
    metadata=None
    catalogue=settings.BASE_DIR/'data'/'problems_topics.json'
    if catalogue.exists():
        source=json.loads(catalogue.read_text()).get('metadata',{})
        metadata={'complete':source.get('complete',False),'generated_at':source.get('generated_at'),'source_count':source.get('source_topic_count_including_root')}
    return Response({'version':version,'metadata':metadata,'topics':[{'id':str(t.pk),'public_id':public_id('topic',t.number_id),'name':t.name,'parent_id':str(t.parent_id) if t.parent_id else None,'is_other':t.is_other,'archived':t.archived,'sort_order':t.sort_order} for t in search_entities(Topic.objects.all(),request.query_params.get('q',''),'topic',text_fields=('name',))]})

@api_view(['PATCH'])
def topic_detail(request,pk):s.update_topic(request.user,pk,request.data);return Response({'ok':True})

@api_view(['GET','POST'])
def tags(request):
    if request.method=='POST':
        s.create_tag(request.user,request.data.get('kind'),request.data.get('name'))
    return Response([{'id':tag.pk,'public_id':public_id('tag',tag.pk),'kind':tag.kind,'name':tag.name,'archived':tag.archived} for tag in search_entities(Tag.objects.all(),request.query_params.get('q',''),'tag','pk',('name',),())],status=201 if request.method=='POST' else 200)

@api_view(['GET'])
def analytics(request):
    from .analytics import report
    return Response(report(request.user,request.query_params))

@api_view(['GET','POST'])
def invitations(request):
    if request.method=='POST':
        d=request.data;role=d.get('role')
        if role in ['student','teacher']:
            ids=s.selection_ids(d,'circle_ids','circle_id')
            selected=[s.get_circle(request.user,pk) for pk in ids]
        else:
            if d.get('circle_ids') or d.get('circle_id'):raise DjangoValidationError('Для этой роли область определяется без выбора кружков.')
            selected=[None]
        with transaction.atomic():
            objects=[s.invite(request.user,str(d.get('email','')),role,circle,d.get('tags')) for circle in selected]
        return Response({'id':str(objects[0].pk),'ids':[str(obj.pk) for obj in objects]},status=201)
    qs=Invitation.objects.all() if s.admin(request.user) else Invitation.objects.filter(created_by=request.user)
    from django.db.models import Prefetch
    qs=qs.prefetch_related(Prefetch('letters',queryset=EmailOutbox.objects.order_by('-pk'),to_attr='_delivery'))
    return Response([{'id':str(i.pk),'public_id':public_id('invitation',i.number_id),'email':i.email,'role':i.role,'circle':i.circle.name if i.circle else None,'circle_id':str(i.circle_id) if i.circle_id else None,'state':'expired' if i.state=='pending' and i.expires_at<=timezone.now() else i.state,'delivery':{'state':i._delivery[0].state,'attempts':i._delivery[0].attempts,'error_code':i._delivery[0].error_code,'sent_at':i._delivery[0].sent_at.isoformat() if i._delivery[0].sent_at else None} if i._delivery else None,'expires_at':i.expires_at.isoformat(),'created_at':i.created_at.isoformat()} for i in search_entities(qs,request.query_params.get('q',''),'invitation',text_fields=('email','circle__name')).select_related('circle').order_by('-created_at')[:100]])

@api_view(['DELETE'])
def invitation_detail(request,pk):
    invitation=Invitation.objects.get(pk=pk)
    s.require(s.admin(request.user) or invitation.created_by_id==request.user.pk)
    invitation.state='revoked';invitation.save();return Response({'ok':True})

@csrf_protect
@require_http_methods(['GET','POST'])
@ensure_csrf_cookie
def invitation_accept(request,token):
    try:
        invitation=s.valid_invitation(token)
        if request.method=='GET':
            recipient=User.objects.filter(email=invitation.email).first()
            return JsonResponse({'email':invitation.email,'role':invitation.role,'circle':invitation.circle.name if invitation.circle else None,'registered':recipient is not None,'student_profile_required':invitation.role=='student' and (recipient is None or 'student' not in recipient.roles),'csrf':get_token(request)})
        user=s.accept_invitation(token,json.loads(request.body),request.user if request.user.is_authenticated else None)
        login(request,user);return JsonResponse({'user':user_data(user),'csrf':get_token(request)})
    except Exception as exc:
        response=exception_handler(exc,{})
        if response:return JsonResponse(response.data,status=response.status_code)
        if hasattr(exc,'detail'):return JsonResponse({'detail':str(exc.detail)},status=403)
        raise

@api_view(['GET'])
def mailbox(request):
    s.require(settings.DEMO,'Локальный почтовый ящик доступен только в демо.')
    qs=EmailOutbox.objects.all() if s.admin(request.user) else EmailOutbox.objects.filter(invitation__created_by=request.user)
    rows=[]
    for letter in qs.select_related('invitation').order_by('-created_at')[:100]:
        content=json.loads(s.cipher().decrypt(letter.encrypted_payload.encode()))
        rows.append({'id':letter.pk,**content,'state':letter.invitation.state,'created_at':letter.created_at.isoformat()})
    return Response(rows)

@api_view(['GET','PATCH'])
def users(request):
    s.require(s.admin(request.user))
    if request.method=='PATCH':
        account=User.objects.get(pk=request.data.get('id'));roles=request.data.get('roles',[])
        if not roles or not set(roles)<=ROLES:raise DjangoValidationError('Выберите допустимые роли.')
        if 'admin' in account.roles and 'admin' not in roles and sum('admin' in u.roles for u in User.objects.filter(is_active=True))<=1:raise DjangoValidationError('Нельзя убрать последнего администратора.')
        with transaction.atomic():
            account.roles=roles;account.save();s.profiles(account)
            grantids=request.data.get('tags',[]);grants=Tag.objects.filter(pk__in=grantids,kind='circle',archived=False)
            if grants.count()!=len(set(grantids)):raise DjangoValidationError('Недопустимая область аналитика.')
            AnalystGrant.objects.filter(user=account).delete()
            if 'analyst' in roles:
                for tag in grants:AnalystGrant.objects.create(user=account,tag=tag)
            if 'teacher' not in roles:CircleTeacher.objects.filter(teacher__user=account,ended_at=None).update(ended_at=timezone.now())
            if 'student' not in roles:Enrollment.objects.filter(student__user=account,left_at=None).update(left_at=timezone.now())
            s.audit(request.user,'user.roles',{'user':account.pk,'roles':roles})
    from .people import filter_users
    qs=filter_users(User.objects.select_related('student','teacher').prefetch_related('analystgrant_set'),request.query_params).order_by('name_search','pk')
    meta=request.method=='GET' and request.query_params.get('meta')=='1'
    page=int(request.query_params.get('page','1')) if meta else 1
    if not 1<=page<=1000000:raise DjangoValidationError('Некорректный номер страницы.')
    selected=qs[(page-1)*30:page*30] if meta else qs[:300]
    rows=[{**user_data(u),'tags':[grant.tag_id for grant in u.analystgrant_set.all()]} for u in selected]
    if not meta:return Response(rows)
    return Response({'results':rows,'count':qs.count(),'page':page,'page_size':30,'graduation_years':list(Student.objects.filter(graduation_year__isnull=False).order_by('graduation_year').values_list('graduation_year',flat=True).distinct())})

@api_view(['GET'])
def audit(request,pk):
    circle=s.get_circle(request.user,pk)
    s.require(s.can_analyse_group(request.user,circle))
    return Response([{'id':e.pk,'actor':e.actor.name,'kind':e.kind,'payload':e.payload,'created_at':e.created_at.isoformat()} for e in AuditEvent.objects.filter(circle=circle).select_related('actor').order_by('-pk')[:100]])


@api_view(['GET'])
def documentation(request, section_id=None):
    from django.http import HttpResponse
    from .documentation import documentation_for
    audience = request.query_params.get('audience', 'robot' if request.path.startswith('/api/v1/') else 'human')
    if audience not in {'human','robot'}:
        raise DjangoValidationError('Выберите audience=human или audience=robot.')
    download = request.query_params.get('download')
    if download not in {None,'markdown'}:
        raise DjangoValidationError('Поддерживается download=markdown.')
    catalogue = documentation_for(request.user, demo=settings.DEMO, audience=audience,
                                   read_only=bool(getattr(request.auth,'read_only',False)))
    if section_id is not None:
        section = next((item for item in catalogue['sections'] if item['id'] == section_id), None)
        if section is None:
            raise s.NotFound('Раздел документации недоступен.')
        if download is None:
            return Response(section)
        catalogue['sections'] = [section]
    if download == 'markdown':
        from .documentation_export import markdown_documentation
        response = HttpResponse(markdown_documentation(catalogue), content_type='text/markdown; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="plusfolio-'+audience+'-guide.md"'
        return response
    return Response(catalogue)
