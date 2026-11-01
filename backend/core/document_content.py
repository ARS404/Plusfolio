"""Render trusted block styles and image positions into the common TeX project."""
import base64,re
from django.core.exceptions import ValidationError

IMAGE_TOKEN=re.compile(r'\\pfimage\{([0-9a-f-]{36})\}')


def content_fragment(text='',tex='',images=()):
    from .documents import escape_text,validate_tex
    source=validate_tex(tex) if tex else text
    declared={image['id']:image for image in images};used=set()
    def image_fragment(identity):
        if identity not in declared:raise ValidationError('Рисунок в тексте не прикреплён к этому блоку.')
        image=declared[identity];used.add(identity)
        align={'left':'flushleft','center':'center','right':'flushright'}[image['align']]
        caption=('\n\\par{\\small '+escape_text(image['caption'])+'}\\par') if image['caption'] else ''
        return '\n\\begin{'+align+'}\n\\includegraphics[width='+str(image['width']/100)+r'\linewidth]{assets/'+identity+'.png}'+caption+'\n\\end{'+align+'}\n'
    parts=[];offset=0
    def plain(value):
        if tex:return value
        return ''.join(validate_tex(part) if part.startswith('$') and part.endswith('$') else escape_text(part)
                       for part in re.split(r'(\$[^$\n]+\$)',value))
    for match in IMAGE_TOKEN.finditer(source):
        parts.extend([plain(source[offset:match.start()]),image_fragment(match[1])]);offset=match.end()
    parts.append(plain(source[offset:]))
    parts.extend(image_fragment(identity) for identity in declared if identity not in used)
    return ''.join(parts)


def text_block_fragment(block):
    from .documents import escape_text
    source=content_fragment(block.get('text',''),block.get('tex',''),block.get('images',[]))
    style=block.get('style','plain');title=escape_text(block.get('title',''))
    if style=='heading':return '\n\\section*{'+(title or escape_text(block.get('text','')))+'}\n'+(source if title else '')
    if style in {'definition','theorem','lemma','example','remark'}:
        return '\n\\begin{'+style+'}'+('[{'+title+'}]' if title else '')+'\n'+source+'\n\\end{'+style+'}\n'
    return ('\n\\paragraph*{'+title+'}\n' if title else '\n')+source+'\n'


def attach_images(files,images,assets=None):
    identities={image['id'] for image in images}
    if not identities:return
    if assets is None:
        from .models import ImageAsset
        assets={str(row.pk):{'base64':base64.b64encode(bytes(row.data)).decode()} for row in ImageAsset.objects.filter(pk__in=identities).only('id','data')}
    for identity in identities:
        if identity not in assets:raise ValidationError('Рисунок отсутствует в проекте.')
        files['assets/'+identity+'.png']=assets[identity]
