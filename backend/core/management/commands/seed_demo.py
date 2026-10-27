from pathlib import Path
import random
from datetime import timedelta
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from core.models import *
from core import services as s

DEMO_PASSWORD='PlusfolioDemo2026!'
class Command(BaseCommand):
    help='Создать вымышленные демоданные. Повторный запуск не сбрасывает изменения.'
    @transaction.atomic
    def handle(self,*args,**options):
        if not settings.DEMO:raise CommandError('Демоданные запрещены вне локального режима.')
        if User.objects.filter(email='admin@plusfolio.example').exists():
            self.stdout.write('Демоданные уже существуют; изменения сохранены.');return
        def account(email,name,roles):
            user=User.objects.create_user(email,DEMO_PASSWORD,name=name,roles=roles);s.profiles(user);return user
        admin=account('admin@plusfolio.example','Администратор',['admin'])
        teacher=account('teacher@plusfolio.example','Анна · демо',['teacher'])
        mentor=account('mentor@plusfolio.example','Михаил · демо',['teacher'])
        analyst=account('analyst@plusfolio.example','Аналитик',['analyst'])
        multi=account('multi@plusfolio.example','Преподаватель и аналитик',['teacher','analyst'])
        names=['Александра К.','Даниил М.','Екатерина С.','Илья П.','Мария Л.','Никита В.','Полина А.','Роман Т.','София Д.','Тимофей Н.','Ульяна Б.','Фёдор Е.']
        students=[account('student@plusfolio.example' if i==0 else f'pupil{i+1}@plusfolio.example',name,['student']) for i,name in enumerate(names)]
        catalogue=settings.BASE_DIR/'data'/'problems_topics.json'
        if catalogue.exists():call_command('import_topics',str(catalogue),verbosity=0)
        if not Topic.objects.exists():
            root=Topic.objects.create(name='Все темы');Topic.objects.create(name='Прочее',parent=root,is_other=True)
            for name in ['Комбинаторика','Геометрия','Методы']:s.add_topic(admin,name,root.pk)
        tags={}
        for kind,labels in {'circle':['Основная программа','Олимпиадная подготовка','Региональный проект'],'problem':['Разминка','На доказательство','Находка'],'worksheet':['Вводный','Практика','Домашний']}.items():
            tags[kind]=[Tag.objects.create(kind=kind,name=name) for name in labels]
        AnalystGrant.objects.create(user=analyst,tag=tags['circle'][0]);AnalystGrant.objects.create(user=multi,tag=tags['circle'][0])
        circles=[]
        for i,(name,city,description) in enumerate([
            ('Математическая мастерская','Москва','7–8 классы · Исследуем идеи, учимся видеть закономерности и объяснять решения.'),
            ('Олимпиадный старт','Казань','8–9 классы · От первых наблюдений к красивым доказательствам.'),
            ('Геометрия в деталях','Новосибирск','8 класс · Чертежи, конструкции и неожиданные связи.')]):
            circle=Circle.objects.create(name=name,city=city,region=city,description=description,created_by=admin,launched_at=timezone.now())
            circle.tags.add(tags['circle'][0 if i!=2 else 2]);circles.append(circle)
        for circle,user in [(circles[0],teacher),(circles[0],mentor),(circles[1],teacher),(circles[1],multi),(circles[2],mentor)]:
            CircleTeacher.objects.create(circle=circle,teacher=user.teacher)
        for user in students:s.enroll(teacher,circles[0],user.email)
        for user in students[:5]:s.enroll(teacher,circles[1],user.email)
        for user in students[6:]:s.enroll(admin,circles[2],user.email)
        def find_topic(name):return Topic.objects.filter(name__icontains=name,is_other=False,parent__isnull=False).first() or Topic.objects.filter(is_other=True,parent__parent=None).first()
        specifications=[
            ('Чётность суммы','Инварианты','На доске записаны числа 1, 2, …, 15. За ход можно стереть два числа и записать их сумму. Может ли последнее число быть нечётным?','Нет. Сумма всех чисел сохраняется и равна $120$, поэтому последнее число чётное.'),
            ('Шесть друзей','Дирихле','На встречу пришли шесть человек. Докажите, что у двух из них одинаковое число знакомых среди остальных. Знакомство взаимно.','Возможны степени от $0$ до $5$, но $0$ и $5$ не встречаются одновременно. Для шести человек остаётся не более пяти вариантов; применяем принцип Дирихле.'),
            ('Домино и шахматная доска','раскраск','Из шахматной доски 8 × 8 вырезали две противоположные угловые клетки. Можно ли замостить остаток костяшками домино 1 × 2?','Нет. Удалены две клетки одного цвета. Каждая костяшка покрывает по одной клетке каждого цвета, а оставшихся клеток разных цветов неодинаковое число.'),
            ('Нечётное произведение','арифметик','Произведение трёх целых чисел нечётно. Может ли их сумма быть чётной?','Нет. Каждый множитель нечётен, а сумма трёх нечётных чисел нечётна.'),
            ('Точки на отрезке','Дирихле','В отрезке длины 1 отмечены пять точек. Докажите, что найдутся две точки на расстоянии не больше $1/4$.','Упорядочим точки. Четыре промежутка между соседними точками имеют суммарную длину не более 1, значит хотя бы один не длиннее $1/4$.'),
            ('Две медианы','Треугольник','Точки M и N — середины сторон AB и AC треугольника ABC. Докажите, что MN параллельна BC и равна половине BC.','По теореме о средней линии треугольника. Также треугольники AMN и ABC подобны с коэффициентом $1/2$.'),
            ('Сумма углов','Треугольник','В треугольнике два угла равны $50^\\circ$ и $60^\\circ$. Найдите третий угол.','Сумма углов треугольника равна $180^\\circ$. Искомый угол: $180^\\circ-50^\\circ-60^\\circ=70^\\circ$.'),
            ('Первые сто чисел','арифметик','Найдите сумму целых чисел от 1 до 100. Объясните способ, не складывая их по очереди.','Составим 50 пар: $1+100=2+99=\\dots=101$. Получаем $50\\cdot101=5050$.')]
        problems=[]
        for i,(title,topic,statement,solution) in enumerate(specifications):
            problem=s.create_material(teacher,'problem',{'title':title,'description':'Демо-задача · условие и решение составлены для Plusfolio','statement':statement,'solution':solution,'topics':[str(find_topic(topic).pk)],'tags':[tags['problem'][i%3].pk]});problems.append(problem)
        sheets=[]
        for title,subset,topic in [('Инварианты и первые наблюдения',problems[:6],'Инварианты'),('Считаем и доказываем',[problems[0],problems[4],problems[6],problems[7]],'Комбинаторик'),('Геометрическая разминка',problems[5:7],'Геометри')]:
            sheets.append(s.create_material(teacher,'worksheet',{'title':title,'description':'Найдите закономерность. Сформулируйте гипотезу. Объясните, почему она верна.','topics':[str(find_topic(topic).pk)],'tags':[tags['worksheet'][1].pk],'problems':[str(p.pk) for p in subset]}))
        from core.worksheets import publish
        for sheet in sheets:publish(admin,sheet.document_id,{'version':sheet.revision})
        for circle,sheet in [(circles[0],sheets[0]),(circles[0],sheets[1]),(circles[1],sheets[0]),(circles[2],sheets[2])]:
            s.issue_worksheet(admin,circle,sheet.pk,timezone.localdate()-timedelta(days=7 if sheet==sheets[0] else 2))
        rng=random.Random(12)
        for person in students:
            for i,problem in enumerate(problems[:6]):
                if rng.random()<0.6:s.mark(teacher,circles[0],problem.pk,{'student_id':person.student.pk,'value':True,'version':0})
        for problem in problems[:3]:s.mark(teacher,circles[0],problem.pk,{'value':True,'version':0},True)
        s.invite(teacher,'new.student@plusfolio.example','student',circles[0])
        self.stdout.write('Демоданные созданы. Пароль профилей указан в README, настоящие письма не отправлены.')
