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
    return FileResponse(toolchain_archive().open('rb'),content_type='application/zip',
                        as_attachment=True,filename='plusfolio-tex-toolchain.zip')
