"""Shared read filters; apply them only after permission scoping."""
from django.core.exceptions import ValidationError
from django.db.models.functions import Trim
from uuid import UUID
from .models import Tag


def query_values(params, key):
    """Keep repeated query parameters; scalar parameters remain backward compatible."""
    return params.getlist(key) if hasattr(params, 'getlist') else params.get(key)


def id_values(raw):
    if not raw:
        return None
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    return {part.strip() for value in values for part in str(value).split(',')}


def uuid_ids(raw):
    values = id_values(raw)
    if values is None:
        return None
    try:
        return {str(UUID(value)) for value in values}
    except (TypeError, ValueError, AttributeError):
        raise ValidationError('Некорректный список идентификаторов.')


def tag_ids(raw, kind):
    if not raw:
        return None
    try:
        ids = {int(value) for value in id_values(raw)}
    except (AttributeError, TypeError, ValueError):
        raise ValidationError('Некорректный фильтр тегов.')
    if not ids or any(value <= 0 for value in ids) or Tag.objects.filter(pk__in=ids, kind=kind).count() != len(ids):
        raise ValidationError('Выберите теги нужного типа.')
    return ids


def by_city(queryset, raw, field='city'):
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    cities = {str(value).strip() for value in values if value and str(value).strip()}
    return queryset.alias(_filter_city=Trim(field)).filter(_filter_city__in=cities) if cities else queryset


def by_tags(queryset, raw, kind, field='tags'):
    ids = tag_ids(raw, kind)
    return queryset.filter(**{field+'__pk__in': ids}).distinct() if ids is not None else queryset
