"""Shared validation/serialization for revision-local worksheet content."""
from uuid import UUID
from django.core.exceptions import ValidationError

STYLES={'plain':'Обычный текст','heading':'Заголовок','definition':'Определение',
        'theorem':'Теорема','lemma':'Лемма','example':'Пример','remark':'Замечание'}


def numbering_start(value=1):
    if type(value) is not int or value not in {0,1}:raise ValidationError('Нумерация задач начинается с 0 или с 1.')
    return value


def image_list(values):
    if not isinstance(values,list) or len(values)>20:raise ValidationError('В одном блоке доступны до 20 изображений.')
    result=[];seen=set()
    for value in values:
        if not isinstance(value,dict):raise ValidationError('Некорректное изображение.')
        try:identity=str(UUID(str(value.get('id',''))))
        except (ValueError,TypeError,AttributeError):raise ValidationError('Некорректный ID изображения.')
        width=value.get('width',70);align=value.get('align','center');caption=value.get('caption','')
        if identity in seen or type(width) is not int or not 10<=width<=100 or align not in {'left','center','right'}:
            raise ValidationError('Ширина рисунка — от 10 до 100%; рисунки внутри блока не повторяются.')
        if not isinstance(caption,str) or len(caption)>500:raise ValidationError('Подпись рисунка — до 500 символов.')
        seen.add(identity);result.append({'id':identity,'width':width,'align':align,'caption':caption.strip()})
    return result


def normalize_blocks(values):
    from .documents import validate_tex
    if not isinstance(values,list) or not 1<=len(values)<=300:raise ValidationError('Добавьте от 1 до 300 блоков.')
    blocks=[];problems=[];total=0
    for index,value in enumerate(values,1):
        if not isinstance(value,dict):raise ValidationError(f'Блок {index}: передайте объект.')
        if value.get('kind')=='problem':
            try:identity=str(UUID(str(value.get('problem_id',''))))
            except (ValueError,TypeError,AttributeError):raise ValidationError(f'Блок {index}: некорректный ID задачи.')
            if identity in problems:raise ValidationError('Одна задача может встречаться в листке только один раз.')
            included=value.get('include_in_journal',True)
            if type(included) is not bool:raise ValidationError(f'Блок {index}: включение в плюсник задаётся как да/нет.')
            blocks.append({'kind':'problem','problem_id':identity,'include_in_journal':included});problems.append(identity)
        elif value.get('kind')=='text':
            style=value.get('style','plain');title=value.get('title','');text=value.get('text','');tex=value.get('tex','')
            if style not in STYLES or any(not isinstance(v,str) for v in [title,text,tex]):raise ValidationError(f'Блок {index}: неверный формат текста.')
            if len(title)>180 or len(text)>30000:raise ValidationError(f'Блок {index}: заголовок до 180, текст до 30 000 символов.')
            if tex:validate_tex(tex)
            images=image_list(value.get('images',[]))
            if not (text.strip() or tex.strip() or images or style=='heading' and title.strip()):raise ValidationError(f'Блок {index}: заполните текст или добавьте рисунок.')
            total+=len(text.encode())+len(tex.encode())
            blocks.append({'kind':'text','style':style,'title':title.strip(),'text':text.strip(),'tex':tex.strip(),'images':images})
        else:raise ValidationError(f'Блок {index}: выберите текст или задачу.')
    if total>2*1024*1024:raise ValidationError('Текст листка превышает 2 МиБ.')
    return blocks,problems


def serialize_blocks(worksheet):
    return [{'kind':'problem','problem_id':str(block.problem_id),'include_in_journal':block.include_in_journal} if block.kind=='problem' else
            {'kind':'text','style':block.style,'title':block.title,'text':block.text,'tex':block.tex,'images':block.images}
            for block in worksheet.blocks.all()]


def create_blocks(worksheet,blocks):
    from .models import WorksheetBlock
    for position,value in enumerate(blocks,1):
        block=WorksheetBlock.objects.create(worksheet=worksheet,position=position,**value)
        if value['kind']=='text':block.assets.set([image['id'] for image in value.get('images',[])])
