import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils import timezone

ROLES={'student','teacher','analyst','admin'}
class UserManager(BaseUserManager):
    def create_user(self,email,password=None,**extra):
        user=self.model(email=email.strip().lower(),**extra)
        user.set_password(password); user.save(); return user
    def create_superuser(self,email,password=None,**extra):
        return self.create_user(email,password,roles=['admin'],is_staff=True,is_superuser=True,**extra)

class User(AbstractUser):
    username=None
    email=models.EmailField(unique=True)
    name=models.CharField(max_length=120)
    name_search=models.CharField(max_length=240,default='',editable=False,db_index=True)
    roles=models.JSONField(default=list)
    USERNAME_FIELD='email'
    REQUIRED_FIELDS=[]
    objects=UserManager()
    def save(self,*args,**kwargs):
        from .people import normalize_name
        self.name_search=normalize_name(self.name)
        if kwargs.get('update_fields') is not None:kwargs['update_fields']=set(kwargs['update_fields'])|{'name_search'}
        self.email=self.email.strip().lower()
        if not self.roles or not set(self.roles)<=ROLES: raise ValidationError('Укажите допустимые роли.')
        self.roles=sorted(set(self.roles))
        super().save(*args,**kwargs)

class Student(models.Model):
    user=models.OneToOneField(User,on_delete=models.PROTECT,related_name='student')
    graduation_year=models.PositiveSmallIntegerField(null=True,blank=True,validators=[MinValueValidator(1900),MaxValueValidator(2200)])
    no_patronymic=models.BooleanField(default=False)
    class Meta:
        constraints=[models.CheckConstraint(condition=models.Q(graduation_year__isnull=True)|models.Q(graduation_year__range=(1900,2200)),name='student_graduation_year_range')]
    def education_info(self,on_date=None):
        from .school import education_info
        return education_info(self.graduation_year,on_date)
class Teacher(models.Model):
    user=models.OneToOneField(User,on_delete=models.PROTECT,related_name='teacher')

class Tag(models.Model):
    kind=models.CharField(max_length=12,choices=[(x,x) for x in ['problem','worksheet','circle']])
    name=models.CharField(max_length=100)
    archived=models.BooleanField(default=False)
    class Meta: constraints=[models.UniqueConstraint(fields=['kind','name'],name='unique_typed_tag')]

class NumberedQuerySet(models.QuerySet):
    def bulk_create(self,objs,*args,**kwargs):
        from django.db import transaction
        objs=list(objs);missing=[obj for obj in objs if obj.number_id is None]
        allocator=self.model._meta.get_field('number').remote_field.model
        with transaction.atomic(using=self.db):
            numbers=allocator.objects.using(self.db).bulk_create([allocator() for _ in missing])
            for obj,number in zip(missing,numbers):obj.number_id=number.pk
            return super().bulk_create(objs,*args,**kwargs)

class NumberedEntity(models.Model):
    """An independent database sequence per entity type, without replacing its UUID."""
    objects=NumberedQuerySet.as_manager()
    class Meta:abstract=True
    def save(self,*args,**kwargs):
        from django.db import transaction
        alias=kwargs.get('using') or self._state.db or 'default'
        with transaction.atomic(using=alias):
            if self._state.adding:
                allocator=self._meta.get_field('number').remote_field.model
                if self.number_id is None:self.number_id=allocator.objects.using(alias).create().pk
            elif type(self).objects.using(alias).filter(pk=self.pk).exclude(number_id=self.number_id).exists():
                raise ValidationError('ID сущности неизменяем.')
            super().save(*args,**kwargs)

class CircleNumber(models.Model):
    id=models.BigAutoField(primary_key=True)
class TopicNumber(models.Model):
    id=models.BigAutoField(primary_key=True)
class WorksheetNumber(models.Model):
    id=models.BigAutoField(primary_key=True)
class InvitationNumber(models.Model):
    id=models.BigAutoField(primary_key=True)

class Topic(NumberedEntity):
    number=models.OneToOneField(TopicNumber,on_delete=models.PROTECT,editable=False,related_name='topic')
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    source_id=models.CharField(max_length=64,blank=True)
    name=models.CharField(max_length=160)
    parent=models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT,related_name='children')
    is_other=models.BooleanField(default=False)
    archived=models.BooleanField(default=False)
    sort_order=models.IntegerField(default=0)
    class Meta:
        ordering=['is_other','sort_order','name']
        constraints=[models.UniqueConstraint(fields=['parent'],condition=models.Q(is_other=True),name='one_other_per_parent'),models.UniqueConstraint(fields=['parent','name'],name='unique_topic_sibling')]

class TopicCatalogVersion(models.Model):
    created_at=models.DateTimeField(auto_now_add=True)
    snapshot=models.JSONField(default=list)

class Circle(NumberedEntity):
    number=models.OneToOneField(CircleNumber,on_delete=models.PROTECT,editable=False,related_name='circle')
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    name=models.CharField(max_length=160)
    description=models.TextField(blank=True)
    city=models.CharField(max_length=100)
    region=models.CharField(max_length=100)
    tags=models.ManyToManyField(Tag,blank=True,related_name='circles')
    created_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    archived=models.BooleanField(default=False)
    launched_at=models.DateTimeField(null=True)
    class Meta: ordering=['name']

class CircleTeacher(models.Model):
    circle=models.ForeignKey(Circle,on_delete=models.PROTECT,related_name='teaching')
    teacher=models.ForeignKey(Teacher,on_delete=models.PROTECT,related_name='teaching')
    started_at=models.DateTimeField(auto_now_add=True)
    ended_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['circle','teacher'],condition=models.Q(ended_at=None),name='active_circle_teacher')]
        indexes=[models.Index(fields=['teacher','circle'],condition=models.Q(ended_at__isnull=True),name='teacher_current_circles')]

class Enrollment(models.Model):
    circle=models.ForeignKey(Circle,on_delete=models.PROTECT,related_name='enrollments')
    student=models.ForeignKey(Student,on_delete=models.PROTECT,related_name='enrollments')
    joined_at=models.DateTimeField(auto_now_add=True)
    left_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['circle','student'],condition=models.Q(left_at=None),name='active_enrollment')]
        indexes=[models.Index(fields=['student','circle'],condition=models.Q(left_at__isnull=True),name='student_current_circles')]

class AnalystGrant(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    tag=models.ForeignKey(Tag,on_delete=models.PROTECT)
    class Meta: constraints=[models.UniqueConstraint(fields=['user','tag'],name='unique_analyst_grant')]

class PublishedMaterial(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    title=models.CharField(max_length=180)
    description=models.TextField(blank=True)
    author=models.ForeignKey(User,on_delete=models.PROTECT)
    published=models.BooleanField(default=False)
    archived=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    topic_catalog_version=models.ForeignKey(TopicCatalogVersion,null=True,on_delete=models.PROTECT)
    class Meta: abstract=True
    def save(self,*args,**kwargs):
        old=type(self).objects.filter(pk=self.pk).first()
        if old and old.published:
            for field in self._meta.concrete_fields:
                if field.name not in ['archived'] and getattr(old,field.attname)!=getattr(self,field.attname):
                    raise ValidationError('Опубликованный материал неизменяем. Создайте копию.')
        super().save(*args,**kwargs)

class ProblemNumber(models.Model):
    """Database-allocated display number; UUID remains the identity used by all relations."""
    id=models.BigAutoField(primary_key=True)

class Problem(PublishedMaterial):
    class Meta:
        indexes=[models.Index(fields=['-created_at','-id'],condition=models.Q(published=True),name='problem_published_order')]
        constraints=[models.UniqueConstraint(fields=['source','source_id'],condition=~models.Q(source='')&~models.Q(source_id=''),name='unique_external_problem')]
    title=models.CharField(max_length=180,blank=True,default='')
    number=models.OneToOneField(ProblemNumber,on_delete=models.PROTECT,editable=False,related_name='problem')
    source=models.CharField(max_length=40,blank=True,default='')
    source_id=models.CharField(max_length=64,blank=True,default='')
    source_url=models.URLField(max_length=400,blank=True,default='')
    source_metadata=models.JSONField(default=dict,blank=True)
    objects=NumberedQuerySet.as_manager()
    statement=models.TextField()
    solution=models.TextField()
    statement_tex=models.TextField(blank=True,default='')
    solution_tex=models.TextField(blank=True,default='')
    topics=models.ManyToManyField(Topic,related_name='problems')
    tags=models.ManyToManyField(Tag,related_name='problems',blank=True)
    @property
    def display_title(self):
        return self.title or (f'Задача №{self.source_id} · problems.ru' if self.source=='problems.ru' else f'Задача №{self.number_id}')
    @property
    def attribution(self):
        return {'source':self.source,'source_id':self.source_id,'url':self.source_url} if self.source_url else self.source_metadata.get('attribution',{})
    def save(self,*args,**kwargs):
        from django.db import transaction
        alias=kwargs.get('using') or self._state.db or 'default'
        with transaction.atomic(using=alias):
            if self.number_id is None:self.number_id=ProblemNumber.objects.using(alias).create().pk
            super().save(*args,**kwargs)

class WorksheetDocument(NumberedEntity):
    number=models.OneToOneField(WorksheetNumber,on_delete=models.PROTECT,editable=False,related_name='worksheetdocument')
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    author=models.ForeignKey(User,on_delete=models.PROTECT,related_name='worksheet_documents')
    current_revision=models.OneToOneField('Worksheet',null=True,on_delete=models.PROTECT,related_name='+')
    public_revision=models.OneToOneField('Worksheet',null=True,on_delete=models.PROTECT,related_name='+')
    copied_from=models.ForeignKey('Worksheet',null=True,on_delete=models.PROTECT,related_name='copies')
    created_at=models.DateTimeField(auto_now_add=True)


class ProblemSearchDocument(models.Model):
    """Rebuildable search data; result access always comes from the primary models."""
    from pgvector.django import VectorField
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE, related_name='search_documents')
    kind = models.CharField(max_length=12, choices=[('statement', 'statement'), ('solution', 'solution'), ('metadata', 'metadata')])
    text = models.TextField()
    normalized = models.TextField()
    fingerprint = models.CharField(max_length=64)
    embedding = VectorField(dimensions=384, null=True)
    model = models.CharField(max_length=100, default='')
    indexed_at = models.DateTimeField(null=True)
    retry_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['problem', 'kind'], name='one_problem_search_section')]
        indexes = [models.Index(fields=['model', 'kind'], name='search_model_kind')]

class CatalogueSearchDocument(models.Model):
    """Rebuildable metadata, keyed by entity type and immutable source UUID."""
    from pgvector.django import VectorField
    kind=models.CharField(max_length=12,choices=[(value,value) for value in ['circle','worksheet','topic']])
    object_id=models.UUIDField()
    text=models.TextField()
    normalized=models.TextField()
    fingerprint=models.CharField(max_length=64)
    embedding=VectorField(dimensions=384,null=True)
    model=models.CharField(max_length=100,default='')
    indexed_at=models.DateTimeField(null=True)
    retry_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['kind','object_id'],name='one_catalogue_search_entity')]
        indexes=[models.Index(fields=['model','kind'],name='catalogue_search_model_kind')]


class Worksheet(PublishedMaterial):
    class Meta:
        indexes=[models.Index(fields=['-created_at','-id'],condition=models.Q(published=True),name='worksheet_published_order')]
        constraints=[models.UniqueConstraint(fields=['document','revision'],name='unique_worksheet_revision')]
    document=models.ForeignKey(WorksheetDocument,on_delete=models.PROTECT,related_name='revisions')
    revision=models.PositiveIntegerField(default=1)
    template_version=models.CharField(max_length=40,default='math-a4-v1')
    topics=models.ManyToManyField(Topic,related_name='worksheets')
    tags=models.ManyToManyField(Tag,related_name='worksheets',blank=True)

class WorksheetItem(models.Model):
    worksheet=models.ForeignKey(Worksheet,on_delete=models.PROTECT,related_name='items')
    problem=models.ForeignKey(Problem,on_delete=models.PROTECT,related_name='items')
    position=models.PositiveIntegerField()
    class Meta:
        ordering=['position']
        constraints=[models.UniqueConstraint(fields=['worksheet','problem'],name='one_problem_in_worksheet'),models.UniqueConstraint(fields=['worksheet','position'],name='one_position')]
    def save(self,*args,**kwargs):
        if self.worksheet.published: raise ValidationError('Состав опубликованного листка неизменяем.')
        super().save(*args,**kwargs)

class WorksheetIssue(models.Model):
    circle=models.ForeignKey(Circle,on_delete=models.PROTECT,related_name='issues')
    worksheet=models.ForeignKey(Worksheet,on_delete=models.PROTECT,related_name='issues')
    document=models.ForeignKey(WorksheetDocument,on_delete=models.PROTECT,related_name='issues')
    issued_on=models.DateField()
    issued_by=models.ForeignKey(User,on_delete=models.PROTECT)
    number=models.PositiveIntegerField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['circle','document'],name='one_document_issue_per_circle'),models.UniqueConstraint(fields=['circle','number'],name='unique_circle_issue_number')]
        indexes=[models.Index(fields=['circle','-issued_on','-id'],name='circle_issues_recent')]

class Assignment(models.Model):
    issue=models.ForeignKey(WorksheetIssue,on_delete=models.PROTECT,related_name='assignments')
    student=models.ForeignKey(Student,on_delete=models.PROTECT,related_name='assignments')
    assigned_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['issue','student'],name='one_assignment')]
        indexes=[models.Index(fields=['student','issue'],name='student_issue_assignments')]

class Solve(models.Model):
    student=models.ForeignKey(Student,on_delete=models.PROTECT)
    problem=models.ForeignKey(Problem,on_delete=models.PROTECT,related_name='solves')
    solved=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=1)
    changed_by=models.ForeignKey(User,on_delete=models.PROTECT)
    source_circle=models.ForeignKey(Circle,on_delete=models.PROTECT)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['student','problem'],name='global_student_problem')]
        indexes=[models.Index(fields=['student','problem'],condition=models.Q(solved=True),name='solved_student_problems')]

class Discussion(models.Model):
    circle=models.ForeignKey(Circle,on_delete=models.PROTECT)
    problem=models.ForeignKey(Problem,on_delete=models.PROTECT)
    discussed=models.BooleanField(default=False)
    solution_visible=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=1)
    changed_by=models.ForeignKey(User,on_delete=models.PROTECT)
    class Meta:
        constraints=[
            models.UniqueConstraint(fields=['circle','problem'],name='circle_problem_discussion'),
            models.CheckConstraint(condition=models.Q(solution_visible=False)|models.Q(discussed=True),name='visible_solution_requires_discussion'),
        ]
        indexes=[models.Index(fields=['problem','circle'],condition=models.Q(discussed=True,solution_visible=True),name='visible_problem_solutions')]

class AuditEvent(models.Model):
    actor=models.ForeignKey(User,on_delete=models.PROTECT)
    circle=models.ForeignKey(Circle,null=True,on_delete=models.PROTECT)
    kind=models.CharField(max_length=40)
    payload=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)

class Invitation(NumberedEntity):
    number=models.OneToOneField(InvitationNumber,on_delete=models.PROTECT,editable=False,related_name='invitation')
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    email=models.EmailField()
    role=models.CharField(max_length=16)
    circle=models.ForeignKey(Circle,null=True,on_delete=models.PROTECT)
    tags=models.ManyToManyField(Tag)
    created_by=models.ForeignKey(User,on_delete=models.PROTECT)
    token_hash=models.CharField(max_length=64,unique=True)
    expires_at=models.DateTimeField()
    state=models.CharField(max_length=16,default='pending')
    created_at=models.DateTimeField(auto_now_add=True)

class EmailOutbox(models.Model):
    invitation=models.ForeignKey(Invitation,on_delete=models.PROTECT,related_name='letters')
    encrypted_payload=models.TextField()
    state=models.CharField(max_length=16,default='queued')
    created_at=models.DateTimeField(auto_now_add=True)
    attempts=models.PositiveSmallIntegerField(default=0)
    next_attempt_at=models.DateTimeField(null=True)
    locked_until=models.DateTimeField(null=True)
    sent_at=models.DateTimeField(null=True)
    error_code=models.CharField(max_length=64,blank=True)
    class Meta:
        indexes=[models.Index(fields=['next_attempt_at','id'],condition=models.Q(state__in=['queued','retry']),name='outbox_pending_retry')]

@receiver(m2m_changed)
def protect_material_links(sender,instance,action,reverse,model,pk_set,**kwargs):
    links={Problem.topics.through,Problem.tags.through,Worksheet.topics.through,Worksheet.tags.through}
    if sender not in links or not action.startswith('pre_'): return
    if isinstance(instance,(Problem,Worksheet)) and instance.published:
        raise ValidationError('Темы и теги опубликованного материала неизменяемы.')
    if reverse:
        manager='problems' if sender in {Problem.topics.through,Problem.tags.through} else 'worksheets'
        queryset=getattr(instance,manager).all()
        if pk_set is not None: queryset=queryset.filter(pk__in=pk_set)
        if queryset.filter(published=True).exists(): raise ValidationError('Привязки опубликованного материала защищены.')


class ApiToken(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='api_tokens')
    name=models.CharField(max_length=100)
    prefix=models.CharField(max_length=11)
    digest=models.CharField(max_length=64,unique=True,editable=False)
    password_stamp=models.CharField(max_length=64,editable=False)
    read_only=models.BooleanField(default=False)
    created_at=models.DateTimeField(default=timezone.now)
    expires_at=models.DateTimeField(db_index=True)
    revoked_at=models.DateTimeField(null=True)
    last_used_at=models.DateTimeField(null=True)
