"""Immutable normalized PNG/JPEG assets with the same visibility as their content."""
import base64,hashlib,io,warnings
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists,OuterRef,Q,Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from . import services as s
from .models import ImageAsset,Problem,User,WorksheetBlock
from .people import has_adult_role

MAX_IMAGE_BYTES=2*1024*1024
MAX_PIXELS=16_000_000


def normalize_image(data):
    from PIL import Image,ImageOps,UnidentifiedImageError
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_IMAGE_BYTES:raise ValidationError('PNG/JPEG — не более 2 МиБ.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data),formats=['PNG','JPEG']) as image:
                if image.width*image.height>MAX_PIXELS or max(image.size)>8192 or getattr(image,'n_frames',1)!=1:
                    raise ValidationError('Изображение — до 16 мегапикселей и 8192 пикселей по стороне; без анимации.')
                image.load();ImageOps.exif_transpose(image,in_place=True)
                # Re-encode pixels only: names, EXIF and arbitrary embedded data are not retained.
                mode='RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB'
                normalized=image if image.mode==mode else image.convert(mode)
                try:
                    normalized.info.clear()
                    output=io.BytesIO();normalized.save(output,format='PNG')
                    payload=output.getvalue()
                    if len(payload)>MAX_IMAGE_BYTES:raise ValidationError('После обработки рисунок превышает 2 МиБ. Уменьшите изображение.')
                    return payload,normalized.width,normalized.height
                finally:
                    if normalized is not image:normalized.close()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValidationError('Не удалось прочитать PNG/JPEG. Проверьте файл и размер рисунка.')


def readable_assets(user,assets,circle=None):
    """Resolve an attachment set in SQL without a permission query per image."""
    if not user.is_authenticated:return assets.none()
    if s.admin(user):return assets
    problems=s.problems_for(user)
    worksheets=s.worksheets_for(user)
    if 'student' in user.roles:
        problems=(problems|s.my_problems_for(user)).distinct()
        worksheets=(worksheets|s.my_worksheets_for(user)).distinct()
    if circle is not None:
        problems=problems.filter(items__worksheet__issues__circle=circle)
        worksheets=worksheets.filter(issues__circle=circle)
    statements=Problem.statement_assets.through.objects.filter(imageasset_id=OuterRef('pk'),problem_id__in=problems)
    solutions=Problem.solution_assets.through.objects.filter(imageasset_id=OuterRef('pk'),problem_id__in=s.solutions_for(user,problems,circle))
    texts=WorksheetBlock.assets.through.objects.filter(imageasset_id=OuterRef('pk'),worksheetblock__worksheet__in=worksheets)
    return assets.filter(Q(owner=user)|Q(Exists(statements))|Q(Exists(solutions))|Q(Exists(texts)))


def can_read(user,asset,circle=None):
    if not user.is_authenticated:return False
    if s.admin(user) or asset.owner_id==user.pk:return True
    return readable_assets(user,ImageAsset.objects.filter(pk=asset.pk),circle).exists()


def authorize_images(user,images):
    identities={image['id'] for image in images}
    if not identities:return []
    assets=list(readable_assets(user,ImageAsset.objects.filter(pk__in=identities)).defer('data'))
    if len(assets)!=len(identities):
        raise ValidationError('Один из рисунков недоступен. Загрузите его или выберите доступный материал.')
    return assets


def metadata(asset):
    return {'id':str(asset.pk),'url':'/api/images/'+str(asset.pk),'width_px':asset.width,'height_px':asset.height,'size':asset.size}


@api_view(['POST'])
@transaction.atomic
def upload(request):
    s.require(has_adult_role(request.user),'Загрузка рисунков доступна авторам листков.')
    User.objects.select_for_update().get(pk=request.user.pk)
    # Only unused uploads expire; every saved problem/revision keeps its images permanently.
    ImageAsset.objects.filter(owner=request.user,created_at__lt=timezone.now()-timedelta(days=1),
        statement_problems__isnull=True,solution_problems__isnull=True,text_blocks__isnull=True).delete()
    file=request.FILES.get('file')
    if file:
        if file.size>MAX_IMAGE_BYTES:raise ValidationError('PNG/JPEG — не более 2 МиБ.')
        source=file.read(MAX_IMAGE_BYTES+1)
    else:
        encoded=request.data.get('data','')
        if not isinstance(encoded,str) or len(encoded)>4*MAX_IMAGE_BYTES//3+16:raise ValidationError('Передайте PNG/JPEG до 2 МиБ.')
        try:source=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):raise ValidationError('Некорректные данные изображения.')
    data,width,height=normalize_image(source);digest=hashlib.sha256(data).hexdigest()
    existing=ImageAsset.objects.filter(owner=request.user,digest=digest).defer('data').first()
    if existing:return Response(metadata(existing))
    used=ImageAsset.objects.filter(owner=request.user).aggregate(total=Sum('size'))['total'] or 0
    if used+len(data)>getattr(settings,'IMAGE_STORAGE_PER_USER_BYTES',50*1024*1024):
        raise ValidationError('Достигнут лимит рисунков аккаунта — 50 МиБ. Обратитесь к администратору.')
    asset=ImageAsset.objects.create(owner=request.user,digest=digest,data=data,media_type='image/png',width=width,height=height,size=len(data))
    return Response(metadata(asset),status=201)


@api_view(['GET'])
def image(request,pk):
    asset=ImageAsset.objects.filter(pk=pk).defer('data').first()
    circle=s.get_circle(request.user,request.query_params['circle']) if request.query_params.get('circle') else None
    if not asset or not can_read(request.user,asset,circle):raise s.NotFound('Изображение недоступно.')
    response=HttpResponse(bytes(ImageAsset.objects.only('data').get(pk=pk).data),content_type=asset.media_type)
    response['Content-Disposition']='inline; filename="'+str(asset.pk)+'.png"'
    response['X-Content-Type-Options']='nosniff'
    return response
