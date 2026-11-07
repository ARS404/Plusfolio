"""Assemble multifile TeX projects; authorize and filter solutions before assembly."""
import hashlib, io, json, os, re, shutil, sys, threading, zipfile
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from rest_framework.exceptions import APIException
from .tex_project import MAX_PDF_BYTES,MAX_PROJECT_BYTES

ROOT=Path(__file__).resolve().parent
TEMPLATE='math-a4-v2'
SUPPORTED_TEMPLATES={'math-a4-v1','math-a4-v2'}
WORKERS=threading.BoundedSemaphore(2)
TEXT_ESCAPES=str.maketrans({'\\':r'\textbackslash{}','{':r'\{','}':r'\}','$':r'\$','&':r'\&','#':r'\#','%':r'\%','_':r'\_','^':r'\textasciicircum{}','~':r'\textasciitilde{}'})


def validate_tex(source):
    if not isinstance(source,str) or len(source)>30000 or '\x00' in source:
        raise ValidationError('TeX-фрагмент должен содержать не более 30 000 символов.')
    if re.search(r'\\(?:documentclass|usepackage)\b|\\(?:begin|end)\s*\{document\}',source):
        raise ValidationError('Вставьте фрагмент TeX без преамбулы и document. TikZ уже подключён шаблоном.')
    return source


def escape_text(value):
    return str(value).translate(TEXT_ESCAPES)


def fragment(problem,field):
    images=getattr(problem,field+'_images',[])
    if images:
        from .document_content import content_fragment
        return content_fragment(getattr(problem,field,''),getattr(problem,field+'_tex',''),images)
    source=getattr(problem,field+'_tex','')
    if source:return validate_tex(source)
    parts=re.split(r'(\$[^$\n]+\$)',getattr(problem,field))
    return ''.join(validate_tex(part) if part.startswith('$') and part.endswith('$') else escape_text(part) for part in parts)


def references(base,title):
    return {'title':title,'pdf_url':base+'/pdf','tex_url':base+'/tex','project_url':base+'/project'}


def issue_references(issue,personal=False):
    base='/api/my-issues/'+str(issue.pk) if personal else '/api/circles/'+str(issue.circle_id)+'/issues/'+str(issue.pk)
    return references(base,issue.worksheet.title)


def project_for(worksheet,problems,allowed_solutions=(),solutions=False,issue=None,assets=None):
    if len(problems)>300:
        raise ValidationError('Для одного PDF доступны до 300 задач и до 2 МиБ исходников.')
    from .content import numbering_start
    first_number=numbering_start(getattr(worksheet,'numbering_start',1))
    sources = [];images=[]
    source_size = 0
    for problem in problems:
        statement = fragment(problem, 'statement')
        solution = fragment(problem, 'solution') if solutions and problem.pk in allowed_solutions else None
        images.extend(getattr(problem,'statement_images',[]))
        if solution is not None:images.extend(getattr(problem,'solution_images',[]))
        source_size += len(statement) + len(solution or '')
        if source_size > 2*1024*1024:
            raise ValidationError('Для одного PDF доступны до 300 задач и до 2 МиБ исходников.')
        sources.append((problem, statement, solution))
    version=getattr(worksheet,'template_version',TEMPLATE)
    if version not in SUPPORTED_TEMPLATES:raise ValidationError('Неизвестная версия шаблона TeX.')
    files={'main.tex':'% Plusfolio: main document\n\\input{variables.tex}\n\\input{template.tex}\n',
           'template.tex':(ROOT/'tex_templates'/f'{version}.tex').read_text()}
    values={'Title':worksheet.title,'Description':worksheet.description,
            'Circle':issue.circle.name if issue else 'НАЗВАНИЕ КРУЖКА',
            'Date':issue.issued_on.strftime('%d.%m.%Y') if issue else 'ДАТА ВЫДАЧИ',
            'Number':str(issue.number) if issue else 'НОМЕР ЛИСТОЧКА'}
    files['variables.tex']='% Parameters of this issue\n'+'\n'.join(r'\newcommand{\Plusfolio'+key+'}{'+escape_text(value)+'}' for key,value in values.items())+'\n'
    tasks=[];answers=[]
    for index,(problem,statement,solution) in enumerate(sources,1):
        name=f'tasks/{index:03d}-{problem.pk}.tex'
        attribution=''
        origin=getattr(problem,'attribution',{})
        if origin:
            attribution='\n\\par{\\footnotesize\\sffamily Источник: '+escape_text(origin['source'])+' № '+escape_text(origin['source_id'])+'.\\par '+escape_text(origin['url'])+'}\n'
        files[name]=statement+attribution+'\n'
        tasks.append(r'\item \input{'+name+'}')
        if solution is not None:
            name=f'solutions/{index:03d}-{problem.pk}.tex';files[name]=solution+'\n'
            answers.append(r'\item[\textbf{'+str(index+first_number-1)+r'.}] \input{'+name+'}')
    files['problems.tex']=r'\begin{enumerate}[leftmargin=*,label=\textbf{\arabic*.},itemsep=12pt'+(',start=0' if first_number==0 else '')+']'+'\n'+'\n'.join(tasks)+'\n'+r'\end{enumerate}'+'\n'
    if version=='math-a4-v2':
        from .document_content import text_block_fragment
        blocks=getattr(worksheet,'_document_blocks',None)
        if blocks is None and hasattr(worksheet,'blocks'):
            from .content import serialize_blocks
            blocks=serialize_blocks(worksheet)
        if blocks:
            if len(blocks)>300:raise ValidationError('В листке доступны до 300 блоков.')
            sequence=[];number=first_number-1;source_by_id={str(problem.pk):index for index,(problem,_,_) in enumerate(sources)}
            for position,block in enumerate(blocks,1):
                if block['kind']=='problem':
                    index=source_by_id.get(str(block['problem_id']))
                    if index is None:raise ValidationError('Задача блока отсутствует в проекте.')
                    number+=1
                    sequence.append(r'\begin{enumerate}[leftmargin=*,label=\textbf{\arabic*.},topsep=5pt,start='+str(number)+']\n'+tasks[index]+'\n'+r'\end{enumerate}')
                else:
                    try:body=text_block_fragment(block)
                    except ValidationError as error:raise ValidationError(f'Блок {position}: '+ ' '.join(error.messages))
                    name=f'blocks/{position:03d}.tex';files[name]=body;sequence.append(r'\input{'+name+'}')
                    images.extend(block.get('images',[]))
            files['problems.tex']='\n'.join(sequence)+'\n'
    files['solutions.tex']=r'\clearpage\section*{Решения}\begin{enumerate}[leftmargin=*,itemsep=12pt]'+'\n'+'\n'.join(answers)+'\n'+r'\end{enumerate}'+'\n' if answers else '% No solutions included.\n'
    if getattr(worksheet,'is_problem',False):
        files['template.tex']=files['template.tex'].replace(r'{\small\sffamily \PlusfolioCircle\hfill \PlusfolioDate}\par',r'{\small\sffamily Plusfolio}\par').replace(r'{\small\sffamily Листок № \PlusfolioNumber}\par','')
    if images:
        from .document_content import attach_images
        attach_images(files,images,assets)
    from .tex_project import project_files
    try:project_files(files)
    except ValueError as error:raise ValidationError(str(error))
    if len(json.dumps(files,ensure_ascii=False).encode())>MAX_PROJECT_BYTES:raise ValidationError('Проект с рисунками превышает 8 МиБ.')
    return files


def flatten(project):
    # Only expand input statements from our trusted generated main/template/list files.
    # Task/solution fragments may define macros or use TikZ and remain untouched.
    def expand(name):
        text=project[name]
        if name.startswith(('tasks/','solutions/','blocks/')):return text
        return re.sub(r'\\input\{([^}]+)\}',lambda match:'\n% '+match.group(1)+'\n'+expand(match.group(1)),text)
    return expand('main.tex')


class CompilerUnavailable(APIException):
    status_code=503
    default_detail='Компилятор Tectonic или его изолированное окружение недоступны. Исходники TeX можно скачать.'


def compiler_environment():
    cache=Path(getattr(settings,'TEX_RESOURCE_DIR',None) or settings.LOCAL_DIR/'tectonic-cache');config=settings.LOCAL_DIR/'tectonic-config'
    cache.mkdir(mode=0o700,exist_ok=True);config.mkdir(mode=0o700,exist_ok=True)
    return {'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','TECTONIC_CACHE_DIR':str(cache),
            'XDG_CONFIG_HOME':str(config),'TECTONIC_UNTRUSTED_MODE':'1'}


def render_pdf(project,diagnostics=None,cache=True):
    from .tex_project import project_files,write_project
    from .tex_cache import pdf_cache
    from .tex_runtime import run_compiler,job_directory
    try:project_files(project)
    except ValueError as error:raise ValidationError(str(error))
    serialized=json.dumps(project,sort_keys=cache,ensure_ascii=False).encode()
    if len(serialized)>MAX_PROJECT_BYTES:raise ValidationError('Проект TeX превышает 8 МиБ.')
    artifacts=pdf_cache() if cache else None
    # The compiler version and complete authorized project identify the PDF, including solution masks.
    digest=hashlib.sha256(b'tectonic-0.17.0-project-v2\n'+serialized).hexdigest() if artifacts else None
    if artifacts:
        try:hit=artifacts.get(digest)
        except OSError:hit=None
        if hit and len(hit[0])<=MAX_PDF_BYTES:
            if diagnostics is not None:diagnostics.update(cache_hit=True,warnings=hit[1].get('warnings',[]))
            return hit[0]
    details=diagnostics if diagnostics is not None else {}
    def remember(pdf):
        if artifacts:
            try:artifacts.put(digest,pdf,{'warnings':details.get('warnings',[])})
            except OSError:pass  # A full/unwritable cache must not prevent downloading an already compiled PDF.
    if getattr(settings,'TEX_SOCKET',''):
        from .tex_remote import compile_project
        pdf=compile_project(settings.TEX_SOCKET,serialized,details)
        remember(pdf)
        return pdf
    del serialized
    compiler=shutil.which(str(getattr(settings,'TEX_COMPILER',settings.LOCAL_DIR/'tools'/'tectonic')))
    if not compiler:raise CompilerUnavailable()
    if not WORKERS.acquire(blocking=False):raise CompilerUnavailable('Сборка PDF занята. Повторите через несколько секунд.')
    try:
        with job_directory(settings.LOCAL_DIR/'tex-jobs') as directory:
            work=Path(directory)
            write_project(project,work)
            env=compiler_environment()
            env.update(XDG_CONFIG_HOME=str(work/'config'),XDG_CACHE_HOME=str(work/'cache'),XDG_DATA_HOME=str(work/'data'))
            if sys.platform=='darwin' and Path('/usr/bin/sandbox-exec').exists():
                def literal(value):return json.dumps(str(value))
                readable=[compiler,str(work),env['TECTONIC_CACHE_DIR'],env['XDG_CONFIG_HOME']]
                rules='(version 1)(allow default)(deny network*)'
                exceptions=' '.join('(require-not (subpath '+literal(Path(path).resolve())+'))' for path in readable)
                for private_root in ['/Users','/Volumes','/private/tmp','/private/var/folders','/opt','/Applications','/Library/Application Support']:
                    rules+='(deny file-read-data (require-all (subpath '+literal(private_root)+') '+exceptions+'))'
                rules+='(deny file-write* (require-all (require-not (subpath '+literal(work.resolve())+')) (require-not (literal "/dev/null"))))'
                profile=work/'compiler.sb';profile.write_text(rules)
                command=['/usr/bin/sandbox-exec','-f',str(profile),compiler,'-X','compile','--untrusted','--only-cached','--keep-logs','main.tex']
            elif sys.platform.startswith('linux') and shutil.which('bwrap'):
                (work/'passwd').write_text(f'plusfolio:x:{os.getuid()}:{os.getgid()}:Plusfolio:/work:/sbin/nologin\n')
                (work/'group').write_text(f'plusfolio:x:{os.getgid()}:\n')
                command=[shutil.which('bwrap'),'--unshare-all','--die-with-parent','--new-session','--dir','/usr']
                for path in ['/usr/lib','/usr/share/fonts','/usr/share/fontconfig','/lib','/lib64','/etc/fonts']:
                    if Path(path).exists():command+=['--ro-bind',path,path]
                command+=['--ro-bind',str(work/'passwd'),'/etc/passwd','--ro-bind',str(work/'group'),'/etc/group','--ro-bind',compiler,'/compiler','--ro-bind',env['TECTONIC_CACHE_DIR'],'/tex-cache','--bind',str(directory),'/work','--tmpfs','/tmp','--proc','/proc','--dev','/dev','--chdir','/work','--setenv','TECTONIC_CACHE_DIR','/tex-cache','--setenv','XDG_CONFIG_HOME','/work/config','--setenv','XDG_CACHE_HOME','/work/cache','--setenv','XDG_DATA_HOME','/work/data','/compiler','-X','compile','--untrusted','--only-cached','--keep-logs','main.tex']
            else:raise CompilerUnavailable('Для изоляции TeX нужен sandbox-exec (macOS) или bubblewrap (Linux).')
            try:returncode,output=run_compiler([sys.executable,str(ROOT/'tex_worker.py'),*command],work,env)
            except ValueError as error:raise ValidationError(str(error))
            if details is not None:
                log=output.decode(errors='replace')
                if (work/'main.log').exists():
                    with (work/'main.log').open(errors='replace') as stream:log+='\n'+stream.read(2*1024*1024)
                warnings=[line.strip()[:500] for line in log.splitlines() if any(marker in line.lower() for marker in ['overfull','underfull','missing character','warning:'])]
                details.update(cache_hit=False,warnings=list(dict.fromkeys(warnings))[:100])
            pdf=work/'main.pdf'
            if returncode or not pdf.exists():
                log=output.decode(errors='replace')
                errors=[line for line in log.splitlines() if line.startswith(('!','error:'))]
                detail=' '.join(errors[:2])[:350]
                raise ValidationError('Не удалось собрать PDF. '+(detail or 'Проверьте TeX и подготовку кэша Tectonic.'))
            with pdf.open('rb') as source:payload=source.read(MAX_PDF_BYTES+1)
            if not payload.startswith(b'%PDF-') or len(payload)>MAX_PDF_BYTES:raise ValidationError('Некорректный PDF.')
            remember(payload)
            return payload
    finally:WORKERS.release()


def response(project,kind,download=False,cache=True):
    if kind not in {'pdf','tex','project'}:raise ValidationError('Поддерживаются PDF, TeX и ZIP проекта.')
    if kind=='pdf':payload=render_pdf(project) if cache else render_pdf(project,cache=False);content_type='application/pdf';extension='pdf'
    elif kind=='tex':payload=flatten(project).encode();content_type='application/x-tex; charset=utf-8';extension='tex'
    else:
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            from .tex_project import project_files
            for name,source in project_files(project):archive.writestr(name,source)
            archive.writestr('README.txt','Compile main.tex with Tectonic 0.17.0 or a compatible XeLaTeX.\nVariables are in variables.tex, tasks in tasks/, permitted solutions in solutions/.\n')
        payload=buffer.getvalue();content_type='application/zip';extension='zip'
    result=HttpResponse(payload,content_type=content_type)
    result['Content-Disposition']=('attachment' if download or kind!='pdf' else 'inline')+'; filename="plusfolio-worksheet.'+extension+'"'
    result['X-Frame-Options']='SAMEORIGIN';result['X-Content-Type-Options']='nosniff'
    return result
