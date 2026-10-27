import json
import platform
import statistics
import time
from pathlib import Path
from urllib.request import urlopen
from django.conf import settings
from django.core.management.base import BaseCommand
from rest_framework.test import APIClient
from core.models import Problem, ProblemSearchDocument, User
from core.search import embed, MODEL_ID, query_embedding, allowed_documents, vector_candidates
from core import services as s


class Command(BaseCommand):
    help = 'Measure real CPU inference, hybrid API latency and retrieval on the local demo corpus.'

    def add_arguments(self, parser):
        parser.add_argument('--encode-corpus', action='store_true')
        parser.add_argument('--output', default=str(settings.LOCAL_DIR/'search-benchmark.json'))

    def handle(self, **options):
        user=next(user for user in User.objects.all() if 'teacher' in user.roles)
        client=APIClient();client.force_authenticate(user=user)
        fixture=json.loads((settings.BASE_DIR/'embeddings/evaluation.json').read_text())
        results=[];timings=[]
        for item in fixture:
            query_embedding.cache_clear()
            start=time.perf_counter()
            reply=client.post('/api/problem-search',{'q':item['query'],'field':'statement'},format='json')
            elapsed=time.perf_counter()-start
            if reply.status_code!=200 or not reply.data['semantic']:raise RuntimeError('Real semantic API unavailable')
            ids=[hit['problem']['source_id'] for hit in reply.data['results']]
            pure=[str(doc.problem_id) for doc,_ in vector_candidates(allowed_documents(user,s.problems_for(user),'statement'),query_embedding(item['query']))]
            expected=str(Problem.objects.get(source='problems.ru',source_id=item['source_id']).pk)
            results.append({'source_id':item['source_id'],'hybrid_rank':ids.index(item['source_id'])+1 if item['source_id'] in ids else None,
                'vector_document_rank':pure.index(expected)+1 if expected in pure else None,'milliseconds':round(elapsed*1000,1)})
            timings.append(elapsed*1000)
        exact=0
        for problem in Problem.objects.filter(source='problems.ru').order_by('number_id')[:20]:
            reply=client.post('/api/problem-search',{'q':' '.join(problem.statement.split()),'field':'statement'},format='json')
            exact+=bool(reply.data['results'] and reply.data['results'][0]['problem']['id']==str(problem.pk))
        from django.db.models.functions import Length
        solution_found=0;solution_tested=0
        for problem in Problem.objects.filter(source='problems.ru').annotate(size=Length('solution')).filter(size__gte=30).order_by('number_id')[:10]:
            reply=client.post('/api/problem-search',{'q':problem.solution,'field':'solution'},format='json')
            solution_tested+=1
            solution_found+=any(hit['problem']['id']==str(problem.pk) for hit in reply.data['results'])
        throughput=None
        if options['encode_corpus']:
            start=time.perf_counter();count=0;batch=[]
            for text in ProblemSearchDocument.objects.exclude(text='').values_list('text',flat=True).iterator(chunk_size=128):
                batch.append(text)
                if len(batch)==8:
                    embed(batch,'document');count+=len(batch);batch=[]
            if batch:embed(batch,'document');count+=len(batch)
            throughput={'documents':count,'seconds':round(time.perf_counter()-start,2)}
        with urlopen(settings.EMBEDDING_URL+'/health',timeout=3) as response:health=json.load(response)
        report={'model':MODEL_ID,'hardware':platform.machine(),'problems':Problem.objects.filter(published=True).count(),
            'indexed_documents':ProblemSearchDocument.objects.filter(model=MODEL_ID).count(),'exact_top1':f'{exact}/20','solution_in_top20':f'{solution_found}/{solution_tested}',
            'paraphrases':results,'api_median_ms':round(statistics.median(timings),1),'api_max_ms':round(max(timings),1),
            'corpus_inference':throughput,'model_health':health,
            'limitations':'Small manually authored smoke set; local CPU, warm model, SQLite, single sequential caller. Not a production SLA or unbiased recall benchmark.'}
        Path(options['output']).write_text(json.dumps(report,ensure_ascii=False,indent=2))
        self.stdout.write(json.dumps(report,ensure_ascii=False,indent=2))
