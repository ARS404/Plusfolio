"""Derived metadata index. Primary querysets decide access before retrieval."""

from .models import CatalogueSearchDocument, Circle, Worksheet, Topic
from .search import rank_documents, index_documents
from .search_index import text_fields, sync_documents

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


def sync_entities(kind,rows,paths=None):
    if kind=='topic' and paths is None:paths=topic_paths()
    def entries():
        for row in rows:
            if kind=='topic':text=paths.get(row.pk,'')
            elif kind=='circle':text='\n'.join([row.name,row.description,row.city,row.region])
            else:text='\n'.join([row.title,row.description])
            yield {'kind':kind,'object_id':row.pk,**text_fields(text)}
    sync_documents(CatalogueSearchDocument,entries(),'object_id')


def sync_entity(instance,paths=None):
    kind=next((key for key,model in MODELS.items() if isinstance(instance,model)),None)
    if not kind:return
    if kind=='worksheet' and not instance.published:
        CatalogueSearchDocument.objects.filter(kind=kind,object_id=instance.pk).delete();return
    sync_entities(kind,[instance],paths)


def sync_topics():
    # Parent edits change descendant paths; unchanged vectors survive the batch.
    paths=topic_paths()
    sync_entities('topic',Topic.objects.only('id').iterator(chunk_size=100),paths)


def reconcile(rebuild=False):
    for kind,model in MODELS.items():
        rows=model.objects.all()
        if kind=='worksheet':rows=rows.filter(published=True)
        CatalogueSearchDocument.objects.filter(kind=kind).exclude(object_id__in=rows.values('pk')).delete()
        if not rebuild:rows=rows.exclude(pk__in=CatalogueSearchDocument.objects.filter(kind=kind).values('object_id'))
        fields={'topic':['id'],'circle':['id','name','description','city','region'],'worksheet':['id','title','description']}[kind]
        sync_entities(kind,rows.only(*fields).iterator(chunk_size=100))


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
