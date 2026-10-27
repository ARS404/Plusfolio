import EntityId from './EntityId';
import {useCatalogueSearch,CatalogueSearchStatus} from './useCatalogueSearch';
import {matchesEntity} from './entitySearch';
import React,{useEffect,useId,useMemo,useRef,useState} from 'react';
import {ChevronDown,ChevronRight,FolderTree,Search,X} from 'lucide-react';

type Topic={id:string;public_id?:string;name:string;parent_id:string|null;is_other:boolean;archived:boolean;sort_order:number};
type Props={topics:Topic[];value:string[];onChange:(value:string[])=>void;label?:string};

export default function TopicTreeFilter({topics,value,onChange,label='Темы задач'}:Props){
 const [query,setQuery]=useState(''),[expanded,setExpanded]=useState<Set<string>>(new Set());
 const semantic=useCatalogueSearch('topic',query);
 const details=useRef<HTMLDetailsElement>(null);const labelId=useId();
 const index=useMemo(()=>{
  const nodes=new Map(topics.map(topic=>[topic.id,topic]));
  const children=new Map<string,Topic[]>();const parents=new Map<string,string[]>();const paths=new Map<string,string>();
  for(const topic of topics){
   if(topic.parent_id){const siblings=children.get(topic.parent_id)||[];siblings.push(topic);children.set(topic.parent_id,siblings)}
   const chain:Topic[]=[];const seen=new Set<string>();let current:Topic|undefined=topic;
   while(current&&current.parent_id&&!seen.has(current.id)){seen.add(current.id);chain.unshift(current);current=nodes.get(current.parent_id)}
   paths.set(topic.id,chain.map(node=>node.name).join(' / '));parents.set(topic.id,chain.slice(0,-1).map(node=>node.id));
  }
  for(const siblings of children.values())siblings.sort((a,b)=>Number(a.is_other)-Number(b.is_other)||a.sort_order-b.sort_order||a.name.localeCompare(b.name,'ru'));
  const roots=topics.filter(topic=>!topic.parent_id).flatMap(root=>children.get(root.id)||[]);
  const sizes=new Map<string,number>();
  for(const topic of topics){if(!topic.parent_id)continue;for(const id of [topic.id,...(parents.get(topic.id)||[])])sizes.set(id,(sizes.get(id)||0)+1)}
  return {nodes,children,parents,paths,roots,sizes};
 },[topics]);
 const selected=new Set(value);
 const partial=new Set(value.flatMap(id=>index.parents.get(id)||[]));
 const visible=useMemo(()=>{
  if(!query.trim())return null;
  const needle=query.trim().toLocaleLowerCase('ru-RU');const result=new Set<string>();const found=new Set((semantic.data?.results||[]).map(hit=>hit.entity.id));
  for(const topic of topics){if(!topic.parent_id||!found.has(topic.id)&&!matchesEntity(topic,needle,index.paths.get(topic.id)||''))continue;result.add(topic.id);for(const parent of index.parents.get(topic.id)||[])result.add(parent)}
  return result;
 },[index,query,topics,semantic.data]);
 const normalize=(ids:string[])=>{const unique=[...new Set(ids)];const choices=new Set(unique);return unique.filter(id=>index.nodes.get(id)?.parent_id&&!(index.parents.get(id)||[]).some(parent=>choices.has(parent)))};
 const toggle=(id:string)=>onChange(selected.has(id)?value.filter(item=>item!==id):normalize([...value,id]));
 const close=()=>{if(details.current){details.current.open=false;details.current.querySelector('summary')?.focus()}};
 useEffect(()=>{
  const outside=(event:PointerEvent)=>{if(details.current?.open&&!details.current.contains(event.target as Node))details.current.open=false};
  document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);
 },[]);
 const render=(nodes:Topic[],depth=0):React.ReactNode=><ul className="topic-filter-level">{nodes.filter(node=>!visible||visible.has(node.id)).map(node=>{
  const parent=(index.parents.get(node.id)||[]).find(id=>selected.has(id));
  const checked=selected.has(node.id)||!!parent;const mixed=!checked&&partial.has(node.id);
  const children=index.children.get(node.id)||[];const open=!!visible||expanded.has(node.id);const path=index.paths.get(node.id)||node.name;
  return <li key={node.id}><div className={'topic-filter-row'+(checked?' checked':'')+(mixed?' partial':'')+(parent?' inherited':'')} style={{'--topic-depth':depth} as React.CSSProperties}>
   {children.length?<button type="button" className="topic-filter-toggle" aria-label={(open?'Свернуть ветку ':'Раскрыть ветку ')+path} aria-expanded={open} onClick={()=>setExpanded(current=>{const next=new Set(current);next.has(node.id)?next.delete(node.id):next.add(node.id);return next})}>{open?<ChevronDown size={15}/>:<ChevronRight size={15}/>}</button>:<span className="topic-filter-spacer"/>}
   <label><input type="checkbox" aria-label={'Выбрать тему '+path} aria-checked={mixed?'mixed':checked} checked={checked} disabled={!!parent} ref={input=>{if(input)input.indeterminate=mixed}} onChange={()=>toggle(node.id)}/><span title={parent?'Включено выбранной веткой «'+index.nodes.get(parent)?.name+'»':path}>{node.name}</span><EntityId value={node.public_id}/></label>
   {node.archived&&<small className="topic-filter-archived">Архив</small>}{selected.has(node.id)&&<small className="topic-filter-branch">{(index.sizes.get(node.id)||1)>1?'Вся ветка':'Выбрано'}</small>}
  </div>{children.length>0&&open&&render(children,depth+1)}</li>;
 })}</ul>;
 return <div className="filter-field analytics-topic topic-tree-filter"><span id={labelId}>{label}</span><details ref={details} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();close();details.current?.querySelector('summary')?.focus()}}}>
 <summary aria-label={'Выбор: '+label} aria-describedby={labelId+'-selection'}><FolderTree size={16}/><span id={labelId+'-selection'}>{value.length?'Выбрано веток: '+value.length:'Все темы'}</span><ChevronDown size={15}/></summary>
 <div className="topic-filter-panel" aria-labelledby={labelId}><div className="topic-filter-search"><Search size={16}/><input type="search" aria-label="Поиск в дереве тем" placeholder="Название, путь или ID TOP-123" value={query} onChange={event=>setQuery(event.target.value)}/>{query&&<button type="button" className="icon-button" aria-label="Очистить поиск тем" onClick={()=>setQuery('')}><X size={14}/></button>}</div>
 <CatalogueSearchStatus {...semantic}/><p className="topic-filter-hint">Можно выбрать несколько веток. Каждая включает все подтемы. Чтобы выбрать часть ветки, сначала снимите выбор с родителя.</p>
 <div className="topic-filter-tree" role="group" aria-label={'Дерево: '+label}>{render(index.roots)}{visible&&!index.roots.some(node=>visible.has(node.id))&&<p className="topic-filter-empty">Темы не найдены.</p>}{!topics.length&&<p className="topic-filter-empty">Загружаем дерево тем…</p>}</div>
 <div className="topic-filter-footer"><span>{value.length?'Выбрано веток: '+value.length:'Без фильтра — все темы'}</span><div><button type="button" className="btn text" disabled={!value.length} onClick={()=>onChange([])}>Сбросить темы</button><button type="button" className="btn primary" onClick={close}>Готово</button></div></div></div>
 </details>{value.length>0&&<div className="topic-filter-chips">{value.map(id=><button type="button" key={id} title={index.paths.get(id)} aria-label={'Убрать ветку '+(index.paths.get(id)||'Тема')} onClick={()=>onChange(value.filter(item=>item!==id))}><span>{index.paths.get(id)||'Тема'}</span><X size={12}/></button>)}</div>}</div>;
}
