"""Metadata search for list views and pickers. Never ranks inaccessible rows."""
from uuid import UUID
from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from . import services as s, filters as f, queries as read
from .models import Topic
from .identifiers import typed_id, search_entities, public_id
from .catalogue_search import retrieve


@api_view(['GET'])
def catalogue_search(request):
    params=request.query_params
    kind=params.get('kind','');text=params.get('q','').strip();mode=params.get('mode','hybrid');scope=params.get('scope','available')
    try:limit=int(params.get('limit','30'))
    except (ValueError,TypeError):raise ValidationError('limit: целое число 1–100.')
    if kind not in {'circle','worksheet','topic'} or not 1<=len(text)<=160 or mode not in {'text','hybrid'} or not 1<=limit<=100:
        raise ValidationError('kind: circle/worksheet/topic; q: 1–160 символов; mode: hybrid/text; limit: 1–100.')
    key=f'catalogue-search:{request.user.pk}'
    if cache.add(key,1,60):count=1
    else:
        try:count=cache.incr(key)
        except ValueError:cache.set(key,1,60);count=1
    if count>60:raise Throttled(wait=60,detail='Слишком много поисков. Повторите через минуту.')
    if kind=='circle':
        if scope!='available':raise ValidationError('Для кружков scope=available.')
        rows=f.by_city(s.circles_for(request.user),f.query_values(params,'city'))
        rows=f.by_tags(rows,f.query_values(params,'tag'),'circle')
        state=params.get('state','all')
        if state not in {'active','all'}:raise ValidationError('state: active/all.')
        if state=='active':rows=rows.filter(archived=False)
        number='number_id';fields=('name','description','city','region');uuids=('pk',)
    elif kind=='worksheet':
        from .worksheets import catalogue
        if scope=='my':rows=s.my_worksheets_for(request.user)
        elif scope=='issued':
            circles=s.circles_for(request.user).filter(pk__in=f.query_values(params,'circle'))
            rows=s.worksheets_for(request.user).filter(issues__circle__in=circles).distinct()
        else:rows=catalogue(request.user,scope)
        rows=f.by_tags(rows,f.query_values(params,'tag'),'worksheet')
        topics=s.topic_ids_in_branch(f.query_values(params,'topic'))
        if topics is not None:rows=rows.filter(topics__pk__in=topics).distinct()
        number='document__number_id';fields=('title','description');uuids=('pk','document_id')
    else:
        s.require(bool({'teacher','analyst','admin'}&set(request.user.roles)))
        if scope!='available':raise ValidationError('Для тем scope=available.')
        rows=Topic.objects.exclude(parent_id=None)
        number='number_id';fields=('name',);uuids=('pk',)
    try:UUID(text);is_uuid=True
    except ValueError:is_uuid=False
    identity=bool(typed_id(text) or is_uuid or text.isascii() and text.isdigit())
    if identity:
        matched=list(search_entities(rows,text,kind,number,fields,uuids).values_list('pk',flat=True)[:limit])
        ranked=[(pk,{'kind':'identifier','excerpt':''}) for pk in matched]
        meta={'semantic':False,'pending':0,'notice':''}
    else:ranked,meta=retrieve(rows,kind,text,limit,mode=='hybrid' and len(text)>=3)
    matches=dict(ranked)
    # Fetch again through the permission-scoped queryset; index rows never grant access.
    selected=rows.filter(pk__in=matches)
    if kind=='circle':
        from .api import circle_data
        entities={row.pk:circle_data(row,request.user) for row in read.circle_rows(selected,request.user)}
    elif kind=='worksheet':
        from .api import material_data
        selected=list(read.material_rows(selected,'worksheet'));read.load_worksheet_items(selected)
        entities={row.pk:material_data(row,request.user) for row in selected}
    else:entities={row.pk:{'id':str(row.pk),'public_id':public_id('topic',row.number_id),'name':row.name,
        'parent_id':str(row.parent_id),'is_other':row.is_other,'archived':row.archived,'sort_order':row.sort_order} for row in selected}
    return Response({'kind':kind,'results':[{'entity':entities[pk],'match':match['kind'],'excerpt':match['excerpt']}
        for pk,match in ranked if pk in entities],**meta})
