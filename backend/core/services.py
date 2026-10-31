import base64, hashlib, json, secrets
from datetime import timedelta
from uuid import UUID
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Max, F, Exists, OuterRef
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, NotFound
from .models import (
    AnalystGrant, Assignment, AuditEvent, Circle, CircleTeacher, Discussion,
    EmailOutbox, Enrollment, Invitation, Problem, Solve, Student, Tag, Teacher,
    Topic, TopicCatalogVersion, User, Worksheet, WorksheetDocument,
    WorksheetIssue, WorksheetItem,
)

RANK={'student':1,'teacher':2,'analyst':3,'admin':4}
def admin(user): return 'admin' in user.roles
def require(value,message='Недостаточно прав.'):
    if not value: raise PermissionDenied(message)
def profiles(user):
    if 'student' in user.roles: Student.objects.get_or_create(user=user)
    if 'teacher' in user.roles: Teacher.objects.get_or_create(user=user)
def audit(user,kind,payload=None,circle=None):
    AuditEvent.objects.create(actor=user,kind=kind,payload=payload or {},circle=circle)
def circles_for(user):
    if admin(user): return Circle.objects.all()
    q=Q(pk__in=[])
    if 'teacher' in user.roles:q|=Q(Exists(CircleTeacher.objects.filter(circle_id=OuterRef('pk'),teacher__user=user,ended_at=None)))
    if 'student' in user.roles:q|=Q(Exists(Enrollment.objects.filter(circle_id=OuterRef('pk'),student__user=user,left_at=None)))
    if 'analyst' in user.roles:q|=Q(Exists(Circle.tags.through.objects.filter(circle_id=OuterRef('pk'),tag_id__in=AnalystGrant.objects.filter(user=user).values('tag_id'))))
    return Circle.objects.filter(q)
def analyst_circles_for(user):
    if 'analyst' not in user.roles: return Circle.objects.none()
    return Circle.objects.filter(Exists(Circle.tags.through.objects.filter(circle_id=OuterRef('pk'),tag_id__in=AnalystGrant.objects.filter(user=user).values('tag_id'))))
def get_circle(user,pk,write=False):
    circle=circles_for(user).filter(pk=pk).first()
    if not circle: raise NotFound('Кружок недоступен.')
    if write:
        require(admin(user) or ('teacher' in user.roles and CircleTeacher.objects.filter(circle=circle,teacher__user=user,ended_at=None).exists()))
        if circle.archived: raise ValidationError('Кружок в архиве.')
    return circle
def can_write(user,circle):
    return not circle.archived and (admin(user) or ('teacher' in user.roles and CircleTeacher.objects.filter(circle=circle,teacher__user=user,ended_at=None).exists()))
def can_analyse_group(user,circle=None):
    if admin(user): return True
    if circle is None: return bool({'teacher','analyst'}&set(user.roles))
    return ('teacher' in user.roles and CircleTeacher.objects.filter(circle=circle,teacher__user=user,ended_at=None).exists()) or ('analyst' in user.roles and circle.tags.filter(pk__in=AnalystGrant.objects.filter(user=user).values('tag_id')).exists())
def problems_for(user):
    qs=Problem.objects.filter(published=True)
    if admin(user) or 'teacher' in user.roles: return qs
    q=Q(Exists(WorksheetItem.objects.filter(problem_id=OuterRef('pk'),worksheet__issues__circle__in=circles_for(user))))
    if 'student' in user.roles:q|=Q(Exists(Solve.objects.filter(problem_id=OuterRef('pk'),student__user=user,solved=True)))
    return qs.filter(q)

def search_problems(queryset,text):
    from .identifiers import typed_id,validate_search
    text=validate_search(text)
    if not text:return queryset
    typed=typed_id(text)
    if typed:return queryset.filter(number_id=typed[1]) if typed[0]=='problem' and typed[1] else queryset.none()
    q=Q(title__icontains=text)|Q(description__icontains=text)|Q(statement__icontains=text)|Q(statement_tex__icontains=text)|Q(source_id__icontains=text)|Q(source__icontains=text)
    import re
    number=re.sub(r'^(?:задача\s*)?[№#]?\s*','',text,flags=re.I)
    if number.isdigit() and len(number)<=18:q|=Q(number_id=int(number))|Q(source_id=number)
    try:q|=Q(pk=UUID(text))
    except (ValueError,AttributeError):pass
    return queryset.filter(q)
def worksheets_for(user):
    qs=Worksheet.objects.filter(published=True)
    if admin(user):return qs
    from .people import has_adult_role
    visible=Q(document__author=user)|Q(document__public_revision_id=F('pk')) if has_adult_role(user) else Q(pk__in=[])
    visible|=Q(Exists(WorksheetIssue.objects.filter(worksheet_id=OuterRef('pk'),circle__in=circles_for(user))))
    if 'student' in user.roles:visible|=Q(Exists(Assignment.objects.filter(issue__worksheet_id=OuterRef('pk'),student__user=user)))
    return qs.filter(visible)
def my_problems_for(user):
    require('student' in user.roles)
    return Problem.objects.filter(published=True).filter(Exists(WorksheetItem.objects.filter(problem_id=OuterRef('pk'),worksheet__issues__assignments__student__user=user)))
def my_worksheets_for(user):
    require('student' in user.roles)
    return Worksheet.objects.filter(published=True).filter(Exists(Assignment.objects.filter(issue__worksheet_id=OuterRef('pk'),student__user=user)))
def solutions_for(user, problems, circle=None):
    """One solution scope for material views, documents and search."""
    if admin(user) or 'teacher' in user.roles:
        return problems
    allowed = Q(pk__in=[])
    if 'analyst' in user.roles:
        allowed |= Q(Exists(WorksheetItem.objects.filter(
            problem_id=OuterRef('pk'), worksheet__issues__circle__in=analyst_circles_for(user))))
    if 'student' in user.roles:
        revealed = Discussion.objects.filter(
            problem_id=OuterRef('pk'), discussed=True, solution_visible=True,
            circle__enrollments__student__user=user, circle__enrollments__left_at=None,
            circle__issues__worksheet__items__problem_id=OuterRef('pk'))
        if circle is not None:
            revealed = revealed.filter(circle=circle)
        allowed |= Q(Exists(revealed))
    return problems.filter(allowed)


def visible_solution_ids(user, problem_ids, circle=None):
    ids = set(problem_ids)
    if admin(user) or 'teacher' in user.roles:
        return ids
    return set(solutions_for(user, Problem.objects.filter(pk__in=ids), circle).values_list('pk', flat=True))


def solution_allowed(user, problem, circle=None):
    return problem.pk in visible_solution_ids(user, [problem.pk], circle)


def topic_active(topic, parents=None):
    parents = {} if parents is None else parents
    seen=set()
    while topic:
        if topic.pk in seen or topic.archived: return False
        seen.add(topic.pk)
        if topic.parent_id not in parents:
            parents[topic.parent_id] = topic.parent
        topic = parents[topic.parent_id]
    return True
def topic_ids_in_branch(raw):
    if not raw: return None
    from .filters import uuid_ids
    wanted=uuid_ids(raw)
    rows=list(Topic.objects.values_list('id','parent_id'))
    known={str(pk) for pk,_ in rows}
    if not wanted<=known: raise ValidationError('Тема не найдена.')
    from collections import defaultdict
    children=defaultdict(list)
    for pk,parent in rows:children[str(parent)].append(str(pk))
    pending=list(wanted)
    while pending:
        for child in children[pending.pop()]:
            if child not in wanted:wanted.add(child);pending.append(child)
    return wanted
def snapshot_topics():
    return TopicCatalogVersion.objects.create(snapshot=[{'id':str(t.id),'parent_id':str(t.parent_id) if t.parent_id else None,'name':t.name,'is_other':t.is_other,'archived':t.archived,'sort_order':t.sort_order} for t in Topic.objects.all()])

@transaction.atomic
def add_topic(user,name,parent_id):
    require(admin(user))
    # Serialize changes through the stable root row; PostgreSQL locks it.
    root=Topic.objects.select_for_update().get(parent=None)
    parent=Topic.objects.get(pk=parent_id or root.pk)
    name=name.strip()
    if not name or len(name)>160 or name.casefold()=='прочее': raise ValidationError('Укажите название обычной темы.')
    if parent.is_other or not topic_active(parent): raise ValidationError('В этом разделе нельзя создать тему.')
    topic=Topic.objects.create(name=name,parent=parent)
    Topic.objects.create(name='Прочее',parent=topic,is_other=True)
    snapshot_topics();audit(user,'topic.create',{'topic':str(topic.pk)})
    return topic

@transaction.atomic
def update_topic(user,pk,data):
    require(admin(user));Topic.objects.select_for_update().get(parent=None)
    topic=Topic.objects.get(pk=pk)
    if topic.is_other or topic.parent_id is None: raise ValidationError('Системная тема защищена.')
    if 'name' in data:
        topic.name=str(data['name']).strip()
        if not topic.name or topic.name.casefold()=='прочее': raise ValidationError('Недопустимое название.')
    if 'parent_id' in data:
        parent=Topic.objects.get(pk=data['parent_id'])
        if parent.is_other or not topic_active(parent): raise ValidationError('Недопустимый родитель.')
        path=parent
        while path:
            if path.pk==topic.pk: raise ValidationError('Перенос создаст цикл.')
            path=path.parent
        topic.parent=parent
    if 'archived' in data: topic.archived=bool(data['archived'])
    topic.save();snapshot_topics();audit(user,'topic.update',{'topic':str(topic.pk)})
    return topic

@transaction.atomic
def create_material(user,kind,data,*,_document=None,_base=None):
    from .people import has_adult_role
    if kind=='worksheet':require(has_adult_role(user),'Создание личных листков школьнику недоступно.')
    require(_document.author_id==user.pk if kind=='worksheet' and _document else admin(user) or 'teacher' in user.roles)
    title=str(data.get('title') or '').strip()
    if len(title)>180 or kind=='worksheet' and not title: raise ValidationError('Укажите название листка, до 180 символов.' if kind=='worksheet' else 'Название задачи — до 180 символов.')
    topics=list(Topic.objects.filter(pk__in=data.get('topics',[])))
    parents = {topic.pk: topic for topic in topics}
    if not topics or len(topics)!=len(set(data.get('topics',[]))) or any(t.parent_id is None or not topic_active(t, parents) for t in topics): raise ValidationError('Выберите хотя бы одну доступную тему.')
    tags=list(Tag.objects.filter(pk__in=data.get('tags',[]),kind=kind,archived=False))
    if len(tags)!=len(set(data.get('tags',[]))): raise ValidationError('Недопустимые теги.')
    model=Problem if kind=='problem' else Worksheet
    extra={}
    if kind=='worksheet':
        document=_document or WorksheetDocument.objects.create(author=user)
        extra={'document':document,'revision':document.current_revision.revision+1 if document.current_revision_id else 1}
    if kind=='problem':
        extra={'statement':str(data.get('statement','')).strip(),'solution':str(data.get('solution','')).strip()}
        if data.get('copy_of'):
            original=problems_for(user).filter(pk=data['copy_of']).first()
            if not original:raise NotFound('Исходная задача недоступна.')
            extra['source_metadata']={'copied_from':str(original.pk),'attribution':original.attribution}
        from .documents import validate_tex
        for field in ['statement_tex','solution_tex']:
            extra[field]=str(data.get(field,'')).strip()
            if extra[field]:validate_tex(extra[field])
        if not (extra['statement'] or extra['statement_tex']) or not (extra['solution'] or extra['solution_tex']):raise ValidationError('Заполните условие и решение текстом или TeX.')
    material=model.objects.create(title=title,description=str(data.get('description','')),author=user,**extra)
    material.topics.set(topics);material.tags.set(tags)
    if kind=='worksheet':
        ids=data.get('problems',[])
        if not ids or len(ids)!=len(set(ids)): raise ValidationError('Добавьте неповторяющиеся задачи.')
        available=problems_for(user).filter(archived=False)
        if _base is not None:available=(available|Problem.objects.filter(items__worksheet=_base)).distinct()
        valid={str(p.pk):p for p in available.filter(pk__in=ids)}
        if len(valid)!=len(ids): raise ValidationError('Недоступная задача.')
        WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=material,problem=valid[str(pk)],position=index+1) for index,pk in enumerate(ids)])
        if any(problem.statement_tex or problem.solution_tex for problem in valid.values()):
            from .documents import project_for,render_pdf
            render_pdf(project_for(material,[valid[str(pk)] for pk in ids],visible_solution_ids(user,[p.pk for p in valid.values()]),True))
    material.topic_catalog_version_id=TopicCatalogVersion.objects.order_by('-pk').values_list('pk',flat=True).first()
    material.published=True;material.save()
    if kind=='worksheet':
        document.current_revision=material;document.save(update_fields=['current_revision'])
    audit(user,f'{kind}.save' if kind=='worksheet' else f'{kind}.publish',{'id':str(material.pk),'title':title})
    return material

@transaction.atomic
def enroll(user,circle,email='',student_id=None):
    require(can_write(user,circle))
    if student_id is not None:
        if type(student_id) is not int or student_id<=0:raise ValidationError('Выберите школьника из подсказок.')
        account=User.objects.filter(student__pk=student_id,is_active=True).first()
    else:account=User.objects.filter(email=email.strip().lower(),is_active=True).first()
    if not account: raise ValidationError('Аккаунт не найден. Отправьте приглашение.')
    if 'student' not in account.roles: raise ValidationError('У аккаунта нет роли школьника.')
    profiles(account)
    membership,created=Enrollment.objects.get_or_create(circle=circle,student=account.student,left_at=None)
    assign_issues(account.student,circle.issues.all())
    if created:audit(user,'enrollment.add',{'student':account.pk},circle)
    return membership

def assign_issues(student,issues):
    issue_ids=list(issues.values_list('pk',flat=True))
    assigned=set(Assignment.objects.filter(student=student,issue_id__in=issue_ids).values_list('issue_id',flat=True))
    Assignment.objects.bulk_create([Assignment(student=student,issue_id=pk) for pk in issue_ids if pk not in assigned],ignore_conflicts=True)

@transaction.atomic
def update_student(user,circle,student_id,data):
    require(can_write(user,circle))
    student=Student.objects.select_for_update().filter(pk=student_id,enrollments__circle=circle,enrollments__left_at=None).first()
    if not student:raise NotFound('Действующий участник кружка не найден.')
    if set(data)!={'graduation_year'}:raise ValidationError('Укажите только год окончания 11-го класса.')
    year=data['graduation_year']
    if year is not None and (type(year) is not int or not 1900<=year<=2200):
        raise ValidationError('Год окончания 11-го класса должен быть целым числом от 1900 до 2200 или не указан.')
    old=student.graduation_year
    if old!=year:
        student.graduation_year=year
        student.save(update_fields=['graduation_year'])
        audit(user,'student.update',{'student_id':student.pk,'old_graduation_year':old,'graduation_year':year},circle)
    return student

@transaction.atomic
def unenroll(user,circle,email):
    require(can_write(user,circle))
    memberships=Enrollment.objects.filter(circle=circle,student__user__email=email.strip().lower(),left_at=None)
    memberships.update(left_at=timezone.now())
    Invitation.objects.filter(circle=circle,email=email.strip().lower(),role='student',state='pending').update(state='revoked')
    audit(user,'enrollment.end',{'email':email.strip().lower()},circle)

@transaction.atomic
def assign_teacher(user,circle,email,remove=False):
    require(admin(user),'Назначать и отзывать преподавателей напрямую может администратор.')
    from .identifiers import typed_id
    from .people import search_people
    candidates=User.objects.filter(is_active=True)
    account=(search_people(candidates,email) if typed_id(email) else candidates.filter(email=email.strip().lower())).first()
    if not account or 'teacher' not in account.roles: raise ValidationError('Зарегистрированный преподаватель не найден.')
    profiles(account)
    if remove: CircleTeacher.objects.filter(circle=circle,teacher=account.teacher,ended_at=None).update(ended_at=timezone.now())
    else:
        CircleTeacher.objects.get_or_create(circle=circle,teacher=account.teacher,ended_at=None)
        if circle.launched_at is None:circle.launched_at=timezone.now();circle.save()
    audit(user,'teacher.end' if remove else 'teacher.add',{'user':account.pk},circle)

@transaction.atomic
def issue_worksheet(user,circle,worksheet_id,issued_on):
    require(can_write(user,circle))
    Circle.objects.select_for_update().get(pk=circle.pk)
    from .worksheets import catalogue
    worksheet=catalogue(user).filter(pk=worksheet_id,archived=False).first()
    if not worksheet:raise ValidationError('Листок недоступен.')
    if issued_on>timezone.localdate():raise ValidationError('Дата не может быть в будущем.')
    if WorksheetIssue.objects.filter(circle=circle,document_id=worksheet.document_id).exists():raise ValidationError('Этот листок уже выдан кружку.')
    number=(circle.issues.aggregate(last=Max('number'))['last'] or 0)+1
    issue=WorksheetIssue.objects.create(circle=circle,worksheet=worksheet,document_id=worksheet.document_id,issued_on=issued_on,issued_by=user,number=number)
    Assignment.objects.bulk_create([Assignment(issue=issue,student_id=pk) for pk in circle.enrollments.filter(left_at=None).values_list('student_id',flat=True)])
    audit(user,'worksheet.issue',{'worksheet':str(worksheet.pk)},circle)
    return issue

def selection_ids(data,plural,singular):
    """Validate an explicit nonempty batch before any writes; keep scalar clients working."""
    from .filters import uuid_ids
    values=data.get(plural) if plural in data else [data.get(singular)]
    if not isinstance(values,list) or not values or len(values)>300 or any(not isinstance(value,str) or ',' in value for value in values):
        raise ValidationError('Выберите от 1 до 300 записей.')
    ids=uuid_ids(values)
    return list(dict.fromkeys(str(UUID(value)) for value in values)) if ids else []

class Conflict(Exception):pass
@transaction.atomic
def mark(user,circle,problem_id,data,discussion=False,solution_visibility=False):
    require(can_write(user,circle))
    problem=Problem.objects.only('pk').filter(pk=problem_id,items__worksheet__issues__circle=circle).first()
    if not problem:raise ValidationError('Задача не выдавалась этому кружку.')
    value=data.get('value');version=data.get('version')
    if type(value) is not bool or type(version) is not int or version<0:raise ValidationError('Передайте да/нет и ожидаемую версию.')
    if solution_visibility:discussion=True
    if discussion:
        model=Discussion;lookup={'circle':circle,'problem':problem};field='solution_visible' if solution_visibility else 'discussed'
    else:
        student=Student.objects.filter(pk=data.get('student_id'),enrollments__circle=circle,enrollments__left_at=None).first()
        if not student:raise ValidationError('Школьник сейчас не состоит в кружке.')
        model=Solve;lookup={'student':student,'problem':problem};field='solved'
    row=model.objects.select_for_update().filter(**lookup).first()
    previous=getattr(row,field) if row else False
    previous_visibility=row.solution_visible if discussion and row else False
    if (row.version if row else 0)!=version:raise Conflict('Отметка уже изменена. Обновите журнал.')
    if solution_visibility and value and (row is None or not row.discussed):
        raise ValidationError('Сначала отметьте задачу как разобранную в кружке.')
    if row:
        # Conditional update also prevents silent races on SQLite's local demo.
        changes={field:value,'version':version+1,'changed_by':user}
        if discussion and not solution_visibility and not value:changes['solution_visible']=False
        if not discussion:changes.update(source_circle=circle,updated_at=timezone.now())
        if model.objects.filter(pk=row.pk,version=version).update(**changes)!=1:raise Conflict('Конфликт отметок.')
    else:
        extras={'changed_by':user,field:value}
        if not discussion:extras['source_circle']=circle
        row=model.objects.create(**lookup,**extras)
    result={field:value,'version':version+1}
    payload={'problem':str(problem.pk),'student':lookup.get('student').pk if not discussion else None,'value':value,'previous':previous}
    if discussion:
        result['solution_visible']=value if solution_visibility else (previous_visibility if value else False)
        payload.update(previous_solution_visible=previous_visibility,solution_visible=result['solution_visible'])
    audit(user,'solution.visibility' if solution_visibility else 'discussion.change' if discussion else 'solve.change',payload,circle)
    return result

def invitation_allowed(user,role,circle):
    if role not in RANK:return False
    if role=='admin':return admin(user)
    if RANK[role]>=max(RANK[r] for r in user.roles):return False
    if role=='analyst':return admin(user)
    if not circle or circle.archived:return False
    if role=='teacher':return admin(user) or ('analyst' in user.roles and circle.launched_at is not None and analyst_circles_for(user).filter(pk=circle.pk).exists())
    return admin(user) or can_write(user,circle) or ('analyst' in user.roles and circle.launched_at is not None and analyst_circles_for(user).filter(pk=circle.pk).exists())
def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()))

@transaction.atomic
def invite(user,email,role,circle=None,tag_ids=None):
    from django.core.validators import validate_email
    email=email.strip().lower();validate_email(email)
    require(invitation_allowed(user,role,circle),'Нельзя пригласить эту роль в выбранную область.')
    tags=list(Tag.objects.filter(pk__in=tag_ids or [],kind='circle',archived=False))
    if role=='analyst' and (not tags or len(tags)!=len(set(tag_ids or []))):raise ValidationError('Выберите теги кружков для аналитика.')
    Invitation.objects.filter(email=email,role=role,circle=circle,state='pending').update(state='revoked')
    token=secrets.token_urlsafe(32)
    invitation=Invitation.objects.create(email=email,role=role,circle=circle,created_by=user,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=timezone.now()+timedelta(days=7))
    invitation.tags.set(tags)
    payload={'to':email,'subject':'Приглашение в Plusfolio','token':token,'role':role,'circle':circle.name if circle else None}
    EmailOutbox.objects.create(invitation=invitation,encrypted_payload=cipher().encrypt(json.dumps(payload,ensure_ascii=False).encode()).decode())
    audit(user,'invitation.create',{'invitation':str(invitation.pk),'role':role},circle)
    return invitation

def valid_invitation(token,lock=False):
    qs=Invitation.objects.select_for_update() if lock else Invitation.objects.select_related('created_by','circle')
    invitation=qs.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not invitation or invitation.state!='pending' or invitation.expires_at<=timezone.now():raise ValidationError('Приглашение истекло, отозвано или уже использовано.')
    require(invitation.created_by.is_active and invitation_allowed(invitation.created_by,invitation.role,invitation.circle),'Отправитель больше не может выдать доступ.')
    return invitation

@transaction.atomic
def accept_invitation(token,data,current_user=None):
    from django.contrib.auth.password_validation import validate_password
    if not isinstance(data,dict):raise ValidationError('Некорректные данные регистрации.')
    invitation=valid_invitation(token,True)
    user=User.objects.select_for_update().filter(email=invitation.email).first()
    identity=None
    if user:
        require(current_user is not None and current_user.pk==user.pk,'Войдите под email получателя, чтобы принять приглашение.')
        require(user.is_active)
        if invitation.role=='student' and 'student' not in user.roles:
            from .people import student_identity
            identity=student_identity(data)
            for field in ['name','last_name','first_name']:setattr(user,field,identity[field])
        user.roles=sorted(set(user.roles)|{invitation.role});user.save()
    else:
        password=str(data.get('password',''));validate_password(password)
        if invitation.role=='student':
            from .people import student_identity
            identity=student_identity(data)
        name=identity['name'] if identity else str(data.get('name','')).strip()
        if not name:raise ValidationError('Укажите имя.')
        names={field:identity[field] for field in ['first_name','last_name']} if identity else {}
        user=User.objects.create_user(invitation.email,password,name=name,roles=[invitation.role],**names)
    profiles(user)
    if identity:
        user.student.graduation_year=identity['graduation_year'];user.student.no_patronymic=identity['no_patronymic']
        user.student.patronymic=identity['patronymic']
        user.student.save(update_fields=['graduation_year','no_patronymic','patronymic'])
    if invitation.role=='student':
        Enrollment.objects.get_or_create(circle=invitation.circle,student=user.student,left_at=None)
        assign_issues(user.student,invitation.circle.issues.all())
    if invitation.role=='teacher':
        CircleTeacher.objects.get_or_create(circle=invitation.circle,teacher=user.teacher,ended_at=None)
        if invitation.circle.launched_at is None:invitation.circle.launched_at=timezone.now();invitation.circle.save()
    if invitation.role=='analyst':
        for tag in invitation.tags.all():AnalystGrant.objects.get_or_create(user=user,tag=tag)
    invitation.state='accepted';invitation.save()
    audit(user,'invitation.accept',{'invitation':str(invitation.pk)},invitation.circle)
    return user


@transaction.atomic
def create_tag(user,kind,name):
    require(admin(user),'Создавать теги может только администратор.')
    if kind not in ['problem','worksheet','circle'] or not isinstance(name,str) or not name.strip():
        raise ValidationError('Укажите справочник и название тега.')
    name=name.strip()
    if len(name)>100:raise ValidationError('Название тега не должно превышать 100 символов.')
    if Tag.objects.filter(kind=kind,name=name).exists():raise Conflict('Тег с таким названием уже есть в этом справочнике.')
    tag=Tag.objects.create(kind=kind,name=name)
    audit(user,'tag.create',{'id':tag.pk,'kind':tag.kind,'name':tag.name})
    return tag
