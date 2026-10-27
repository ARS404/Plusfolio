from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from core.backup import verify_bundle,restore_bundle

class Command(BaseCommand):
    help='Проверить копию или восстановить её в НОВУЮ изолированную папку, без изменения текущей БД.'
    def add_arguments(self,parser):
        parser.add_argument('archive');parser.add_argument('--key');parser.add_argument('--into')
    def handle(self,*args,**options):
        key=options['key'] or settings.LOCAL_DIR/'backup.key'
        try:
            if options['into']:manifest=restore_bundle(options['archive'],key,options['into'])
            else:manifest,_=verify_bundle(options['archive'],key)
        except Exception as exc:raise CommandError('Не удалось проверить/восстановить копию: '+type(exc).__name__) from None
        self.stdout.write(f'Целостность проверена. Пользователей: {manifest["users"]}; тем: {manifest["topics"]}. '+('Восстановлено в изоляции; сессии отозваны, приглашения отменены.' if options['into'] else 'Текущая база не изменена.'))
