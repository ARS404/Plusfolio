import {useId,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {Maximize2,Minimize2} from 'lucide-react';
import './journal-viewport.css';

type Props={title:string;description:string;status:ReactNode;canExpand:boolean;children:ReactNode};

export default function JournalViewport({title,description,status,canExpand,children}:Props){
 const headingId=useId();
 const viewport=useRef<HTMLElement>(null),toggle=useRef<HTMLButtonElement>(null);
 const [expandedHeight,setExpandedHeight]=useState<number|null>(null);
 const expanded=expandedHeight!==null;

 useLayoutEffect(()=>{
  if(!expanded)return;
  if(!canExpand){setExpandedHeight(null);return}
  const root=viewport.current;
  if(!root)return;
  const overflow=document.body.style.overflow;
  document.body.style.overflow='hidden';
  // Inert only the surrounding page. App dialogs can still open above the table.
  const background:{element:HTMLElement;inert:boolean}[]=[];
  for(let branch:HTMLElement=root;branch!==document.body&&branch.parentElement;branch=branch.parentElement){
   for(const sibling of branch.parentElement.children){
    if(sibling!==branch&&sibling instanceof HTMLElement&&!sibling.matches('.modal-shade,.toast')){
     background.push({element:sibling,inert:sibling.inert});sibling.inert=true;
    }
   }
  }
  const onKeyDown=(event:KeyboardEvent)=>{
   if(event.defaultPrevented||document.querySelector('.modal-shade'))return;
   if(event.key==='Escape'){
    event.preventDefault();setExpandedHeight(null);
   }else if(event.key==='Tab'){
    const focusable=Array.from(root.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')).filter(element=>element.getClientRects().length>0);
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey&&(document.activeElement===first||!root.contains(document.activeElement))){event.preventDefault();last?.focus()}
    else if(!event.shiftKey&&(document.activeElement===last||!root.contains(document.activeElement))){event.preventDefault();first?.focus()}
   }
  };
  document.addEventListener('keydown',onKeyDown);
  toggle.current?.focus({preventScroll:true});
  return()=>{
   document.body.style.overflow=overflow;
   for(const {element,inert} of background)element.inert=inert;
   document.removeEventListener('keydown',onKeyDown);
   toggle.current?.focus({preventScroll:true});
  };
 },[expanded,canExpand]);

 return <div style={expanded?{height:expandedHeight}:undefined}>
  <section ref={viewport} className={'journal-viewport'+(expanded?' is-expanded':'')}
   role={expanded?'dialog':'region'} aria-modal={expanded||undefined} aria-labelledby={headingId}>
   <div className="journal-intro">
    <div><h3 id={headingId}>{title}</h3><span>{description}</span></div>
    <div className="journal-viewport-actions">{status}{canExpand&&<button ref={toggle} type="button" className="btn secondary"
     aria-expanded={expanded} title={expanded?'Вернуться к странице кружка (Esc)':'Развернуть таблицу на всю область окна'}
     onClick={()=>setExpandedHeight(expanded?null:viewport.current?.getBoundingClientRect().height??null)}>
     {expanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}<span>{expanded?'Свернуть':'На весь экран'}</span>
    </button>}</div>
   </div>
   {children}
  </section>
 </div>;
}
