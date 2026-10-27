"""Invitation outbox: short leases, bounded retry, and no recipient/token logging."""
import hashlib,json,smtplib
from email.utils import parseaddr
from datetime import timedelta
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import EmailOutbox
from . import services as s

MAX_ATTEMPTS=8


def deliver_batch(limit=10):
    if settings.DEMO:return 0
    if not settings.EMAIL_HOST or not settings.DEFAULT_FROM_EMAIL:raise RuntimeError('SMTP is not configured')
    done=0
    for _ in range(limit):
        now=timezone.now()
        with transaction.atomic():
            letter=EmailOutbox.objects.select_for_update(skip_locked=True).filter(state__in=['queued','retry'])\
                .filter(Q(next_attempt_at=None)|Q(next_attempt_at__lte=now))\
                .filter(Q(locked_until=None)|Q(locked_until__lte=now)).order_by('pk').first()
            if not letter:break
            letter.locked_until=now+timedelta(minutes=2);letter.attempts+=1;letter.save(update_fields=['locked_until','attempts'])
        state='sent';error=''
        try:
            payload=json.loads(s.cipher().decrypt(letter.encrypted_payload.encode()))
            invitation=s.valid_invitation(payload['token'])
            if invitation.pk!=letter.invitation_id or hashlib.sha256(payload['token'].encode()).hexdigest()!=invitation.token_hash:
                raise ValueError('Payload does not match invitation')
            url=settings.PUBLIC_URL+'/#/accept/'+payload['token']
            circle='Кружок: '+payload['circle']+'\n' if payload.get('circle') else ''
            text='Вас пригласили в Plusfolio.\n'+circle+'\nПринять приглашение: '+url+'\n\nСсылка действует до '+invitation.expires_at.strftime('%d.%m.%Y %H:%M UTC')+'. Если вы не ожидали письмо, просто проигнорируйте его.'
            message=EmailMultiAlternatives(payload['subject'],text,settings.DEFAULT_FROM_EMAIL,[payload['to']],
                headers={'Message-ID':f'<invitation-{letter.pk}@{parseaddr(settings.DEFAULT_FROM_EMAIL)[1].rsplit("@",1)[-1]}>',
                         'Auto-Submitted':'auto-generated'})
            if message.send(fail_silently=False)!=1:raise OSError('SMTP did not accept message')
        except (s.NotFound,s.PermissionDenied,ValueError,KeyError):state='cancelled';error='invalid_invitation'
        except Exception as exc:
            # Errors never contain provider text, addresses, credentials or message bodies.
            from django.core.exceptions import ValidationError
            if isinstance(exc,ValidationError) or hasattr(exc,'status_code') and exc.status_code in {400,403,404}:
                state='cancelled';error='invitation_unavailable'
            else:
                state='failed' if letter.attempts>=MAX_ATTEMPTS else 'retry'
                permanent=(isinstance(exc,smtplib.SMTPResponseException) and exc.smtp_code>=500) or (isinstance(exc,smtplib.SMTPRecipientsRefused) and bool(exc.recipients) and all(code>=500 for code,_ in exc.recipients.values()))
                error='smtp_permanent' if permanent else 'smtp_unavailable'
                if error=='smtp_permanent':state='failed'
        updates={'state':state,'locked_until':None,'error_code':error,
            'next_attempt_at':now+timedelta(seconds=min(3600,30*2**(letter.attempts-1))) if state=='retry' else None,
            'sent_at':timezone.now() if state=='sent' else None}
        EmailOutbox.objects.filter(pk=letter.pk,locked_until=letter.locked_until).update(**updates)
        done+=1
    return done
