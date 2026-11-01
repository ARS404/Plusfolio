"""Image permissions stay scoped while many attachments share one permission query."""
import hashlib
from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from . import services as s
from .image_assets import authorize_images,can_read
from .models import (Assignment,Circle,Discussion,Enrollment,ImageAsset,Problem,User,
                     Worksheet,WorksheetDocument,WorksheetIssue,WorksheetItem)


class ImagePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create(email='image-owner@example.test',name='Автор',roles=['teacher'])
        cls.reader=User.objects.create(email='image-reader@example.test',name='Другой автор',roles=['teacher'])
        cls.student=User.objects.create(email='image-student@example.test',name='Ученик',roles=['student'])
        s.profiles(cls.student)
        cls.assets=[]
        for index in range(8):
            data=f'permission-fixture-{index}'.encode()
            cls.assets.append(ImageAsset.objects.create(owner=cls.owner,digest=hashlib.sha256(data).hexdigest(),
                media_type='image/png',width=1,height=1,size=len(data),data=data))
        cls.problem=Problem.objects.create(author=cls.owner,title='Рисунки',statement='Условие',solution='Решение')
        cls.problem.statement_assets.set(cls.assets);cls.problem.published=True;cls.problem.save()
        cls.circle=Circle.objects.create(name='Кружок рисунков',created_by=cls.owner)
        Enrollment.objects.create(circle=cls.circle,student=cls.student.student)
        document=WorksheetDocument.objects.create(author=cls.owner)
        sheet=Worksheet.objects.create(document=document,author=cls.owner,title='Листок с рисунками')
        WorksheetItem.objects.create(worksheet=sheet,problem=cls.problem,position=1)
        sheet.published=True;sheet.save()
        issue=WorksheetIssue.objects.create(circle=cls.circle,worksheet=sheet,document=document,issued_by=cls.owner,
            number=1,issued_on=timezone.localdate())
        Assignment.objects.create(issue=issue,student=cls.student.student)

    def test_many_foreign_attachments_use_one_query_without_loading_pixels(self):
        images=[{'id':str(asset.pk)} for asset in self.assets]
        with CaptureQueriesContext(connection) as queries:
            result=authorize_images(self.reader,images)
        self.assertEqual({asset.pk for asset in result},{asset.pk for asset in self.assets})
        self.assertEqual(len(queries),1)
        self.assertNotIn('"core_imageasset"."data"',queries[0]['sql'])

    def test_student_condition_access_does_not_reveal_private_solution_images(self):
        data=b'private-solution'
        private=ImageAsset.objects.create(owner=self.owner,digest=hashlib.sha256(data).hexdigest(),
            media_type='image/png',width=1,height=1,size=len(data),data=data)
        problem=Problem.objects.create(author=self.owner,title='Решение с рисунком',statement='Условие',solution='Решение')
        problem.solution_assets.add(private);problem.published=True;problem.save()
        # A new independently issued worksheet gives access to its condition, but not its solution.
        document=WorksheetDocument.objects.create(author=self.owner)
        sheet=Worksheet.objects.create(document=document,author=self.owner,title='Закрытое решение')
        WorksheetItem.objects.create(worksheet=sheet,problem=problem,position=1)
        sheet.published=True;sheet.save()
        issue=WorksheetIssue.objects.create(circle=self.circle,worksheet=sheet,document=document,issued_by=self.owner,
            number=2,issued_on=timezone.localdate())
        Assignment.objects.create(issue=issue,student=self.student.student)
        self.assertTrue(can_read(self.student,self.assets[0]))
        self.assertFalse(can_read(self.student,private))
        with self.assertRaises(ValidationError):authorize_images(self.student,[{'id':str(self.assets[0].pk)},{'id':str(private.pk)}])
        Discussion.objects.create(circle=self.circle,problem=problem,discussed=True,solution_visible=True,changed_by=self.owner)
        self.assertTrue(can_read(self.student,private))
        self.assertEqual(len(authorize_images(self.student,[{'id':str(private.pk)}])),1)

    def test_missing_and_unattached_foreign_images_are_rejected(self):
        for identity in [str(uuid4()),str(ImageAsset.objects.create(owner=self.owner,digest='f'*64,
                media_type='image/png',width=1,height=1,size=1,data=b'x').pk)]:
            with self.subTest(identity=identity),self.assertRaises(ValidationError):
                authorize_images(self.reader,[{'id':identity}])

    def test_empty_image_list_needs_no_query_and_owner_keeps_access(self):
        with self.assertNumQueries(0):self.assertEqual(authorize_images(self.reader,[]),[])
        self.assertTrue(can_read(self.owner,self.assets[0]))
