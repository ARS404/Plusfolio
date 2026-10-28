import smtplib
from unittest.mock import patch
from datetime import timedelta
from django.test import TestCase,override_settings
from django.core import mail
from django.utils import timezone
from .models import User,Circle,EmailOutbox
from . import services as s
from .mail_delivery import deliver_batch

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    EMAIL_HOST='smtp-test',DEFAULT_FROM_EMAIL='robot@example.test',PUBLIC_URL='https://math.example.test')
class InvitationDeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=User.objects.create_superuser('admin@example.test','Synthetic-pass-2040!',name='Admin')
        cls.circle=Circle.objects.create(name='Test circle',created_by=cls.admin)
    def invite(self):
        invitation=s.invite(self.admin,'student@example.test','student',self.circle)
        return invitation,EmailOutbox.objects.get(invitation=invitation)
    @override_settings(DEMO=False)
    def test_delivery_has_public_https_link_and_is_idempotent(self):
        invitation,letter=self.invite();self.assertEqual(deliver_batch(),1);letter.refresh_from_db()
        self.assertEqual(letter.state,'sent');self.assertEqual(len(mail.outbox),1)
        self.assertIn('https://math.example.test/#/accept/',mail.outbox[0].body)
        self.assertNotIn('127.0.0.1',mail.outbox[0].body)
        self.assertEqual(deliver_batch(),0);self.assertEqual(len(mail.outbox),1)
    @override_settings(DEMO=False)
    @patch('django.core.mail.message.EmailMultiAlternatives.send',side_effect=OSError('private provider response'))
    def test_retry_is_delayed_and_error_is_sanitized(self,send):
        _,letter=self.invite();deliver_batch();letter.refresh_from_db()
        self.assertEqual(letter.state,'retry');self.assertEqual(letter.attempts,1)
        self.assertEqual(letter.error_code,'smtp_unavailable');self.assertGreater(letter.next_attempt_at,timezone.now())
        self.assertEqual(deliver_batch(),0)
    @override_settings(DEMO=False)
    @patch('django.core.mail.message.EmailMultiAlternatives.send',side_effect=smtplib.SMTPRecipientsRefused({'x':(550,b'private')}))
    def test_permanent_failure_is_visible_and_bounded(self,send):
        _,letter=self.invite();deliver_batch();letter.refresh_from_db()
        self.assertEqual(letter.state,'failed');self.assertEqual(letter.error_code,'smtp_permanent')
    @override_settings(DEMO=False)
    @patch('django.core.mail.message.EmailMultiAlternatives.send',side_effect=smtplib.SMTPRecipientsRefused({'x':(450,b'temporarily unavailable')}))
    def test_temporary_recipient_rejection_is_retried(self,send):
        _,letter=self.invite();deliver_batch();letter.refresh_from_db()
        self.assertEqual(letter.state,'retry');self.assertEqual(letter.error_code,'smtp_unavailable')
        self.assertGreater(letter.next_attempt_at,timezone.now())
    @override_settings(DEMO=False)
    def test_revoked_expired_and_permission_revoked_invites_are_not_sent(self):
        invitation,letter=self.invite();invitation.state='revoked';invitation.save()
        deliver_batch();letter.refresh_from_db();self.assertEqual(letter.state,'cancelled')
        self.assertEqual(len(mail.outbox),0)
    @override_settings(DEMO=True)
    def test_demo_never_sends_real_mail(self):
        _,letter=self.invite();self.assertEqual(deliver_batch(),0);letter.refresh_from_db();self.assertEqual(letter.state,'queued')
    @override_settings(DEMO=False)
    def test_another_workers_active_lease_is_not_stolen(self):
        _,letter=self.invite();letter.locked_until=timezone.now()+timedelta(minutes=1);letter.save()
        self.assertEqual(deliver_batch(),0)


class ProxyAddressTests(TestCase):
    def test_proxy_rate_limit_uses_last_valid_address_only(self):
        from django.test import RequestFactory
        from .proxy import ClientIPMiddleware
        middleware=ClientIPMiddleware(lambda request:request.META['REMOTE_ADDR'])
        factory=RequestFactory()
        with override_settings(TRUST_PROXY_CLIENT_IP=True):
            self.assertEqual(middleware(factory.get('/',REMOTE_ADDR='172.18.0.2',HTTP_X_FORWARDED_FOR='1.2.3.4, 2001:db8::2')),'2001:db8::2')
            self.assertEqual(middleware(factory.get('/',REMOTE_ADDR='172.18.0.2',HTTP_X_FORWARDED_FOR='invalid')),'172.18.0.2')
        with override_settings(TRUST_PROXY_CLIENT_IP=False):
            self.assertEqual(middleware(factory.get('/',REMOTE_ADDR='127.0.0.1',HTTP_X_FORWARDED_FOR='1.2.3.4')),'127.0.0.1')
