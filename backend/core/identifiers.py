"""Typed, stable IDs for people and catalogue entities. Permissions stay with callers."""
import re
from uuid import UUID
from django.core.exceptions import ValidationError
from django.db.models import Q

PREFIXES={'user':'U','student':'S','teacher':'T','circle':'C','problem':'P',
          'worksheet':'W','topic':'TOP','tag':'TAG','invitation':'INV','issue':'ISS'}
KINDS={prefix:kind for kind,prefix in PREFIXES.items()}
MAX_NUMBER=2**63-1


def public_id(kind,number):
    return f'{PREFIXES[kind]}-{number}' if number is not None else None


def typed_id(text):
    match=re.fullmatch(r'([a-z]+)\s*-\s*([0-9]+)',text.strip(),re.I)
    if not match or match[1].upper() not in KINDS:return None
    digits=match[2].lstrip('0') or '0'
    if len(digits)>19 or not 1<=int(digits)<=MAX_NUMBER:return KINDS[match[1].upper()],None
    return KINDS[match[1].upper()],int(digits)


def validate_search(text):
    if not isinstance(text,str) or len(text)>160:raise ValidationError('Поисковый запрос — до 160 символов.')
    return text.strip()


def uuid_id(text: str) -> UUID | None:
    try:return UUID(text)
    except ValueError:return None


def search_entities(queryset,text,kind,number_field='number_id',text_fields=(),uuid_fields=('pk',)):
    text=validate_search(text)
    if not text:return queryset
    typed=typed_id(text)
    if typed:
        return queryset.filter(**{number_field:typed[1]}) if typed[0]==kind and typed[1] else queryset.none()
    condition=Q(pk__in=[])
    for field in text_fields:condition|=Q(**{field+'__icontains':text})
    if text.isascii() and text.isdigit() and len(text)<=19 and 0<int(text)<=MAX_NUMBER:
        condition|=Q(**{number_field:int(text)})
    identity=uuid_id(text)
    if identity:
        for field in uuid_fields:condition|=Q(**{field:identity})
    return queryset.filter(condition)


def search_issues(queryset,text):
    text=validate_search(text);typed=typed_id(text)
    if typed and typed[0]=='issue':
        return queryset.filter(pk=typed[1]) if typed[1] else queryset.none()
    return search_entities(queryset,text,'worksheet','worksheet__document__number_id',
                           ('worksheet__title','circle__name'),('worksheet_id','worksheet__document_id'))
