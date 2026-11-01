"""Explicit, version-checked changes to a circle's existing assignment."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from collections import Counter,defaultdict
from django.utils import timezone
from django.utils.dateparse import parse_date
from . import services as s
from .models import Circle,Worksheet,WorksheetItem,WorksheetIssue


def candidates(user,issue):
    return s.worksheets_for(user).filter(document_id=issue.document_id).filter(Q(archived=False)|Q(pk=issue.worksheet_id))


def options(user,circle,issue_id):
    s.require(s.can_write(user,circle))
    issue=circle.issues.only('id','version','circle_id','worksheet_id','document_id','issued_on','number').filter(pk=issue_id).first()
    if not issue:raise s.NotFound('Выдача не найдена.')
    # The picker needs identities and counts, never revision descriptions or task bodies.
    versions=list(candidates(user,issue).only('id','revision','title').order_by('-revision')[:50])
    if not any(row.pk==issue.worksheet_id for row in versions):
        versions.append(Worksheet.objects.only('id','revision','title').get(pk=issue.worksheet_id))
    problems=defaultdict(set);tracked=Counter()
    for wid,pid,included in WorksheetItem.objects.filter(worksheet_id__in=[row.pk for row in versions]).order_by().values_list('worksheet_id','problem_id','include_in_journal').iterator(chunk_size=1000):
        problems[wid].add(pid);tracked[wid]+=included
    original=problems[issue.worksheet_id]
    rows=[]
    for row in versions:
        ids=problems[row.pk]
        rows.append({'id':str(row.pk),'revision':row.revision,'title':row.title,'problem_count':len(ids),
                     'tracked_count':tracked[row.pk],
                     'added':len(ids-original),'removed':len(original-ids)})
    return {'version':issue.version,'worksheet_id':str(issue.worksheet_id),'issued_on':issue.issued_on.isoformat(),
            'number':issue.number,'versions':rows}


@transaction.atomic
def update(user,circle,issue_id,data):
    s.require(s.can_write(user,circle))
    Circle.objects.select_for_update().get(pk=circle.pk)
    issue=circle.issues.select_for_update(of=('self',)).select_related('worksheet__document','circle').filter(pk=issue_id).first()
    if not issue:raise s.NotFound('Выдача не найдена.')
    if set(data)-{'version','worksheet_id','issued_on'}:raise ValidationError('Можно изменить версию листка и дату выдачи.')
    if type(data.get('version')) is not int:raise ValidationError('Передайте версию выдачи.')
    if data['version']!=issue.version:raise s.Conflict('Выдача уже изменена. Откройте её заново.')
    target=data.get('worksheet_id',str(issue.worksheet_id))
    worksheet=candidates(user,issue).filter(pk=target).first()
    if not worksheet:raise ValidationError('Выберите доступную версию того же листка.')
    raw=data.get('issued_on',issue.issued_on.isoformat())
    try:issued_on=parse_date(raw) if isinstance(raw,str) else None
    except ValueError:issued_on=None
    if issued_on is None or issued_on>timezone.localdate():raise ValidationError('Укажите дату выдачи не в будущем.')
    if worksheet.pk==issue.worksheet_id and issued_on==issue.issued_on:return issue
    before={'worksheet_id':str(issue.worksheet_id),'revision':issue.worksheet.revision,'issued_on':issue.issued_on.isoformat()}
    previous=issue.version
    if WorksheetIssue.objects.filter(pk=issue.pk,version=previous).update(worksheet=worksheet,issued_on=issued_on,version=previous+1)!=1:
        raise s.Conflict('Выдача уже изменена. Откройте её заново.')
    issue.worksheet=worksheet;issue.issued_on=issued_on;issue.version=previous+1
    s.audit(user,'worksheet.issue.update',{'issue':issue.pk,'before':before,'after':{'worksheet_id':str(worksheet.pk),'revision':worksheet.revision,'issued_on':issued_on.isoformat()},'version':issue.version},circle)
    return issue
