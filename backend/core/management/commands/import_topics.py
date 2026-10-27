import json,uuid
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from core.models import Topic
from core.services import snapshot_topics

def topic_uuid(value):return uuid.uuid5(uuid.NAMESPACE_URL,'plusfolio-topic:'+str(value))
class Command(BaseCommand):
    help='Импорт общедоступной структуры тем problems.ru, без задач и решений.'
    def add_arguments(self,parser):parser.add_argument('path')
    @transaction.atomic
    def handle(self,*args,**options):
        data=json.loads(Path(options['path']).read_text())
        if data.get('conflicts'):raise CommandError('Сначала разрешите конфликты исходной иерархии.')
        pending=list(data['normalized_nodes']);created=0
        while pending:
            progress=False
            for item in list(pending):
                parent_id=topic_uuid(item['parent_id']) if item['parent_id'] else None
                if parent_id and not Topic.objects.filter(pk=parent_id).exists():continue
                _,new=Topic.objects.get_or_create(pk=topic_uuid(item['id']),defaults={'name':item['name'],'parent_id':parent_id,'source_id':item.get('source_id') or '', 'is_other':item['is_other'],'sort_order':item.get('sort_order',0)})
                created+=new;pending.remove(item);progress=True
            if not progress:raise CommandError('Не найден родитель или обнаружен цикл.')
        snapshot_topics()
        self.stdout.write(f'Тем: {Topic.objects.count()}; добавлено: {created}; полный источник: {data["metadata"]["complete"]}')
