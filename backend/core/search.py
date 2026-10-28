"""Permission-scoped hybrid retrieval; the model never decides object access."""
import heapq
import json
from datetime import timedelta
from functools import lru_cache
from urllib.request import Request


import numpy as np
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Q
from django.utils import timezone
from pgvector.django import CosineDistance
from .models import Problem, ProblemSearchDocument
from . import services as s
from .search_index import normalized, text_fields, sync_documents

MODEL_ID = 'e5-small-int8-614241f622f5-chunk448-v1'


class EmbeddingUnavailable(Exception):
    pass


def problem_text(problem, kind):
    values = [problem.title, problem.description] if kind == 'metadata' else [getattr(problem, kind), getattr(problem, kind + '_tex')]
    return '\n'.join(dict.fromkeys(value.strip() for value in values if value.strip()))


def sync_problems(problems):
    def entries():
        for problem in problems:
            for kind in ['statement','solution','metadata']:
                yield {'problem_id':problem.pk,'kind':kind,**text_fields(problem_text(problem,kind))}
    sync_documents(ProblemSearchDocument,entries(),'problem_id')


def sync_problem(problem):
    if not problem.published:
        ProblemSearchDocument.objects.filter(problem=problem).delete()
        return
    sync_problems([problem])


def reconcile_missing(rebuild=False):
    # Bulk imports bypass signals, so recover missing rows in bounded batches.
    rows=Problem.objects.filter(published=True)
    if not rebuild:rows=rows.annotate(docs=Count('search_documents')).filter(docs__lt=3)
    rows=rows.only('id','title','description','statement','statement_tex','solution','solution_tex')
    sync_problems(rows.iterator(chunk_size=100))


def _embed_request(texts, mode='query'):
    request = Request(settings.EMBEDDING_URL.rstrip('/') + '/embed',
        data=json.dumps({'texts': texts, 'mode': mode}).encode(), headers={'Content-Type': 'application/json'})
    try:
        # Explicitly bypass environment HTTP proxies for this private local service.
        from urllib.request import build_opener, ProxyHandler
        with build_opener(ProxyHandler({})).open(request, timeout=60 if mode == 'document' else 8) as response:
            data = json.load(response)
        vectors = np.asarray(data['vectors'], dtype=np.float32)
        if data.get('model') != MODEL_ID or vectors.shape != (len(texts), 384) or not np.isfinite(vectors).all():
            raise ValueError()
        norms = np.linalg.norm(vectors, axis=1)
        if not np.allclose(norms, 1, atol=.01):
            raise ValueError()
        return vectors
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise EmbeddingUnavailable('Локальная модель недоступна.') from error


def embed(texts, mode='query'):
    # Bound HTTP payloads and cover arbitrarily long source documents in batches.
    pieces, owners = [], []
    for owner, text in enumerate(texts):
        for start in range(0, len(text), 10000):
            pieces.append(text[start:start+10000]); owners.append(owner)
    result = np.zeros((len(texts),384),dtype=np.float32)
    for start in range(0,len(pieces),8):
        vectors = _embed_request(pieces[start:start+8],mode)
        for owner, vector in zip(owners[start:start+8], vectors):
            result[owner] += vector
    result /= np.maximum(np.linalg.norm(result,axis=1,keepdims=True),1e-12)
    return result


@lru_cache(maxsize=128)
def query_embedding(text):
    return embed([text])[0]


def index_documents(queryset, batch_size=8):
    now = timezone.now()
    docs = list(queryset.filter(Q(embedding__isnull=True) | ~Q(model=MODEL_ID))
        .filter(Q(retry_at=None) | Q(retry_at__lte=now)).only('id','text','fingerprint').order_by('pk')[:batch_size])
    if not docs:return 0
    try:vectors = embed([doc.text for doc in docs], 'document')
    except EmbeddingUnavailable:
        queryset.filter(pk__in=[doc.pk for doc in docs]).update(retry_at=now + timedelta(seconds=60))
        raise
    for doc, vector in zip(docs, vectors):
        queryset.filter(pk=doc.pk,fingerprint=doc.fingerprint).update(
            embedding=vector,model=MODEL_ID,retry_at=None,indexed_at=timezone.now())
    return len(docs)


def index_batch(batch_size=8):
    return index_documents(ProblemSearchDocument.objects.filter(problem__published=True).exclude(text=''),batch_size)


def selected_fields(field):
    return set(field) if isinstance(field,(list,set,tuple)) else ({'statement','solution','metadata'} if field=='all' else {field})


def allowed_documents(user, problems, field):
    fields=selected_fields(field)
    docs = ProblemSearchDocument.objects.filter(problem__in=problems, problem__published=True)
    visible=Q(kind__in=fields-{'solution'})
    if 'solution' in fields:
        visible |= Q(kind='solution',problem__in=s.solutions_for(user,problems))
    return docs.filter(visible).exclude(text='')


def document_fields(docs,*extra):
    identity='problem_id' if docs.model is ProblemSearchDocument else 'object_id'
    return ['id',identity,'kind','text',*extra]


def grams(value):
    return {value[index:index + 3] for index in range(max(0, len(value) - 2))}


def lexical_candidates(docs, text, limit=120):
    query = normalized(text)
    folded = query.casefold()
    exact = []
    for doc in docs.filter(normalized__contains=folded).only(*document_fields(docs))[:limit]:
        exact.append((doc, 1. if normalized(doc.text) == query else .95, 'exact' if normalized(doc.text) == query else 'text'))
    if connection.vendor == 'postgresql':
        from django.contrib.postgres.search import TrigramSimilarity
        candidates = docs.only(*document_fields(docs)).annotate(lexical_score=TrigramSimilarity('normalized', folded)).filter(lexical_score__gte=.08).order_by('-lexical_score')[:limit]
        return exact + [(doc, float(doc.lexical_score), 'text') for doc in candidates]
    # Local SQLite demo: streamed fuzzy scan, bounded result memory.
    query_grams = grams(folded)
    heap = []
    if not query_grams:
        return exact
    for doc in docs.only(*document_fields(docs,'normalized')).iterator(chunk_size=256):
        other = grams(doc.normalized)
        score = 2 * len(query_grams & other) / max(1, len(query_grams) + len(other))
        if score >= .15:
            item = (score, doc.pk, doc)
            heapq.heappush(heap, item)
            if len(heap) > limit:
                heapq.heappop(heap)
    return exact + [(doc, score, 'text') for score, _, doc in sorted(heap, reverse=True)]


def vector_candidates(docs, vector, limit=120):
    docs = docs.filter(model=MODEL_ID, embedding__isnull=False)
    if connection.vendor == 'postgresql':
        # Continue HNSW scans after permission/topic filters instead of returning too few candidates.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            return [(doc, 1 - float(doc.distance)) for doc in docs.only(*document_fields(docs)).annotate(distance=CosineDistance('embedding', vector))
                    .order_by('distance')[:limit]]
    # SQLite has no vector operators. Evaluate blocks on CPU without retaining the full bank.
    heap, batch = [], []
    def consume(rows):
        scores = np.asarray([doc.embedding for doc in rows], dtype=np.float32) @ vector
        for doc, score in zip(rows, scores):
            item = (float(score), doc.pk, doc)
            heapq.heappush(heap, item)
            if len(heap) > limit:
                heapq.heappop(heap)
    for doc in docs.only(*document_fields(docs,'embedding')).iterator(chunk_size=256):
        batch.append(doc)
        if len(batch) == 256:
            consume(batch); batch = []
    if batch:
        consume(batch)
    return [(doc, score) for score, _, doc in sorted(heap, reverse=True)]


def rank_documents(docs,text,limit=20,semantic=True):
    pending = docs.filter(Q(embedding__isnull=True) | ~Q(model=MODEL_ID)).count()
    matches = {}
    def add(doc, strength, kind, source, rank):
        value = matches.setdefault(doc.problem_id if isinstance(doc,ProblemSearchDocument) else doc.object_id, {'score':0., 'kind':kind, 'fields':set(), 'excerpt':'', 'lexical':0., 'vector':0., 'exact':False, 'best':-1.})
        value['fields'].add(doc.kind)
        # Reciprocal rank fusion: a weak text match cannot systematically bury
        # every semantic result; multiple sections do not double-count one task.
        value[source] = max(value[source], (2. if source == 'vector' else 1.) / (60 + rank))
        value['exact'] |= kind == 'exact'
        value['score'] = value['lexical'] + value['vector'] + (1. if value['exact'] else 0.)
        priority = 2. if kind == 'exact' else strength
        if priority > value['best']:
            value.update(best=priority, kind=kind, excerpt=doc.text[:500])
    for rank, (doc, score, kind) in enumerate(lexical_candidates(docs, text), 1):
        add(doc, score, kind, 'lexical', rank)
    available = False
    if semantic and docs.filter(model=MODEL_ID, embedding__isnull=False).exists():
        try:
            vector = query_embedding(text)
            for rank, (doc, score) in enumerate(vector_candidates(docs, vector), 1):
                if score >= .73:
                    add(doc, score, 'semantic', 'vector', rank)
            available = True
        except EmbeddingUnavailable:
            pass
    ranked = sorted(matches.items(), key=lambda item: (-item[1]['score'], str(item[0])))[:limit]
    notice = '' if available or not semantic else 'Семантический поиск пока недоступен. Показаны совпадения по тексту.'
    if pending:
        notice += (' ' if notice else '') + 'Часть доступных материалов ещё индексируется.'
    return ranked, {'semantic': available, 'pending': pending, 'notice': notice}


def retrieve(user,problems,text,field='all',limit=20,semantic=True):
    ranked,metadata=rank_documents(allowed_documents(user,problems,field),text,limit,semantic)
    matches=dict(ranked)
    if 'statement' in selected_fields(field) and len(text) <= 160:
        # Preserve title, source-number and UUID search as additional candidates.
        for pk,statement in s.search_problems(problems, text).exclude(pk__in=matches).values_list('pk','statement')[:limit]:
            matches[pk] = {'score':.01, 'kind':'text', 'fields':set(), 'excerpt':statement[:500]}
    return sorted(matches.items(),key=lambda item:(-item[1]['score'],str(item[0])))[:limit],metadata
