"""School grade is derived from the expected year of finishing grade 11."""
from django.utils import timezone


def education_info(graduation_year, on_date=None):
    current_grade = None
    label = 'Класс не указан'
    if graduation_year is not None:
        on_date = on_date or timezone.localdate()
        academic_start = on_date.year if on_date.month >= 9 else on_date.year - 1
        calculated = 12 + academic_start - graduation_year
        if calculated < 1:
            label = 'Ещё не учится'
        elif calculated > 11:
            label = 'Выпускник'
        else:
            current_grade = calculated
            label = f'{current_grade} класс'
    return {'graduation_year': graduation_year, 'current_grade': current_grade, 'grade_label': label}
