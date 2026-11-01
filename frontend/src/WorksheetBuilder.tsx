import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowDown,ArrowUp,BookOpen,Copy,FileText,GripVertical,Loader2,Plus,Search,Trash2} from 'lucide-react';
import ContentEditor from './ContentEditor';
import MultiSelect from './MultiSelect';
import {PdfCanvas} from './PdfDocument';
import {blockStyles,builderProblem,moveBlock,numberedBlocks,serializeWorksheetBlocks,type BuilderProblem,type WorksheetBlock} from './worksheetBlocks';

type Props={numberingStart:0|1;onNumberingStartChange:(value:0|1)=>void;tags?:any[];onUploadingChange?:(busy:boolean)=>void;value:WorksheetBlock[];onChange:(blocks:WorksheetBlock[])=>void;initialProblems:any[];title:string;description:string;api:(path:string,method?:string,data?:any,signal?:AbortSignal)=>Promise<any>};
export default function WorksheetBuilder({value,onChange,initialProblems=[],title,description,api,onUploadingChange,tags=[],numberingStart,onNumberingStartChange}:Props){
 const [known,setKnown]=useState<Record<string,BuilderProblem>>(()=>Object.fromEntries(initialProblems.map(problem=>[problem.id,builderProblem(problem)])));
 const [picker,setPicker]=useState<number|null>(null),[query,setQuery]=useState(''),[choices,setChoices]=useState<BuilderProblem[]>([]),[searching,setSearching]=useState(false),[error,setError]=useState('');
 const [tag,setTag]=useState<string[]>([]),[notice,setNotice]=useState('');
 const [uploads,setUploads]=useState(0);
 const [expanded,setExpanded]=useState<Record<string,boolean>>({});
 const [preview,setPreview]=useState(''),[previewing,setPreviewing]=useState(false),[solutions,setSolutions]=useState(false),[snapshot,setSnapshot]=useState<symbol|null>(null);
 const latest=useRef(value);latest.current=value;
 const drag=useRef<number|null>(null),abortPreview=useRef<AbortController|null>(null);
 const draftVersion=useMemo(()=>Symbol(),[title,description,value,numberingStart,solutions]);
 useEffect(()=>()=>{abortPreview.current?.abort()},[]);
 useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview)},[preview]);
 useEffect(()=>{
  if(picker===null){setChoices(current=>current.length?[]:current);return}const controller=new AbortController();setSearching(true);setError('');setChoices([]);setNotice('');
  const text=query.trim();
  if(text&&text.length<3&&!/^\d+$/.test(text)){setSearching(false);setNotice('Введите хотя бы 3 символа или ID задачи.');return()=>controller.abort()}
  const timer=setTimeout(async()=>{
   try{
    const params=new URLSearchParams();tag.forEach(value=>params.append('tag',value));
    const reply=await (text?api('/problem-search','POST',{q:text,field:'all',scope:'library',mode:'hybrid',limit:40,tag},controller.signal):api('/materials/problem?'+params,'GET',undefined,controller.signal));
    const rows=text?reply.results.map((hit:any)=>hit.problem):reply;
    if(!controller.signal.aborted){setChoices(rows.map(builderProblem));setNotice(text?reply.notice||'':'Показаны доступные задачи. Поиск работает по ID, условию и решению.')}
   }catch(error:any){if(!controller.signal.aborted)setError(error.message)}finally{if(!controller.signal.aborted)setSearching(false)}
  },500);
  return()=>{clearTimeout(timer);controller.abort()};
 },[query,picker,JSON.stringify(tag)]);
 const canInsert=value.length<300;
 const insert=(index:number,block:WorksheetBlock)=>{if(!canInsert)return;const key=crypto.randomUUID();const next=[...value];next.splice(index,0,{...block,_key:key});setExpanded(old=>({...old,[key]:true}));onChange(next)};
 const isExpanded=(block:WorksheetBlock,index:number)=>expanded[block._key||String(index)]??(index<2);
 const toggle=(block:WorksheetBlock,index:number)=>{const key=block._key||String(index);setExpanded(old=>({...old,[key]:!isExpanded(block,index)}))};
 const patch=(index:number,block:WorksheetBlock)=>onChange(value.map((item,position)=>position===index?block:item));
 const patchContent=(key:string|undefined,index:number,content:any)=>{const current=latest.current;const position=key?current.findIndex(block=>block._key===key):index;if(position<0||current[position]?.kind!=='text')return;onChange(current.map((block,i)=>i===position?{...block,...content}:block))};
 const remove=(index:number)=>{
  const block=value[index];onChange(value.filter((_,position)=>position!==index));
  const key=block._key||String(index);setExpanded(old=>{if(!(key in old))return old;const next={...old};delete next[key];return next});
  if(block.kind==='problem')setKnown(old=>{const next={...old};delete next[block.problem_id];return next});
 };
 const addText=(index:number)=>insert(index,{kind:'text',style:'plain',title:'',text:'',tex:'',images:[]});
 const controls=(index:number)=><div className="block-insert"><button type="button" className="btn text" disabled={!canInsert} onClick={()=>addText(index)}><Plus size={14}/>Текст</button><button type="button" className="btn text" disabled={!canInsert} onClick={()=>{setPicker(index);setQuery('')}}><Plus size={14}/>Задача</button></div>;
 const compile=async()=>{
  abortPreview.current?.abort();const controller=new AbortController();abortPreview.current=controller;
  setPreviewing(true);setError('');const compiled=draftVersion;
  const body=JSON.stringify({title,description,blocks:serializeWorksheetBlocks(value),numbering_start:numberingStart,solutions});
  try{
   const csrf=document.cookie.split('; ').find(item=>item.startsWith('csrftoken='))?.split('=').slice(1).join('=')||'';
   const response=await fetch('/api/worksheets/preview',{method:'POST',signal:controller.signal,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(csrf)},body});
   if(!response.ok){const value=await response.json();throw new Error(value.detail||'Не удалось собрать PDF.')}
   const pdf=await response.blob();if(!controller.signal.aborted){setPreview(URL.createObjectURL(pdf));setSnapshot(compiled)}
  }catch(error:any){if(!controller.signal.aborted)setError(error.message)}finally{if(!controller.signal.aborted)setPreviewing(false)}
 };
 useEffect(()=>{if(picker!==null)document.querySelector('.builder-picker')?.scrollIntoView({block:'nearest'})},[picker]);
 const selected=useMemo(()=>new Set(value.flatMap(block=>block.kind==='problem'?[block.problem_id]:[])),[value]);
 const availableChoices=useMemo(()=>choices.filter(problem=>!selected.has(problem.id)),[choices,selected]);
 const numbered=useMemo(()=>numberedBlocks(value,numberingStart),[value,numberingStart]);
 const tagOptions=useMemo(()=>tags.filter(tag=>tag.kind==='problem').map(tag=>({value:String(tag.id),label:tag.name,public_id:tag.public_id})),[tags]);
 return <section className="worksheet-builder">
  <div className="builder-heading"><div><h3>Содержание листка</h3><p>Текст и задачи в порядке печати. Нумеруются только задачи.</p></div><span>{value.length} блоков · {selected.size} задач</span></div>
  <div className="builder-numbering"><label>Нумерация задач<select aria-label="Начинать нумерацию задач" value={numberingStart} onChange={event=>onNumberingStartChange(Number(event.target.value) as 0|1)}><option value={1}>С 1</option><option value={0}>С 0</option></select></label><span>Задачи без галочки остаются в листке и PDF, но не учитываются в плюснике.</span></div>
  {controls(0)}
  <div className="worksheet-block-list">{numbered.map(({block,number},index)=><div key={block._key||index} onDragOver={event=>{if(drag.current!==null)event.preventDefault()}} onDrop={event=>{if(drag.current!==null){event.preventDefault();onChange(moveBlock(value,drag.current,index));drag.current=null}}}>
   <article className={'worksheet-edit-block '+(block.kind==='text'?'text-'+block.style:'problem-block')}>
    <div className="block-heading"><span className="block-drag" draggable onDragStart={event=>{drag.current=index;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',String(index))}} onDragEnd={()=>{drag.current=null}} aria-label={'Переместить блок '+(index+1)}><GripVertical size={16}/></span><button type="button" className="block-expand" aria-expanded={isExpanded(block,index)} onClick={()=>toggle(block,index)}>{block.kind==='problem'?'Задача '+number:(blockStyles[block.style]||'Текст')+(block.title?' · '+block.title:'')}</button>{block.kind==='problem'&&<label className="block-journal-toggle" title="Включать задачу в таблицу сдачи и подсчёт прогресса"><input type="checkbox" aria-label={'Включать задачу '+number+' в плюсник'} checked={block.include_in_journal!==false} onChange={event=>patch(index,{...block,include_in_journal:event.target.checked})}/>В плюсник</label>}<div className="block-row-actions"><button type="button" className="icon-button" aria-label={'Блок '+(index+1)+' выше'} disabled={index===0} onClick={()=>onChange(moveBlock(value,index,index-1))}><ArrowUp size={16}/></button><button type="button" className="icon-button" aria-label={'Блок '+(index+1)+' ниже'} disabled={index===value.length-1} onClick={()=>onChange(moveBlock(value,index,index+1))}><ArrowDown size={16}/></button>{block.kind==='text'&&<button type="button" className="icon-button" disabled={!canInsert} aria-label={'Копировать блок '+(index+1)} onClick={()=>insert(index+1,{...block,images:block.images.map(image=>({...image}))})}><Copy size={16}/></button>}<button type="button" className="icon-button danger" aria-label={'Удалить блок '+(index+1)} onClick={()=>remove(index)}><Trash2 size={16}/></button></div></div>
    {block.kind==='problem'?<div className="builder-problem" hidden={!isExpanded(block,index)}><BookOpen size={20}/><div><h4>{known[block.problem_id]?.title||'Задача'}</h4><span>{known[block.problem_id]?.public_id||block.problem_id}</span><p>{known[block.problem_id]?.statement}</p></div></div>:<div className="block-body" hidden={!isExpanded(block,index)}><div className="block-format-row"><label>Оформление<select aria-label={'Оформление блока '+(index+1)} value={block.style} onChange={event=>patch(index,{...block,style:event.target.value})}>{Object.entries(blockStyles).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>Заголовок<input aria-label={'Заголовок блока '+(index+1)} value={block.title} maxLength={180} placeholder="Необязательно" onChange={event=>patch(index,{...block,title:event.target.value})}/></label></div><ContentEditor onUploadingChange={busy=>{setUploads(count=>Math.max(0,count+(busy?1:-1)));onUploadingChange?.(busy)}} label={'Текст блока '+(index+1)} value={{text:block.text,tex:block.tex,images:block.images}} onChange={content=>patchContent(block._key,index,content)}/></div>}
   </article>{controls(index+1)}
  </div>)}</div>
  {!value.length&&<p className="builder-empty">Добавьте введение, определение или первую задачу. Листок может содержать только теорию.</p>}
  {picker!==null&&<section className="builder-picker"><div className="builder-picker-heading"><h4>Вставить задачу · позиция {picker+1}</h4><button type="button" className="btn text" onClick={()=>setPicker(null)}>Закрыть выбор</button></div><MultiSelect label="Теги задач" value={tag} onChange={setTag} placeholder="Все теги" options={tagOptions}/><div className="search-field"><Search size={16}/><input maxLength={12000} aria-label="Найти задачу для блока" value={query} onChange={event=>setQuery(event.target.value)} placeholder="ID, условие или решение"/></div>{notice&&<p className="search-help">{notice}</p>}{searching?<p><Loader2 size={16} className="spin"/> Ищем задачи…</p>:<div className="builder-problem-choices">{availableChoices.slice(0,40).map(problem=><button type="button" key={problem.id} disabled={!canInsert} onClick={()=>{setKnown(old=>({...old,[problem.id]:problem}));insert(picker,{kind:'problem',problem_id:problem.id,include_in_journal:true});setPicker(null)}}><span>{problem.public_id}</span><b>{problem.title}</b><Plus size={16}/></button>)}{!availableChoices.length&&<p>Доступных новых задач не найдено.</p>}</div>}</section>}
  <div className="builder-preview-toolbar"><button type="button" className="btn secondary" disabled={previewing||!value.length||uploads>0} onClick={()=>void compile()}>{previewing?<Loader2 size={16} className="spin"/>:<FileText size={16}/>}Обновить PDF</button><label className="inline-check"><input type="checkbox" checked={solutions} onChange={event=>setSolutions(event.target.checked)}/>С доступными решениями</label>{preview&&snapshot!==draftVersion&&<span className="builder-preview-stale" role="status">Содержание изменено — обновите PDF</span>}</div>
  {error&&<p className="error-panel" role="alert">{error}</p>}
  {preview&&<section className="builder-pdf-preview"><PdfCanvas url={preview} title={title||'Предпросмотр листка'}/><a className="btn text" href={preview} download="worksheet-preview.pdf">Скачать предпросмотр</a></section>}
 </section>
}
