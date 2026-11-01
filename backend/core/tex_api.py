from django.http import FileResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .services import require
from .tex_toolchain import build_contract,toolchain_archive


def authorize(user):
    require(bool({'teacher','admin'}&set(user.roles)),'Подготовка TeX доступна преподавателю и администратору.')


@api_view(['GET'])
def toolchain(request):
    authorize(request.user)
    return Response(build_contract())


@api_view(['GET'])
def archive(request):
    authorize(request.user)
    return FileResponse(toolchain_archive(open_file=True),content_type='application/zip',
                        as_attachment=True,filename='plusfolio-tex-toolchain.zip')


@api_view(['POST'])
def preview(request):
    """Compile an authorized unsaved draft, without creating a revision or caching it."""
    from types import SimpleNamespace
    from django.core.exceptions import ValidationError
    from .content import normalize_blocks,numbering_start
    from .image_assets import authorize_images
    from .documents import project_for,response
    from . import services as s
    from .people import has_adult_role
    s.require(has_adult_role(request.user))
    from rest_framework.throttling import UserRateThrottle
    class PreviewThrottle(UserRateThrottle):rate='12/min'
    throttle=PreviewThrottle()
    if not throttle.allow_request(request,preview):
        from rest_framework.exceptions import Throttled
        raise Throttled(wait=throttle.wait(),detail='Подождите перед следующей сборкой предпросмотра.')
    blocks,ids=normalize_blocks(request.data.get('blocks',[]))
    problems=list(s.problems_for(request.user).filter(pk__in=ids))
    by_id={str(problem.pk):problem for problem in problems}
    if len(problems)!=len(ids):raise ValidationError('Одна из задач недоступна.')
    authorize_images(request.user,[image for block in blocks if block['kind']=='text' for image in block['images']])
    title=request.data.get('title','Предпросмотр листка');description=request.data.get('description','')
    if not isinstance(title,str) or not isinstance(description,str) or len(title)>180 or len(description)>30000:raise ValidationError('Некорректные название или описание.')
    sheet=SimpleNamespace(title=title or 'Предпросмотр листка',description=description,template_version='math-a4-v2',numbering_start=numbering_start(request.data.get('numbering_start',1)),_document_blocks=blocks)
    allowed=s.visible_solution_ids(request.user,[p.pk for p in problems])
    project=project_for(sheet,[by_id[pk] for pk in ids],allowed,request.data.get('solutions') is True)
    return response(project,'pdf',cache=False)
