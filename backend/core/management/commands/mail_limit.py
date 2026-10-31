from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.mail_backend import locked_budget,pending_count


class Command(BaseCommand):
    help='Показать или изменить общий суточный лимит почты без перезапуска.'

    def add_arguments(self,parser):
        parser.add_argument('--set',type=int,dest='limit',help='Новый лимит; 0 останавливает отправку.')

    def handle(self,**options):
        with transaction.atomic():
            budget=locked_budget()
            if options['limit'] is not None:
                budget.daily_limit=options['limit']
                try:budget.full_clean()
                except ValidationError as error:raise CommandError('; '.join(error.messages)) from None
                budget.save(update_fields=['daily_limit'])
            pending=pending_count()
        self.stdout.write(f'Лимит: {budget.daily_limit}; учтено за {budget.day}: {budget.used}; в очереди: {pending}; доступно: {max(0,budget.daily_limit-budget.used-pending)}.')
