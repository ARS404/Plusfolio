import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ValidationError
from core.models import User
from core.problem_import import import_sample

class Command(BaseCommand):
    help='Импорт проверенной подборки problems.ru без дублей и перезаписи опубликованных задач.'
    def add_arguments(self,parser):
        parser.add_argument('path',type=Path)
        parser.add_argument('--author',required=True,help='Email администратора, выполняющего импорт')
        parser.add_argument('--dry-run',action='store_true')
        parser.add_argument('--topics',type=Path,default=settings.BASE_DIR/'data/problems_topics.json')
    def handle(self,*args,**options):
        user=User.objects.filter(email=options['author'].strip().lower(),is_active=True).first()
        if not user or 'admin' not in user.roles:raise CommandError('Нужен действующий аккаунт администратора.')
        try:
            result=import_sample(user,json.loads(options['path'].read_text()),json.loads(options['topics'].read_text()),dry_run=options['dry_run'])
        except (ValidationError,ValueError,KeyError,TypeError) as error:raise CommandError('Импорт отклонён: '+' '.join(error.messages) if isinstance(error,ValidationError) else 'Некорректный формат подборки.') from None
        self.stdout.write(('Проверка без записи. ' if result['dry_run'] else '')+f'Задач добавлено: {result["created"]}; уже были: {result["skipped"]}; новых тем: {result["topics_created"]}.')
