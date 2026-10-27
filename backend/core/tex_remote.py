"""Length-framed private Unix socket; this is never a public API endpoint."""
import base64,json,socket
from .documents import CompilerUnavailable
from django.core.exceptions import ValidationError


def request(socket_path,value):
    payload=json.dumps(value,ensure_ascii=False).encode()
    if len(payload)>8*1024*1024:raise ValidationError('Проект TeX превышает 8 МиБ.')
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(25);client.connect(socket_path);client.sendall(str(len(payload)).encode()+b'\n'+payload)
            with client.makefile('rb') as stream:
                size=int(stream.readline(32))
                if not 1<=size<=24*1024*1024:raise ValueError()
                body=stream.read(size)
                if len(body)!=size:raise ValueError()
                return json.loads(body)
    except (OSError,ValueError,TypeError):raise CompilerUnavailable('Изолированный компилятор недоступен.')


def compile_project(path,project,diagnostics=None):
    result=request(path,project)
    if result.get('busy'):raise CompilerUnavailable(result['error'])
    if result.get('error'):raise ValidationError(result['error'])
    try:pdf=base64.b64decode(result['pdf'],validate=True)
    except (KeyError,ValueError):raise CompilerUnavailable()
    if not pdf.startswith(b'%PDF-') or len(pdf)>16*1024*1024:raise CompilerUnavailable()
    if diagnostics is not None:diagnostics.update(cache_hit=False,warnings=result.get('warnings',[]))
    return pdf
