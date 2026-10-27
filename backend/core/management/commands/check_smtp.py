from django.core.mail import get_connection
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings

class Command(BaseCommand):
    help='Verify SMTP connectivity, TLS and credentials without sending a message.'
    def handle(self,**options):
        if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:raise CommandError('SMTP is not configured')
        try:
            connection=get_connection();connection.open();connection.close()
        except Exception as exc:raise CommandError('SMTP check failed: '+type(exc).__name__)
        self.stdout.write('SMTP connection and credentials verified; no message was sent.')
