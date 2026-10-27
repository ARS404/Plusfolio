from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand
from core.backup import create_bundle

class Command(BaseCommand):
    help='Создать зашифрованный полный комплект локальной демки.'
    def add_arguments(self,parser):parser.add_argument('--output')
    def handle(self,*args,**options):
        path=options['output'] or settings.LOCAL_DIR/'backups'/f'plusfolio-{datetime.now():%Y%m%d-%H%M%S}.pfb'
        manifest=create_bundle(path)
        self.stdout.write(f'Копия: {path}; файлов: {len(manifest["files"])}. Сохраните .local/backup.key отдельно от копии; значение ключа не выводится.')
