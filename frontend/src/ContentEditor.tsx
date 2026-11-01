import {useEffect,useRef,useState} from 'react';
import {ImagePlus,Loader2,Trash2,Shapes} from 'lucide-react';
import type {ContentImage} from './worksheetBlocks';
import {plainToTex} from './worksheetBlocks';

type Content={text:string;tex:string;images:ContentImage[]};
const tikz='\\begin{center}\n\\begin{tikzpicture}[scale=0.8]\n  \\draw (0,0) -- (3,0) -- (1,2) -- cycle;\n  \\node[below] at (0,0) {$A$};\n  \\node[below] at (3,0) {$B$};\n  \\node[above] at (1,2) {$C$};\n\\end{tikzpicture}\n\\end{center}';
export default function ContentEditor({label,value,onChange,onUploadingChange}:{label:string;value:Content;onChange:(value:Content)=>void;onUploadingChange?:(busy:boolean)=>void}){
 const plain=useRef<HTMLTextAreaElement>(null),tex=useRef<HTMLTextAreaElement>(null),input=useRef<HTMLInputElement>(null);
 const [active,setActive]=useState<'text'|'tex'>(value.tex?'tex':'text'),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const uploadAbort=useRef<AbortController|null>(null);
 const mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;uploadAbort.current?.abort()}},[]);
 const latest=useRef(value);latest.current=value;
 const insert=(snippet:string,images=latest.current.images,asTex=false)=>{
  const current=latest.current;const field=asTex?'tex':current.tex?'tex':active;
  const source=field==='tex'?(current.tex||plainToTex(current.text)):current.text;
  const area=field==='tex'?tex.current:plain.current;
  const at=field==='tex'&&!current.tex?source.length:area?.selectionStart??source.length,end=field==='tex'&&!current.tex?source.length:area?.selectionEnd??source.length;
  onChange({...current,[field]:source.slice(0,at)+'\n'+snippet+'\n'+source.slice(end),images});setActive(field);
  if(field==='tex'&&tex.current)tex.current.closest('details')?.setAttribute('open','');
 };
 const upload=async(file:File)=>{
  if(uploadAbort.current)return;
  if(latest.current.images.length>=20){setError('В одном блоке доступны до 20 рисунков.');return}
  if(!['image/png','image/jpeg'].includes(file.type)||file.size>2*1024*1024){setError('Выберите PNG/JPEG до 2 МиБ.');return}
  setBusy(true);setError('');onUploadingChange?.(true);const controller=new AbortController();uploadAbort.current=controller;
  try{
   const body=new FormData();body.append('file',file);
   const csrf=document.cookie.split('; ').find(item=>item.startsWith('csrftoken='))?.split('=').slice(1).join('=')||'';
   const response=await fetch('/api/images',{method:'POST',signal:controller.signal,credentials:'same-origin',headers:{'X-CSRFToken':decodeURIComponent(csrf)},body});
   const asset=await response.json();if(controller.signal.aborted)return;if(!response.ok)throw new Error(asset.detail||'Не удалось загрузить рисунок.');
   if(latest.current.images.some(image=>image.id===asset.id)){setError('Этот рисунок уже добавлен в блок.');return}
   insert('\\pfimage{'+asset.id+'}',[...latest.current.images,{id:asset.id,width:70,align:'center',caption:''}]);
  }catch(error:any){if(mounted.current&&!controller.signal.aborted)setError(error.message)}finally{if(uploadAbort.current===controller)uploadAbort.current=null;onUploadingChange?.(false);if(mounted.current)setBusy(false);if(input.current)input.current.value=''}
 };
 const paste=(event:React.ClipboardEvent)=>{const file=Array.from(event.clipboardData.files).find(file=>file.type.startsWith('image/'));if(file){event.preventDefault();void upload(file)}};
 const patchImage=(id:string,patch:Partial<ContentImage>)=>onChange({...value,images:value.images.map(image=>image.id===id?{...image,...patch}:image)});
 return <div className="content-editor" onDragOver={event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault()}} onDrop={event=>{if(event.dataTransfer.files.length){event.preventDefault();event.stopPropagation();void upload(event.dataTransfer.files[0])}}}>
  <label>{label}<textarea ref={plain} aria-label={label} value={value.text} rows={4} maxLength={30000} onFocus={()=>setActive('text')} onPaste={paste} onChange={event=>onChange({...value,text:event.target.value})} placeholder="Текст и формулы $...$. Рисунок можно вставить из буфера."/></label>
  <details className="tex-editor" open={value.tex?true:undefined}><summary>TeX и TikZ</summary><p>Заполненный TeX используется в PDF вместо обычного текста. Шаблон уже содержит оформление и TikZ.</p><label>TeX: {label.toLowerCase()}<textarea ref={tex} aria-label={'TeX: '+label.toLowerCase()} value={value.tex} rows={6} maxLength={30000} spellCheck={false} onFocus={()=>setActive('tex')} onPaste={paste} onChange={event=>onChange({...value,tex:event.target.value})}/></label></details>
  <div className="content-insert-actions"><input ref={input} type="file" accept="image/png,image/jpeg" aria-label={'Загрузить рисунок: '+label.toLowerCase()} onChange={event=>{if(event.target.files?.[0])void upload(event.target.files[0])}} hidden/><button type="button" className="btn secondary" disabled={busy||value.images.length>=20} onClick={()=>input.current?.click()}>{busy?<Loader2 size={15} className="spin"/>:<ImagePlus size={15}/>}Вставить рисунок</button><button type="button" className="btn text" onClick={()=>insert(tikz,undefined,true)}><Shapes size={15}/>Пример TikZ</button><span>PNG/JPEG до 2 МиБ · вставка из буфера и перетаскивание</span></div>
  {error&&<p className="error-panel" role="alert">{error}</p>}
  {!!value.images.length&&<div className="content-images">{value.images.map((image,index)=><div className="content-image-editor" key={image.id}><img src={'/api/images/'+image.id} alt={image.caption||'Рисунок '+(index+1)}/><div className="content-image-fields"><label>Подпись<input aria-label={'Подпись рисунка '+(index+1)} value={image.caption} maxLength={500} onChange={event=>patchImage(image.id,{caption:event.target.value})}/></label><div className="content-image-options"><label>Ширина, %<input type="number" min={10} max={100} step={5} value={image.width} onChange={event=>patchImage(image.id,{width:Number(event.target.value)})}/></label><label>Выравнивание<select value={image.align} onChange={event=>patchImage(image.id,{align:event.target.value as ContentImage['align']})}><option value="left">Слева</option><option value="center">По центру</option><option value="right">Справа</option></select></label><button type="button" className="icon-button danger" aria-label={'Удалить рисунок '+(index+1)} onClick={()=>{const token='\\pfimage{'+image.id+'}';onChange({...value,text:value.text.replaceAll(token,''),tex:value.tex.replaceAll(token,''),images:value.images.filter(item=>item.id!==image.id)})}}><Trash2 size={17}/></button></div></div></div>)}</div>}
 </div>
}
