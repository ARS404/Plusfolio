"""Small, dependency-free project transport shared by local and isolated compilers."""
import base64,re
from pathlib import Path

REQUIRED={'main.tex','template.tex','variables.tex','problems.tex','solutions.tex'}
TEXT_PATH=re.compile(r'(?:main|variables|template|problems|solutions)\.tex|(?:tasks|solutions|blocks)/[A-Za-z0-9_-]+\.tex')
IMAGE_PATH=re.compile(r'assets/[0-9a-f-]{36}\.png')
MAX_IMAGE_BYTES=4*1024*1024
MAX_PROJECT_BYTES=8*1024*1024
MAX_PDF_BYTES=16*1024*1024


def project_files(project):
    if not isinstance(project,dict) or not REQUIRED<=set(project) or len(project)>1100:raise ValueError('Некорректный состав проекта TeX.')
    total=0;text_size=0;result=[]
    for name,value in project.items():
        if not isinstance(name,str):raise ValueError('Недопустимое имя файла TeX.')
        if TEXT_PATH.fullmatch(name) and isinstance(value,str):
            data=value.encode();text_size+=len(data)
            if text_size>2*1024*1024:raise ValueError('Исходники проекта превышают 2 МиБ.')
        elif IMAGE_PATH.fullmatch(name) and isinstance(value,dict) and set(value)=={'base64'}:
            try:data=base64.b64decode(value['base64'],validate=True)
            except (ValueError,TypeError):raise ValueError('Некорректное изображение в проекте.')
            if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>2*1024*1024:raise ValueError('Некорректный PNG в проекте.')
            total+=len(data)
            if total>MAX_IMAGE_BYTES:raise ValueError('Рисунки одного проекта превышают 4 МиБ.')
        else:raise ValueError('Недопустимый файл проекта TeX.')
        result.append((name,data))
    return result


def write_project(project,directory):
    for name,data in project_files(project):
        target=Path(directory)/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
