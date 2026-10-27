import os
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.core.management import call_command
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from core.models import User,Topic

class Command(BaseCommand):
    help='Idempotent server initialization without demo accounts or automatic password resets.'
    def handle(self,**options):
        if settings.DEMO:raise CommandError('Server initialization requires PLUSFOLIO_DEMO=0')
        email=os.environ.get('BOOTSTRAP_ADMIN_EMAIL','').strip().lower()
        if not email:raise CommandError('BOOTSTRAP_ADMIN_EMAIL is required')
        from django.core.validators import validate_email
        validate_email(email)
        with transaction.atomic():
            if User.objects.exists():
                if not User.objects.filter(is_active=True,roles__contains=['admin']).exists():
                    raise CommandError('No active administrator; restore operator access explicitly before starting')
            else:
                password=Path(os.environ['BOOTSTRAP_ADMIN_PASSWORD_FILE']).read_text().strip()
                validate_password(password)
                User.objects.create_superuser(email,password,name=os.environ.get('BOOTSTRAP_ADMIN_NAME','Администратор'))
        if not Topic.objects.exists():call_command('import_topics',str(settings.BASE_DIR/'data/problems_topics.json'))
        self.stdout.write('Server initialized; demo accounts were not created.')
