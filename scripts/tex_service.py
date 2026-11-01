#!/usr/bin/env python3
"""Single-job compiler in a read-only, networkless container; no application secrets."""
import base64, json, os, socketserver, subprocess, sys, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOCKET=Path(os.environ.get('PLUSFOLIO_TEX_SOCKET','/run/plusfolio-tex/compiler.sock'))
LIMIT=8*1024*1024
GATE=threading.BoundedSemaphore(1)
sys.path.insert(0,str(ROOT/'backend'))
from core.tex_project import write_project
from core.tex_runtime import run_compiler,job_directory


def compile_project(project,diagnostic=False):
    with job_directory() as temporary:
        work=Path(temporary)
        write_project(project,work)
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','TECTONIC_CACHE_DIR':str(ROOT/'.local/tectonic-cache'),
             'XDG_CONFIG_HOME':str(work/'config'),'XDG_CACHE_HOME':str(work/'cache'),'XDG_DATA_HOME':str(work/'data'),'TECTONIC_UNTRUSTED_MODE':'1'}
        command=[sys.executable,str(ROOT/'backend/core/tex_worker.py'),str(ROOT/'.local/tools/tectonic'),
                 '-X','compile','--untrusted','--only-cached','--keep-logs','main.tex']
        returncode,output=run_compiler(command,work,env)
        pdf=work/'main.pdf'
        if returncode or not pdf.exists():
            if diagnostic:print('Trusted compiler startup check: '+output.decode(errors='replace')[:4000],file=sys.stderr,flush=True)
            raise ValueError('Не удалось собрать PDF. Проверьте TeX и доступность пакетов.')
        if pdf.stat().st_size>16*1024*1024:raise ValueError('PDF превышает 16 МиБ.')
        data=pdf.read_bytes()
        if not data.startswith(b'%PDF-'):raise ValueError('Invalid PDF')
        log=output.decode(errors='replace')
        if (work/'main.log').exists():
            with (work/'main.log').open(errors='replace') as stream:log+='\n'+stream.read(2*1024*1024)
        warnings=[line.strip()[:500] for line in log.splitlines() if any(word in line.lower() for word in ['overfull','underfull','missing character','warning:'])]
        return {'pdf':base64.b64encode(data).decode(),'warnings':list(dict.fromkeys(warnings))[:100]}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(30)
        try:
            header=self.rfile.readline(32)
            size=int(header)
            if not 1<=size<=LIMIT:raise ValueError('Invalid request size')
            payload=self.rfile.read(size)
            if len(payload)!=size:raise ValueError('Incomplete request')
            value=json.loads(payload)
            if value=={'health':True}:result={'ok':True}
            elif not GATE.acquire(blocking=False):result={'error':'Сборка PDF занята. Повторите позже.','busy':True}
            else:
                try:result=compile_project(value)
                finally:GATE.release()
        except Exception as exc:
            result={'error':str(exc) if isinstance(exc,ValueError) else 'Компилятор временно недоступен.'}
        body=json.dumps(result,ensure_ascii=False).encode();self.wfile.write(str(len(body)).encode()+b'\n'+body)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
    request_queue_size=4


if __name__=='__main__':
    if sys.platform!='linux':raise RuntimeError('This service requires the isolated Linux container')
    if os.environ.get('PLUSFOLIO_ISOLATED_TEX')!='1':raise RuntimeError('Use the supplied networkless compiler container')
    version=subprocess.check_output([str(ROOT/'.local/tools/tectonic'),'--version'],text=True).strip().lower()
    if version!='tectonic 0.17.0':raise RuntimeError('Wrong compiler version')
    variables='\n'.join(r'\newcommand{\Plusfolio'+key+'}{'+value+'}' for key,value in {
        'Circle':'Plusfolio','Date':'01.01.2026','Title':'Проверка сервера','Number':'1','Description':'Проверка готовности.'}.items())
    compile_project({'main.tex':r'\input{variables.tex}\input{template.tex}',
        'template.tex':(ROOT/'backend/core/tex_templates/math-a4-v2.tex').read_text(),'variables.tex':variables,
        'problems.tex':r'\begin{enumerate}\item Русский текст: $\sqrt{2}$. \begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture}\end{enumerate}',
        'solutions.tex':r'\begin{definition}[Проверка]Сохранение ресурсов.\end{definition}\section*{Решения}Проверка.'},diagnostic=True)
    print('Isolated TeX ready: Russian, formulas and TikZ verified',flush=True)
    SOCKET.parent.mkdir(parents=True,exist_ok=True);SOCKET.unlink(missing_ok=True)
    with Server(str(SOCKET),Handler) as server:
        SOCKET.chmod(0o660);server.serve_forever(poll_interval=.2)
