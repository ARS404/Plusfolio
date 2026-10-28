import time
from django.core.cache import cache
from django.core.management.base import BaseCommand,CommandError
from django.db import close_old_connections
from core.mail_delivery import deliver_batch

class Command(BaseCommand):
    help='Send queued invitations via configured SMTP, with leases and bounded retries.'
    def add_arguments(self,parser):parser.add_argument('--watch',action='store_true')
    def handle(self,**options):
        while True:
            close_old_connections()
            try:count=deliver_batch()
            except RuntimeError as exc:raise CommandError(str(exc))
            cache.set('worker:mail',int(time.time()),60)
            if not options['watch']:self.stdout.write(f'Processed invitations: {count}');return
            if not count:time.sleep(5)
