"""Personal worksheet documents with immutable, independently published revisions."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F,Q
from .models import Worksheet,WorksheetDocument
from . import services as s


def catalogue(user,scope='available'):
    if scope not in {'available','public','mine','all'}:raise ValidationError('Неизвестный раздел листков.')
    rows=Worksheet.objects.filter(published=True)
    if scope=='all':s.require(s.admin(user))
    if scope=='mine':return rows.filter(document__author=user,document__current_revision_id=F('pk'))
    library=bool({'admin','teacher','analyst'}&set(user.roles))
    if scope=='public':return rows.filter(document__public_revision_id=F('pk')) if library else rows.none()
    if s.admin(user):return rows.filter(document__current_revision_id=F('pk'))
    own=Q(document__author=user,document__current_revision_id=F('pk'))
    if library:own|=Q(document__public_revision_id=F('pk'))&~Q(document__author=user)
    return rows.filter(own)


def get_document(user,pk):
    revision=catalogue(user).select_related('document','author').filter(document_id=pk).first()
    if not revision:raise s.NotFound('Листок недоступен.')
    return revision


def metadata(revision,user):
    document=revision.document
    current=document.current_revision_id==revision.pk
    owner=document.author_id==user.pk
    return {'public_id':f'W-{document.number_id}','document_id':str(document.pk),'author_id':document.author_id,'revision':revision.revision,
            'is_public':document.public_revision_id==revision.pk,
            'can_edit':owner and current and not revision.archived,'can_copy':not revision.archived,
            'can_publish':s.admin(user) and current and not revision.archived and document.public_revision_id!=revision.pk,
            'has_unpublished_changes':bool((owner or s.admin(user)) and document.public_revision_id and document.public_revision_id!=document.current_revision_id)}


def fields(revision):
    return {'title':revision.title,'description':revision.description,
            'topics':[str(pk) for pk in revision.topics.values_list('pk',flat=True)],
            'tags':list(revision.tags.values_list('pk',flat=True)),
            'problems':[str(pk) for pk in revision.items.values_list('problem_id',flat=True)]}


@transaction.atomic
def update(user,pk,data):
    document=WorksheetDocument.objects.select_for_update(of=('self',)).select_related('current_revision').filter(pk=pk).first()
    if not document:raise s.NotFound('Листок недоступен.')
    s.require(document.author_id==user.pk,'Редактировать листок может только его автор.')
    base=document.current_revision
    if base.archived:raise ValidationError('Листок в архиве.')
    if type(data.get('version')) is not int:raise ValidationError('Передайте номер редактируемой версии.')
    if data['version']!=base.revision:raise s.Conflict('Листок уже изменён. Обновите страницу перед сохранением.')
    values=fields(base)
    values.update({key:data[key] for key in values if key in data})
    return s.create_material(user,'worksheet',values,_document=document,_base=base)


@transaction.atomic
def copy(user,revision_id):
    source=s.worksheets_for(user).filter(pk=revision_id,archived=False).first()
    if not source:raise s.NotFound('Листок недоступен.')
    document=WorksheetDocument.objects.create(author=user,copied_from=source)
    values=fields(source);values['title']=(source.title[:172]+' — копия')[:180]
    result=s.create_material(user,'worksheet',values,_document=document,_base=source)
    s.audit(user,'worksheet.copy',{'source':str(source.pk),'document':str(document.pk)})
    return result


@transaction.atomic
def publish(user,pk,data):
    s.require(s.admin(user),'Публиковать листки для всех может только администратор.')
    document=WorksheetDocument.objects.select_for_update(of=('self',)).select_related('current_revision').get(pk=pk)
    current=document.current_revision
    if current.archived:raise ValidationError('Листок в архиве.')
    if type(data.get('version')) is not int:raise ValidationError('Передайте номер публикуемой версии.')
    if data['version']!=current.revision:raise s.Conflict('Автор уже изменил листок. Проверьте новую версию перед публикацией.')
    if document.public_revision_id!=current.pk:
        document.public_revision=current;document.save(update_fields=['public_revision'])
        s.audit(user,'worksheet.publish',{'document':str(document.pk),'revision':current.revision})
    return current
