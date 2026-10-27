import {useEffect,useId,useMemo,useRef,useState} from 'react';
import {useCatalogueSearch,CatalogueSearchStatus} from './useCatalogueSearch';
import {matchesEntity} from './entitySearch';
import {CheckCheck,ChevronDown,Search,X} from 'lucide-react';

export type Choice={value:string;public_id?:string;extra_ids?:string[];label:string;description?:string;hidden?:boolean;pdfUrl?:string;searchId?:string};
type Props={label:string;options:Choice[];value:string[];onChange:(value:string[])=>void;placeholder?:string;required?:boolean;loading?:boolean;hint?:string;searchKind?:'circle'|'worksheet'|'topic';searchFilters?:Record<string,string|string[]>};

export default function MultiSelect({label,options,value,onChange,placeholder='Все значения',required=false,loading=false,hint,searchKind,searchFilters}:Props){
 const [query,setQuery]=useState('');const details=useRef<HTMLDetailsElement>(null);const labelId=useId();
 const known=useRef(new Map<string,Choice>());for(const option of options)known.current.set(option.value,option);
 const semantic=useCatalogueSearch(searchKind,query,searchFilters);
 const choices=useMemo(()=>{
  const ranks=new Map((semantic.data?.results||[]).map((hit,index)=>[hit.entity.id,index]));
  return options.filter(option=>!option.hidden&&(ranks.has(option.searchId||option.value)||(option.public_id?matchesEntity({...option,id:option.value},query,option.label,option.description||''):(option.label+' '+(option.description||'')).toLocaleLowerCase('ru-RU').includes(query.trim().toLocaleLowerCase('ru-RU')))))
   .sort((a,b)=>(ranks.get(a.searchId||a.value)??1000)-(ranks.get(b.searchId||b.value)??1000));
 },[options,query,semantic.data]);
 const selected=new Set(value);const allShown=choices.length>0&&choices.every(option=>selected.has(option.value));
 const close=()=>{if(details.current){details.current.open=false;details.current.querySelector('summary')?.focus()}};
 useEffect(()=>{const outside=(event:PointerEvent)=>{if(details.current?.open&&!details.current.contains(event.target as Node))details.current.open=false};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside)},[]);
 const toggle=(id:string)=>onChange(selected.has(id)?value.filter(item=>item!==id):[...value,id]);
 return <div className="filter-field multi-select"><span id={labelId}>{label}{required&&<span aria-hidden="true"> *</span>}</span><details ref={details} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();close()}}}>
  <summary aria-label={'Выбор: '+label} aria-describedby={labelId+'-value'}><CheckCheck size={16}/><span id={labelId+'-value'}>{value.length===1?known.current.get(value[0])?.label||'Выбрано: 1':value.length?'Выбрано: '+value.length:placeholder}</span><ChevronDown size={15}/></summary>
  <div className="multi-select-panel" aria-labelledby={labelId}>
   <div className="multi-select-search"><Search size={16}/><input type="search" aria-label={'Поиск: '+label} placeholder="Найти в списке" value={query} onChange={event=>setQuery(event.target.value)}/>{query&&<button type="button" className="icon-button" aria-label={'Очистить поиск: '+label} onClick={()=>setQuery('')}><X size={14}/></button>}</div>
   <CatalogueSearchStatus {...semantic}/>{hint&&<p className="multi-select-hint">{hint}</p>}
   <div className="multi-select-actions"><button type="button" className="btn text" disabled={!choices.length} onClick={()=>onChange(allShown?value.filter(id=>!choices.some(option=>option.value===id)):[...new Set([...value,...choices.map(option=>option.value)])])}>{allShown?'Снять видимые':'Выбрать видимые'}</button><span>{choices.length} в списке</span></div>
   <div className="multi-select-options" role="group" aria-label={label}>{choices.map(option=><div key={option.value} className={option.pdfUrl?'multi-select-document':''}><label className={selected.has(option.value)?'checked':''}><input type="checkbox" aria-label={'Выбрать: '+option.label} checked={selected.has(option.value)} onChange={()=>toggle(option.value)}/><span>{option.label}{option.description&&<small>{option.description}</small>}</span></label>{option.pdfUrl&&<div><a href={option.pdfUrl} target="_blank" rel="noreferrer" aria-label={'PDF: '+option.label}>PDF</a><a href={option.pdfUrl+'?download=1'} aria-label={'Скачать PDF: '+option.label}>↓</a></div>}</div>)}{!choices.length&&<p className="multi-select-empty">{loading?'Загружаем список…':'Ничего не найдено.'}</p>}</div>
   <div className="multi-select-footer"><span>{value.length?'Выбрано: '+value.length:placeholder}</span><div><button type="button" className="btn text" disabled={!value.length} onClick={()=>onChange([])}>Сбросить</button><button type="button" className="btn primary" onClick={close}>Готово</button></div></div>
  </div>
 </details>{value.length>0&&<div className="multi-select-chips">{value.map(id=><button type="button" key={id} aria-label={'Убрать: '+(known.current.get(id)?.label||id)} onClick={()=>onChange(value.filter(item=>item!==id))}><span>{known.current.get(id)?.label||'Выбрано'}</span><X size={12}/></button>)}</div>}</div>;
}
