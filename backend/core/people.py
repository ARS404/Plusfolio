"""Student identity validation and portable, Unicode-aware people searches."""
import unicodedata
from collections.abc import Iterable
from django.core.exceptions import ValidationError
from django.db.models import Q


def normalize_name(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value)).casefold().replace('ё','е').split())


def role_query(roles: Iterable[str], prefix: str = '') -> Q:
    from .models import ROLES
    query = Q(pk__in=[])
    for role in roles:
        for index in range(len(ROLES)):
            query |= Q(**{f'{prefix}roles__{index}': role})
    return query


def search_people(queryset,text,prefix='',email=True):
    if not isinstance(text,str) or len(text)>160:raise ValidationError('Поисковый запрос — до 160 символов.')
    from .identifiers import typed_id,MAX_NUMBER
    typed=typed_id(text)
    fields={'user':'pk','student':'student__pk','teacher':'teacher__pk'}
    if typed:
        if typed[0] not in fields or not typed[1]:return queryset.none()
        return queryset.filter(**{prefix+fields[typed[0]]:typed[1]})
    if text.strip().isascii() and text.strip().isdigit():
        digits=text.strip()
        if len(digits)>19 or not 0<int(digits)<=MAX_NUMBER:return queryset.none()
        # In student pickers, bare numbers mean the student profile ID; U-... is explicit.
        return queryset.filter(**{(prefix+'student__pk' if prefix else 'pk'):int(digits)})
    for part in normalize_name(text).split():
        condition=Q(**{prefix+'name_search__contains':part})
        if email:condition|=Q(**{prefix+'email__icontains':part})
        queryset=queryset.filter(condition)
    return queryset


def student_identity(data):
    if not isinstance(data,dict):raise ValidationError('Укажите ФИО и год выпуска школьника.')
    name=data.get('name');year=data.get('graduation_year');no_patronymic=data.get('no_patronymic',False)
    if not isinstance(name,str) or type(no_patronymic) is not bool:
        raise ValidationError('Укажите полное ФИО и наличие отчества.')
    name=' '.join(name.split())
    words=name.split()
    if not name or len(name)>120 or len(words)<(2 if no_patronymic else 3) or any((len(word)==1 and unicodedata.name(word,'').startswith(('LATIN','CYRILLIC'))) or not any(char.isalpha() for char in word) or any(not (char.isalpha() or unicodedata.category(char).startswith('M') or char in "-'’ʼ") for char in word) for word in words):
        raise ValidationError('Укажите фамилию, имя и отчество полностью, без инициалов. Если отчества нет, отметьте это отдельно. До 120 символов.')
    if type(year) is not int or not 1900<=year<=2200:
        raise ValidationError('Укажите год окончания 11-го класса: целое число от 1900 до 2200.')
    return {'name':name,'graduation_year':year,'no_patronymic':no_patronymic}


def student_profile_complete(student):
    try:student_identity({'name':student.user.name,'graduation_year':student.graduation_year,'no_patronymic':student.no_patronymic})
    except ValidationError:return False
    return True


def masked_email(email):
    local,domain=email.rsplit('@',1)
    return local[:1]+'•••'+local[-1:]+'@'+domain


def filter_users(queryset,params):
    from .filters import id_values,query_values
    from .models import ROLES
    queryset=search_people(queryset,params.get('q',''))
    roles=id_values(query_values(params,'role'))
    if roles:
        if not roles<=ROLES:raise ValidationError('Недопустимая роль в фильтре.')
        queryset=queryset.filter(role_query(roles))
    states=id_values(query_values(params,'state'))
    if states:
        if not states<={'active','inactive'}:raise ValidationError('Недопустимое состояние аккаунта.')
        queryset=queryset.filter(is_active__in=[state=='active' for state in states])
    years=id_values(query_values(params,'graduation_year'))
    if years:
        try:years={int(year) for year in years}
        except (ValueError,TypeError):raise ValidationError('Некорректный год выпуска.')
        if any(not 1900<=year<=2200 for year in years):raise ValidationError('Год выпуска должен быть от 1900 до 2200.')
        queryset=queryset.filter(role_query(['student']),student__graduation_year__in=years)
    return queryset
