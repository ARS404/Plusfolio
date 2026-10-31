from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as utc
from io import StringIO
from unittest import skipUnless
from unittest.mock import patch
from django.core import mail
from django.core.management import call_command, CommandError
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from . import services as s
from .mail_backend import DailyMailLimit, reserve_mail
from .mail_delivery import deliver_batch
from .models import Circle, EmailOutbox, Invitation, MailBudget, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],DEMO=False,
    EMAIL_BACKEND='core.mail_backend.EmailBackend',EMAIL_HOST='smtp.example.test',EMAIL_USE_SSL=False,
    EMAIL_USE_TLS=False,EMAIL_HOST_USER='',DEFAULT_FROM_EMAIL='robot@example.test',PUBLIC_URL='https://math.example.test')
class MailBudgetTests(TransactionTestCase):
    def setUp(self):
        self.now=datetime(2026,10,31,20,59,tzinfo=utc.utc)
        clock=patch('core.mail_backend.timezone.now',return_value=self.now)
        self.clock=clock.start();self.addCleanup(clock.stop)
        smtp=patch('django.core.mail.backends.smtp.smtplib.SMTP')
        self.smtp=smtp.start();self.addCleanup(smtp.stop)
        self.smtp.return_value.sendmail.return_value={}
        self.budget,_=MailBudget.objects.update_or_create(pk=1,defaults={'day':self.now.date(),'used':0,'daily_limit':100})
        self.admin=User.objects.create_superuser('admin@example.test','TestPassword2026!',name='Test admin')
        self.circle=Circle.objects.create(name='Mail test',created_by=self.admin)

    def send(self,subject='Test',recipients=None):
        return mail.send_mail(subject,'Body','robot@example.test',recipients or ['student@example.test'])

    def test_all_mail_types_and_recipients_share_one_budget(self):
        self.assertEqual(self.send('Invitation'),1)
        self.assertEqual(self.send('Password reset'),1)
        message=mail.EmailMessage('Other','Body','robot@example.test',['to@example.test'],cc=['cc@example.test'],bcc=['bcc@example.test'])
        self.assertEqual(message.send(),1)
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,5)
        self.budget.used=99;self.budget.save(update_fields=['used'])
        with self.assertRaises(DailyMailLimit):self.send(recipients=['one@example.test','two@example.test'])
        self.assertEqual(self.send(),1)
        with self.assertRaises(DailyMailLimit):self.send()
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,100)
        self.assertEqual(self.smtp.return_value.sendmail.call_count,4)

    def test_failed_smtp_attempt_still_consumes_capacity(self):
        self.smtp.return_value.sendmail.side_effect=OSError('private provider text')
        with self.assertRaises(OSError):self.send()
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,1)

    def test_runtime_limit_changes_preserve_usage_and_need_no_restart(self):
        self.send()
        call_command('mail_limit',limit=1,stdout=StringIO())
        with self.assertRaises(DailyMailLimit):self.send()
        call_command('mail_limit',limit=2,stdout=StringIO())
        self.send()
        call_command('mail_limit',limit=0,stdout=StringIO())
        with self.assertRaises(DailyMailLimit):self.send()
        with self.assertRaises(CommandError):call_command('mail_limit',limit=-1,stdout=StringIO())
        self.budget.refresh_from_db();self.assertEqual((self.budget.daily_limit,self.budget.used),(0,2))

    def test_moscow_midnight_resets_usage_independent_of_request_timezone(self):
        self.budget.used=100;self.budget.save(update_fields=['used'])
        with self.assertRaises(DailyMailLimit):self.send()
        self.clock.return_value=self.now+timedelta(minutes=1)
        with timezone.override('America/New_York'):self.send()
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.day.isoformat(),'2026-11-01');self.assertEqual(self.budget.used,1)

    def test_smtp_inside_rollbackable_transaction_is_rejected_before_network(self):
        with transaction.atomic(),self.assertRaises(RuntimeError):self.send()
        self.assertFalse(self.smtp.called)
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,0)

    def test_over_limit_invite_returns_notice_and_creates_no_outbox_or_invitation(self):
        self.budget.used=99;self.budget.save(update_fields=['used'])
        first=s.invite(self.admin,'first@example.test','student',self.circle)
        client=APIClient();client.force_authenticate(self.admin)
        result=client.post('/api/invitations',{'email':'second@example.test','role':'student','circle_ids':[str(self.circle.pk)]},format='json')
        self.assertEqual(result.status_code,429);self.assertIn('Сегодня письма',str(result.data['detail']))
        self.assertEqual(Invitation.objects.count(),1);self.assertEqual(EmailOutbox.objects.count(),1)
        self.assertEqual(deliver_batch(),1)
        self.assertEqual(EmailOutbox.objects.get(invitation=first).state,'sent')
        self.assertEqual(self.smtp.return_value.sendmail.call_count,1)

    def test_reduced_limit_discards_queued_letters_without_rescheduling(self):
        invitation=s.invite(self.admin,'queued@example.test','student',self.circle)
        call_command('mail_limit',limit=0,stdout=StringIO())
        self.assertEqual(deliver_batch(),1)
        letter=EmailOutbox.objects.get(invitation=invitation)
        self.assertEqual((letter.state,letter.error_code,letter.attempts),('cancelled','daily_limit',0))
        self.assertIsNone(letter.next_attempt_at);self.assertIsNone(letter.locked_until)
        self.clock.return_value=self.now+timedelta(days=1)
        call_command('mail_limit',limit=100,stdout=StringIO())
        self.assertEqual(deliver_batch(),0);self.assertFalse(self.smtp.called)

    def test_batch_invitation_request_rolls_back_when_only_one_slot_remains(self):
        self.budget.used=99;self.budget.save(update_fields=['used'])
        other=Circle.objects.create(name='Second circle',created_by=self.admin)
        client=APIClient();client.force_authenticate(self.admin)
        result=client.post('/api/invitations',{'email':'batch@example.test','role':'student',
            'circle_ids':[str(self.circle.pk),str(other.pk)]},format='json')
        self.assertEqual(result.status_code,429)
        self.assertFalse(Invitation.objects.exists());self.assertFalse(EmailOutbox.objects.exists())

    def test_pending_invitation_reserves_capacity_against_other_outgoing_mail(self):
        self.budget.daily_limit=1;self.budget.save(update_fields=['daily_limit'])
        s.invite(self.admin,'reserved@example.test','student',self.circle)
        with self.assertRaises(DailyMailLimit):self.send('Other mail')
        self.assertFalse(self.smtp.called)
        self.assertEqual(deliver_batch(),1)
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,1)

    def test_expired_and_revoked_invites_free_pending_capacity_without_sending(self):
        self.budget.daily_limit=1;self.budget.save(update_fields=['daily_limit'])
        expired=s.invite(self.admin,'expired@example.test','student',self.circle)
        Invitation.objects.filter(pk=expired.pk).update(expires_at=self.now-timedelta(seconds=1))
        revoked=s.invite(self.admin,'revoked@example.test','student',self.circle)
        Invitation.objects.filter(pk=revoked.pk).update(state='revoked')
        s.invite(self.admin,'active@example.test','student',self.circle)
        self.assertEqual(deliver_batch(),3)
        self.assertEqual(EmailOutbox.objects.filter(state='cancelled').count(),2)
        self.assertEqual(self.smtp.return_value.sendmail.call_count,1)
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,1)

    def test_resend_reuses_pending_capacity_and_blocked_resend_keeps_old_invite(self):
        call_command('mail_limit',limit=1,stdout=StringIO())
        first=s.invite(self.admin,'same@example.test','student',self.circle)
        second=s.invite(self.admin,'same@example.test','student',self.circle)
        first.refresh_from_db();self.assertEqual(first.state,'revoked')
        call_command('mail_limit',limit=0,stdout=StringIO())
        with self.assertRaises(DailyMailLimit):s.invite(self.admin,'same@example.test','student',self.circle)
        second.refresh_from_db();self.assertEqual(second.state,'pending')

    @skipUnless(connection.vendor=='postgresql','Cross-worker PostgreSQL row locks')
    def test_concurrent_senders_cannot_exceed_the_global_budget(self):
        def reserve(index):
            try:
                reserve_mail(1)
                return True
            except DailyMailLimit:return False
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=6) as workers:accepted=list(workers.map(reserve,range(120)))
        self.assertEqual(sum(accepted),100)
        self.budget.refresh_from_db();self.assertEqual(self.budget.used,100)

    @skipUnless(connection.vendor=='postgresql','Cross-worker PostgreSQL row locks')
    def test_concurrent_invite_requests_cannot_overfill_the_outbox(self):
        def invite(index):
            try:
                s.invite(self.admin,f'concurrent{index}@example.test','student',self.circle)
                return True
            except DailyMailLimit:return False
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=6) as workers:accepted=list(workers.map(invite,range(120)))
        self.assertEqual(sum(accepted),100);self.assertEqual(EmailOutbox.objects.count(),100)


class MailBudgetMigrationTests(TransactionTestCase):
    def test_existing_confirmed_sends_are_counted_using_moscow_day(self):
        executor=MigrationExecutor(connection);latest=executor.loader.graph.leaf_nodes()
        previous=[('core','0015_student_name_parts')]
        now=datetime(2026,11,1,9,tzinfo=utc.utc);start=datetime(2026,10,31,21,tzinfo=utc.utc)
        try:
            executor.migrate(previous);apps=executor.loader.project_state(previous).apps
            admin=apps.get_model('core','User').objects.create(email='legacy-mail@example.test',name='Legacy',roles=['admin'],password='!')
            number=apps.get_model('core','InvitationNumber').objects.create()
            invitation=apps.get_model('core','Invitation').objects.create(number=number,email='legacy@example.test',role='student',created_by=admin,token_hash='legacy',expires_at=now+timedelta(days=7))
            outbox=apps.get_model('core','EmailOutbox')
            for moment in [start-timedelta(seconds=1),start,now,start+timedelta(days=1)]:
                outbox.objects.create(invitation=invitation,encrypted_payload='legacy',state='sent',sent_at=moment)
            outbox.objects.create(invitation=invitation,encrypted_payload='legacy',state='queued',sent_at=now)
            with patch('django.utils.timezone.now',return_value=now):MigrationExecutor(connection).migrate([('core','0016_mail_budget')])
            budget=MailBudget.objects.get(pk=1)
            self.assertEqual((budget.day.isoformat(),budget.used,budget.daily_limit),('2026-11-01',2,100))
        finally:MigrationExecutor(connection).migrate(latest)
