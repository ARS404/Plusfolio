import time
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.core.cache import cache
from core.search import reconcile_missing, index_batch, EmbeddingUnavailable, MODEL_ID
from core.models import ProblemSearchDocument, CatalogueSearchDocument
from core import catalogue_search
from django.db.models import Q


class Command(BaseCommand):
    help = 'Build/resume the derived problem index using the private CPU model service.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')
        parser.add_argument('--rebuild', action='store_true',help='Reconcile all source texts after bulk edits.')

    def handle(self, **options):
        total = 0
        rebuild=options['rebuild']
        while True:
            close_old_connections()
            cache.set('worker:index',int(time.time()),60)
            reconcile_missing(rebuild)
            catalogue_search.reconcile(rebuild)
            rebuild=False
            try:
                count = index_batch() + catalogue_search.index_batch()
                total += count
            except EmbeddingUnavailable:
                if not options['watch']:
                    raise CommandError('CPU-модель недоступна. Запустите scripts/run_search.sh и повторите индексацию.')
                time.sleep(10)
                continue
            if count:
                self.stdout.write(f'Indexed documents: {total}')
            elif options['watch']:
                time.sleep(10)
            else:
                if any(model.objects.exclude(text='').filter(Q(embedding__isnull=True)|~Q(model=MODEL_ID)).exists() for model in [ProblemSearchDocument,CatalogueSearchDocument]):
                    raise CommandError('Часть документов ожидает повторной попытки. Повторите через минуту или используйте --watch.')
                self.stdout.write(f'Index ready. Processed documents: {total}')
                break
