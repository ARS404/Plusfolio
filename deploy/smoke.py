"""Exercise the actual HTTPS/PG/Redis/SMTP/TeX/CPU stack with disposable data."""
import email,json,re,ssl,subprocess,time,urllib.request,urllib.error,urllib.parse,http.cookiejar
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import sys;sys.path.insert(0,str(ROOT/'scripts'))
import server
probe=subprocess.run(['docker','compose','version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
server.COMPOSE_TEST=(["docker","compose"] if probe.returncode==0 else ["docker-compose"])+['--env-file',str(server.STATE/'env'),'-f',str(ROOT/'compose.yml'),'-f',str(ROOT/'deploy/compose.test.yml')]
CONFIG=server.read_env();BASE=CONFIG['PUBLIC_URL'];CERT=server.STATE/'local-ca.crt'
context=ssl.create_default_context(cafile=str(CERT))
TOKEN=None
RUN=str(time.time_ns());DESTINATION='student-'+RUN+'@delivery.example.test';SHEET_TITLE='Проверка серверного листка '+RUN

def request(path,method='GET',data=None,opener=None,csrf=None):
    headers={'Referer':BASE+'/'}
    if TOKEN and path.startswith('/api/v1/'):headers['Authorization']='Bearer '+TOKEN
    if data is not None:headers['Content-Type']='application/json'
    if csrf:headers['X-CSRFToken']=csrf
    req=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
    try:
        with (opener.open(req,timeout=45) if opener else urllib.request.urlopen(req,context=context,timeout=45)) as response:
            raw=response.read();return response.status,json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw
    except urllib.error.HTTPError as error:raise AssertionError(f'{method} {re.sub(r"/accept/[^/]+","/accept/<redacted>",path.split("?")[0])} -> {error.code}') from None


def capture():
    result=subprocess.run(server.COMPOSE_TEST+['exec','-T','smtp-test','python','-c',"from pathlib import Path; import sys; rows=sorted(Path('/tmp/smtp-capture').glob('*.eml')); sys.stdout.buffer.write(rows[-1].read_bytes() if rows else b'')"],check=True,stdout=subprocess.PIPE,cwd=ROOT)
    return result.stdout


password=(server.STATE/'secrets/admin_password').read_text().strip()
_,auth=request('/api/v1/auth/token','POST',{'login':CONFIG['ADMIN_EMAIL'],'password':password,'name':'Deployment smoke','expires_in_days':1})
TOKEN=auth['access_token']
_,users=request('/api/v1/users');assert not any(row['email'].endswith('@plusfolio.example') for row in (users if isinstance(users,list) else users['results']))
_,circle=request('/api/v1/circles','POST',{'name':'Проверка установки','city':'Тестовый город','description':'Только синтетические данные'})
_,topics=request('/api/v1/topics');topic=next(row['id'] for row in topics['topics'] if row['parent_id'] and not row['archived'] and not row['is_other'])
_,problem=request('/api/v1/materials/problem','POST',{'title':'Проверка CPU и TikZ','statement':'Найдите длину гипотенузы при катетах 3 и 4.','solution':'По теореме Пифагора ответ равен 5.',
    'statement_tex':r'Найдите гипотенузу: $a=3$, $b=4$.\par\begin{tikzpicture}\draw (0,0)--(2,0)--(0,1.5)--cycle;\end{tikzpicture}',
    'solution_tex':r'По теореме Пифагора $c=\sqrt{3^2+4^2}=5$.','topics':[topic],'tags':[]})
_,sheet=request('/api/v1/materials/worksheet','POST',{'title':SHEET_TITLE,'description':'Русский текст, формулы и TikZ','topics':[topic],'tags':[],'problems':[problem['id']]})
_,_=request('/api/v1/worksheet-documents/'+sheet['document_id']+'/publish','POST',{'version':sheet['revision']})
_,_=request('/api/v1/circles/'+circle['id']+'/issues','POST',{'worksheet_ids':[sheet['id']],'issued_on':time.strftime('%Y-%m-%d')})
for solutions in [False,True]:
    _,pdf=request('/api/v1/materials/worksheet/'+sheet['id']+'/pdf'+('?solutions=1' if solutions else ''))
    assert pdf.startswith(b'%PDF-') and len(pdf)>1000
    (server.STATE/('with-solutions.pdf' if solutions else 'statement.pdf')).write_bytes(pdf)
print('PDF: condition and solution, Russian/formulas/TikZ compiled in isolated container')
_,toolchain=request('/api/v1/tex/toolchain');assert toolchain['compiler']['version']=='0.17.0'
_,_=request('/api/v1/invitations','POST',{'email':DESTINATION,'role':'student','circle_ids':[circle['id']]})
message=b''
for _ in range(30):
    message=capture()
    if DESTINATION.encode() in message:break
    time.sleep(1)
assert DESTINATION.encode() in message,'No invitation reached SMTP sink'
parsed=email.message_from_bytes(message)
text=parsed.get_payload(decode=True).decode(parsed.get_content_charset() or 'utf-8')
match=re.search(re.escape(BASE)+r'/#/accept/([A-Za-z0-9_-]+)',text);assert match,'Wrong external invitation URL'
link='/api/accept/'+match[1]
jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),urllib.request.HTTPCookieProcessor(jar))
_,invite=request(link,opener=opener)
_,student=request(link,'POST',{'name':'Тестов Тест Тестович','graduation_year':2035,'no_patronymic':False,'password':'Synthetic-student-pass-2040!'},opener,invite['csrf'])
assert 'student' in student['user']['roles']
_,students=request('/api/v1/circles/'+circle['id']+'/members');assert any(row['user_public_id']==student['user']['public_id'] for row in students)
print('Invitation: queued -> SMTP -> HTTPS link -> registration -> automatic enrollment')
for _ in range(90):
    _,found=request('/api/v1/catalogue-search?kind=worksheet&q='+urllib.parse.quote(SHEET_TITLE)+'&scope=mine')
    if found['semantic'] and not found['pending']:break
    time.sleep(1)
assert found['semantic'] and not found['pending'],'CPU index was not ready'
assert found['results'][0]['entity']['id']==sheet['id']
_,found=request('/api/v1/problem-search','POST',{'q':'катеты прямоугольного треугольника','field':'statement','mode':'hybrid'})
assert found['semantic'],'CPU search did not participate'
_,docs=request('/api/v1/documentation?audience=robot');assert docs['mandatory_instructions']
_,spec=request('/api/v1/openapi.json');assert '/catalogue-search' in spec['paths']
print('Search/API: real CPU model, PostgreSQL vector/trigram indexes, documentation and OpenAPI ready')
_,_=request('/api/v1/auth/tokens/current','DELETE')
print('SERVER SMOKE PASSED')
