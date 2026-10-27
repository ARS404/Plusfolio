"""Read public problems.ru catalog pages without executing or displaying their HTML."""
from collections import Counter
from datetime import datetime,timezone
from html import unescape
from html.parser import HTMLParser
import hashlib,json,math,re,time
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urljoin,urlparse,parse_qs
from urllib.request import Request,urlopen
from urllib.robotparser import RobotFileParser

BASE='https://problems.ru'
AGENT='PlusfolioEducationalImport/0.1 (local noncommercial math-circle demo)'
COPYRIGHT=BASE+'/about_system.php'
MAX_BYTES=8*1024*1024

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2));temporary.replace(path)

class Unsupported(ValueError):pass

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.math_depth=0;self.math_wrappers=[];self.in_math=False;self.links=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in {'img','svg','math','table','script','style','iframe','object','embed'}:raise Unsupported('requires_'+tag)
        if tag=='font' and attrs.get('face','').casefold()=='symbol':raise Unsupported('symbol_font')
        if tag in {'sup','sub'}:
            wrapper=not self.in_math
            if wrapper:self.parts.append('$ {}');self.in_math=True
            self.math_wrappers.append(wrapper)
            self.parts.append('^{' if tag=='sup' else '_{');self.math_depth+=1
        elif tag in {'br','p','div','li','h4','blockquote'}:self.parts.append('\n')
        elif tag=='a':
            href=attrs.get('href','')
            if href and not href.startswith('#'):
                url=urljoin(BASE+'/',href)
                if urlparse(url).scheme not in {'http','https'}:raise Unsupported('unsafe_link')
                self.links.append(url)
            else:self.links.append('')
        elif tag not in {'a','b','strong','i','em','span','font','nobr','small','big','u','center','ul','ol','tt','code','h4','blockquote','sup','sub'}:
            raise Unsupported('unsupported_tag_'+tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in {'br','p'}:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in {'sup','sub'}:
            if not self.math_depth:raise Unsupported('unbalanced_math')
            self.parts.append('}');self.math_depth-=1
            if self.math_wrappers.pop():self.parts.append('$');self.in_math=False
        elif tag in {'p','div','li','h4','blockquote'}:self.parts.append('\n')
        elif tag=='a' and self.links:
            url=self.links.pop()
            if url:self.parts.append(' ('+url+')')
    def handle_data(self,data):
        # Catalogs mix TeX $/$$ formulae with HTML superscripts. Keep one math scope.
        for part in re.split(r'((?<!\\)\${1,2})',data.replace('\xa0',' ')):
            if part in {'$','$$'}:
                if not self.math_depth:self.parts.append('$');self.in_math=not self.in_math
            else:self.parts.append(part)
    def value(self):
        if self.math_depth or self.in_math:raise Unsupported('unbalanced_math')
        text=re.sub(r'\$([^$]*)\$',lambda match:'$'+' '.join(match.group(1).split())+'$',''.join(self.parts))
        for formula in re.findall(r'\$([^$]*)\$',text):
            depth=0
            for brace in re.findall(r'(?<!\\)[{}]',formula):
                depth+=1 if brace=='{' else -1
                if depth<0:raise Unsupported('unbalanced_formula')
            if depth:raise Unsupported('unbalanced_formula')
        lines=[re.sub(r'[\t\r\f\v ]+',' ',line).strip() for line in text.split('\n')]
        return re.sub(r'\n{3,}','\n\n','\n'.join(lines)).strip()

def plain(html):
    parser=Text();parser.feed(html);parser.close();return parser.value()

def caption_end(block):
    depth=0
    for match in re.finditer(r'</?table\b[^>]*>',block,re.I):
        depth+=-1 if match.group(0).startswith('</') else 1
        if depth==0:return match.end()
    raise Unsupported('missing_caption')

def parse_catalog(html,subject):
    if not re.search(r'<title>\s*Каталог по темам\s*</title>',html,re.I):raise ValueError('Unexpected catalog page')
    markers=list(re.finditer(r'<a\s+name=["\']problem_(\d+)["\'][^>]*>\s*</a>',html,re.I))
    rows=[];skipped=[]
    for index,marker in enumerate(markers):
        identifier=marker.group(1);block=html[marker.end():markers[index+1].start() if index+1<len(markers) else len(html)]
        try:
            end=caption_end(block);caption=block[:end]
            body=re.split(r'<table\s+class=["\']problemfootertable["\']',block[end:],maxsplit=1,flags=re.I)[0]
            parts=re.split(r'<h3\b[^>]*>(.*?)</h3>',body,flags=re.S|re.I)
            statement=plain(parts[0]);answers=[];has_solution=False
            for position in range(1,len(parts),2):
                heading=plain(parts[position]);text=plain(parts[position+1])
                if not re.search('решени|ответ|указани|подсказк',heading,re.I):raise Unsupported('unknown_section')
                if text:answers.append(heading+':\n'+text)
                if text and re.search('решени',heading,re.I):has_solution=True
            solution='\n\n'.join(answers)
            if not statement or not solution:raise Unsupported('missing_statement_or_answer')
            if len(statement)>30000 or len(solution)>30000:raise Unsupported('content_too_long')
            subjects=[]
            for href,name in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',caption,re.S|re.I):
                url=urlparse(urljoin(BASE+'/',unescape(href)));ids=parse_qs(url.query).get('parent',[])
                if url.path=='/view_by_subject_new.php' and ids and ids[0].isdigit():subjects.append({'id':ids[0],'name':plain(name)})
            if not subjects:raise Unsupported('missing_topics')
            raw=re.sub('<[^>]+>',' ',caption);difficulty=re.search(r'Сложность:\s*([^<\n]+)',unescape(raw));grades=re.search(r'Классы:\s*([\d, ]+)',unescape(raw))
            rows.append({'source_id':identifier,'source_url':BASE+'/view_problem_details_new.php?id='+identifier,
                'title':'','statement':statement,'solution':solution,'topics':subjects,'catalog_subjects':[str(subject)],
                'has_detailed_solution':has_solution,'difficulty':difficulty.group(1).strip() if difficulty else '',
                'grades':[int(value) for value in re.findall(r'\d+',grades.group(1))] if grades else [],
                'content_sha256':hashlib.sha256((statement+'\n\n'+solution).encode()).hexdigest()})
        except Unsupported as error:skipped.append({'source_id':identifier,'reason':str(error)})
    return rows,skipped,len(markers)

class Fetcher:
    def __init__(self,cache,offline=False):
        self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True);self.offline=offline
        self.state=self.cache/'fetch-state.json';self.delay=20.;self.robot=RobotFileParser();self.requests=0
        path=self.cache/'robots.json'
        if path.exists() and (offline or time.time()-path.stat().st_mtime<86400):robots=json.loads(path.read_text())
        elif offline:raise ValueError('Offline cache has no robots.txt')
        else:
            robots={'text':self.request(BASE+'/robots.txt',check=False),'fetched_at':now()};save_json(path,robots)
        self.robot.parse(robots['text'].splitlines());self.delay=max(20.,float(self.robot.crawl_delay(AGENT) or self.robot.crawl_delay('*') or 0))
    def request(self,url,data=None,check=True):
        if self.offline:raise ValueError('Network disabled')
        if urlparse(url).netloc!='problems.ru':raise ValueError('Unexpected source host')
        if check and not self.robot.can_fetch(AGENT,url):raise ValueError('robots.txt disallows this URL')
        for attempt in range(3):
            state=json.loads(self.state.read_text()) if self.state.exists() else {}
            remaining=self.delay-(time.time()-state.get('last_request_epoch',0))
            if remaining>0:time.sleep(remaining)
            save_json(self.state,{'last_request_epoch':time.time()})
            try:
                with urlopen(Request(url,data=data,headers={'User-Agent':AGENT,'Accept':'text/html,text/plain;q=0.8'}),timeout=45) as response:
                    payload=response.read(MAX_BYTES+1)
                    if len(payload)>MAX_BYTES:raise ValueError('Source page too large')
                    self.requests+=1
                    return payload.decode(response.headers.get_content_charset() or 'utf-8')
            except (HTTPError,URLError,TimeoutError) as error:
                if attempt==2 or isinstance(error,HTTPError) and error.code in {401,403,404}:raise
                time.sleep(20*(attempt+1))
    def catalog(self,subject,start):
        if not str(subject).isdigit() or start<0 or start%100:raise ValueError('Invalid catalog selection')
        path=self.cache/f'catalog-{subject}-{start}.html'
        if path.exists():return path.read_text()
        data=urlencode({'viewing_params[view_amount]':'100','viewing_params[view_solutions]':'on','viewing_params[submit]':'Показать!'}).encode()
        content=self.request(BASE+'/view_by_subject_new.php?'+urlencode({'parent':subject,'start':start}),data)
        path.write_text(content);return content

def balanced(buckets,limit):
    selected={};positions={key:0 for key in buckets}
    while len(selected)<limit:
        progress=False
        for key,rows in buckets.items():
            while positions[key]<len(rows):
                row=rows[positions[key]];positions[key]+=1
                if row['source_id'] in selected:
                    existing=selected[row['source_id']]
                    existing['catalog_subjects']=list(dict.fromkeys(existing['catalog_subjects']+row['catalog_subjects']));continue
                selected[row['source_id']]={**row,'catalog_subjects':list(row['catalog_subjects'])};progress=True;break
            if len(selected)==limit:break
        if not progress:break
    return list(selected.values())

def collect(fetcher,subjects,limit,max_pages=35):
    buckets={key:[] for key in subjects};finished=set();skipped=[];pages=[]
    for round_index in range(math.ceil(max_pages/len(subjects))):
        for subject in subjects:
            if subject in finished:continue
            if len(pages)>=max_pages:break
            html=fetcher.catalog(subject,round_index*100);rows,rejected,count=parse_catalog(html,subject)
            buckets[subject].extend(rows);skipped.extend(rejected)
            pages.append({'subject_id':subject,'start':round_index*100,'parsed':count,'accepted':len(rows),'sha256':hashlib.sha256(html.encode()).hexdigest()})
            if count<100:finished.add(subject)
            print(f'Раздел {subject}: страниц {len(pages)}, пригодных задач {len(buckets[subject])}; уникальных всего {len(balanced(buckets,limit))}',flush=True)
            if all(buckets.values()) and len(balanced(buckets,limit))==limit:break
        chosen=balanced(buckets,limit)
        if len(chosen)==limit:break
        if finished==set(subjects):break
    if len(chosen)!=limit:raise ValueError(f'Найдено {len(chosen)} полных текстовых задач из {limit}; увеличьте --max-pages или дополните кэш.')
    return {'schema_version':1,'source':'problems.ru','fetched_at':now(),'copyright_url':COPYRIGHT,
        'policy':'Personal noncommercial use and math circles; retain problems.ru links and task IDs. Commercial use requires separate permission.',
        'selection':{'requested':limit,'subjects':subjects,'pages':pages,'skipped':dict(Counter(row['reason'] for row in skipped))},'problems':chosen}
