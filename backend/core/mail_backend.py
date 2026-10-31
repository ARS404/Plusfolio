"""One database budget for all SMTP mail, including queued invitations."""
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled
from .models import EmailOutbox, MailBudget


class DailyMailLimit(Throttled):
    default_detail='Сегодня письма отправлять уже нельзя: общий суточный лимит исчерпан.'


def locked_budget():
    """Call inside the transaction that checks and consumes capacity."""
    budget,_=MailBudget.objects.select_for_update().get_or_create(pk=1)
    day=timezone.localdate(timezone=ZoneInfo(settings.TIME_ZONE))
    if budget.day!=day:
        budget.day=day;budget.used=0;budget.save(update_fields=['day','used'])
    return budget


def pending_count():
    return EmailOutbox.objects.filter(state__in=['queued','retry'],invitation__state='pending',
                                     invitation__expires_at__gt=timezone.now()).count()


def check_capacity(budget,count,*,outbox=False):
    if budget.used+count+(0 if outbox else pending_count())>budget.daily_limit:
        raise DailyMailLimit()


def check_invitation_capacity():
    # The caller's invite transaction holds this lock until its outbox row exists.
    check_capacity(locked_budget(),1)


def reserve_mail(count,*,outbox=False):
    if not transaction.get_autocommit():
        raise RuntimeError('Отправляйте почту вне транзакции: через outbox или после commit.')
    with transaction.atomic():
        budget=locked_budget()
        check_capacity(budget,count,outbox=outbox)
        budget.used+=count;budget.save(update_fields=['used'])


class EmailBackend(SMTPBackend):
    def __init__(self,*args,outbox=False,**kwargs):
        super().__init__(*args,**kwargs)
        self.outbox=outbox

    def send_messages(self,email_messages):
        messages=list(email_messages or [])
        count=sum(len(message.recipients()) for message in messages)
        if not count:return 0
        # Commit before SMTP; uncertain/failed sends retain their consumed budget.
        reserve_mail(count,outbox=self.outbox)
        return super().send_messages(messages)
