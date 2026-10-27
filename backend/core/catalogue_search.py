"""Derived metadata index. Primary querysets decide access before retrieval."""
import hashlib
from django.db.models import Q
from .models import CatalogueSearchDocument, Circle, Worksheet, Topic
from .search import normalized, rank_documents, index_documents, EmbeddingUnavailable, MODEL_ID

MODELS={'circle':Circle,'worksheet':Worksheet,'topic':Topic}


def topic_paths():
    nodes={row.pk:row for row in Topic.objects.only('id','name','parent_id')}
    paths={}
    for pk,node in nodes.items():
        chain=[];seen=set()
        while node and node.pk not in seen:
            seen.add(node.pk)
            if node.parent_id:chain.append(node.name)
            node=nodes.get(node.parent_id)
        paths[pk]=' / '.join(reversed(chain))
    return paths


def sync_entity(instance, paths=None):
    kind=next((key for key,model in MODELS.items() if isinstance(instance,model)),None)
    if not kind:return
    if kind=='worksheet' and not instance.published:
        CatalogueSearchDocument.objects.filter(kind=kind,object_id=instance.pk).delete();return
    if kind=='topic':
        text=(paths if paths is not None else topic_paths()).get(instance.pk,'')
    elif kind=='circle':text='\n'.join([instance.name,instance.description,instance.city,instance.region])
    else:text='\n'.join([instance.title,instance.description])
    text=text.strip();fingerprint=hashlib.sha256(normalized(text).encode()).hexdigest()
    doc,created=CatalogueSearchDocument.objects.get_or_create(kind=kind,object_id=instance.pk,
        defaults={'text':text,'normalized':normalized(text).casefold(),'fingerprint':fingerprint})
    if not created and doc.fingerprint!=fingerprint:
        CatalogueSearchDocument.objects.filter(pk=doc.pk).update(text=text,normalized=normalized(text).casefold(),
            fingerprint=fingerprint,embedding=None,model='',retry_at=None)


def sync_topics():
    # Renaming or moving a parent changes every descendant's indexed path.
    paths=topic_paths()
    for row in Topic.objects.all().iterator(chunk_size=200):sync_entity(row,paths)


def reconcile(rebuild=False):
    for kind,model in MODELS.items():
        rows=model.objects.all()
        if kind=='worksheet':rows=rows.filter(published=True)
        CatalogueSearchDocument.objects.filter(kind=kind).exclude(object_id__in=rows.values('pk')).delete()
        if not rebuild:rows=rows.exclude(pk__in=CatalogueSearchDocument.objects.filter(kind=kind).values('object_id'))
        paths=topic_paths() if kind=='topic' else None
        for row in rows.iterator(chunk_size=100):sync_entity(row,paths)


def index_batch(batch_size=8):
    return index_documents(CatalogueSearchDocument.objects.exclude(text=''),batch_size)


def retrieve(rows,kind,text,limit=20,semantic=True):
    docs=CatalogueSearchDocument.objects.filter(kind=kind,object_id__in=rows.values('pk')).exclude(text='')
    return rank_documents(docs,text,limit,semantic)


def search_issued(issues,text,semantic=False):
    from uuid import UUID
    from .identifiers import typed_id,search_issues,validate_search
    text=validate_search(text)
    if not text:return issues
    try:UUID(text);identity=True
    except ValueError:identity=bool(typed_id(text) or text.isascii() and text.isdigit())
    if identity or not semantic:return search_issues(issues,text)
    rows=Worksheet.objects.filter(pk__in=issues.values('worksheet_id'))
    ranked,_=retrieve(rows,'worksheet',text,limit=100)
    return issues.filter(worksheet_id__in=[pk for pk,_ in ranked])
