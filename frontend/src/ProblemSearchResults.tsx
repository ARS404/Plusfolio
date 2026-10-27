import {useEffect,useState} from 'react';
import {Search,Loader2,ArrowUpRight,Check} from 'lucide-react';
import EntityId from './EntityId';
import './problem-search.css';

type Hit={problem:any;match:'identifier'|'exact'|'text'|'semantic';fields:('statement'|'solution'|'metadata')[];excerpt:string};
type Reply={results:Hit[];semantic:boolean;pending:number;notice:string};
type Props={query:string;field?:string;fields?:string[];scope?:string;tags?:string[];topics?:string[];onOpen:(problem:any)=>void;onUse?:(problem:any)=>void;selected?:string[];compact?:boolean};
const names={identifier:'Совпадение ID',exact:'Текст совпадает',text:'Похожий текст',semantic:'Близко по смыслу'};

export default function ProblemSearchResults({query,field='all',fields=[],scope='library',tags=[],topics=[],onOpen,onUse,selected=[],compact=false}:Props){
 const [data,setData]=useState<Reply|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const body={q:query.trim(),field,fields,scope,limit:compact?5:20,tag:tags,topic:topics};
 const request=JSON.stringify(body),active=query.trim().length>=3||/^\d+$/.test(query.trim());
 useEffect(()=>{
  setData(null);setError('');setBusy(active);
  if(!active)return;
  const abort=new AbortController();
  const timer=setTimeout(async()=>{
   try{
    const csrf=document.cookie.split('; ').find(item=>item.startsWith('csrftoken='))?.split('=').slice(1).join('=')||'';
    const response=await fetch('/api/problem-search',{method:'POST',body:request,headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(csrf)},credentials:'same-origin',signal:abort.signal});
    const reply=await response.json();
    if(!response.ok)throw new Error(typeof reply.detail==='string'?reply.detail:'Не удалось выполнить поиск.');
    if(!abort.signal.aborted)setData(reply);
   }catch(error:any){if(!abort.signal.aborted)setError(error.message)}
   finally{if(!abort.signal.aborted)setBusy(false)}
  },700);
  return()=>{clearTimeout(timer);abort.abort()};
 },[request,active]);
 if(!active)return <p className="search-help">Введите хотя бы 3 символа или число. Можно вставить целое условие или решение.</p>;
 return <section className={'problem-search-results '+(compact?'compact':'')} aria-label="Результаты поиска по тексту" aria-busy={busy}>
  <div className="text-search-status" role="status">{busy?<><Loader2 size={16} className="spin"/>Ищем совпадения…</>:data?<><Search size={16}/>{compact?'Возможные совпадения':'Показано совпадений'}: {data.results.length}{data.semantic&&<span className="badge green">По тексту и смыслу</span>}</>:null}</div>
  {error&&<p className="error-panel" role="alert">{error}</p>}
  {data?.notice&&<p className="search-help">{data.notice}</p>}
  {data?.results.map(hit=><article key={hit.problem.id} className="text-search-hit">
   <div className="search-hit-heading"><EntityId value={hit.problem.public_id} copyable/><span className={'badge '+(hit.match==='exact'?'green':'gray')}>{names[hit.match]}</span>{hit.fields.length>0&&<small>{hit.fields.map(value=>value==='solution'?'Решение':value==='metadata'?'Название и описание':'Условие').join(' · ')}</small>}</div>
   <h4>{hit.problem.title}</h4>
   <p className="search-excerpt">{hit.excerpt||hit.problem.statement}</p>
   <div className="search-hit-actions"><button type="button" className="btn secondary" onClick={()=>onOpen(hit.problem)}>Открыть задачу<ArrowUpRight size={14}/></button>{onUse&&<button type="button" className="btn secondary" onClick={()=>onUse(hit.problem)}>{selected.includes(hit.problem.id)?<><Check size={14}/>Убрать из листка</>:'Использовать задачу'}</button>}</div>
  </article>)}
  {data&&!data.results.length&&<p className="search-help">Совпадений не найдено. Это не гарантирует, что в банке нет той же задачи с другой формулировкой.</p>}
  {data&&data.results.length>0&&<p className="search-help">Сравните числа, знаки и формулы. Похожесть — подсказка для проверки, задачи автоматически не объединяются.</p>}
 </section>;
}
