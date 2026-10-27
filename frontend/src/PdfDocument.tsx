import {useEffect,useRef,useState} from 'react';
import type {PDFDocumentProxy,PDFDocumentLoadingTask,RenderTask} from 'pdfjs-dist';
import {Download,FileCode2,FileText,Loader2,PackageOpen} from 'lucide-react';

export type PdfDocument={title:string;pdf_url:string;tex_url?:string;project_url?:string;solutions_available?:boolean};
function urlWith(url:string,values:Record<string,string>){const result=new URL(url,location.origin);for(const [key,value] of Object.entries(values))result.searchParams.set(key,value);return result.pathname+result.search}
export function PdfActions({document,onPreview,allowSource=false,compact=false}: {document:PdfDocument;onPreview:(document:PdfDocument)=>void;allowSource?:boolean;compact?:boolean}){
 return <div className={'pdf-actions'+(compact?' compact':'')}><button type="button" className="btn text" onClick={()=>onPreview(document)} aria-label={'Предпросмотр PDF: '+document.title}><FileText size={15}/>PDF</button><a className="btn text" href={urlWith(document.pdf_url,{download:'1'})} aria-label={'Скачать PDF: '+document.title}><Download size={15}/>{!compact&&'Скачать'}</a>{allowSource&&document.tex_url&&<a className="btn text" href={document.tex_url}><FileCode2 size={15}/>TeX</a>}{allowSource&&document.project_url&&<a className="btn text" href={document.project_url}><PackageOpen size={15}/>Проект ZIP</a>}</div>
}
export default function PdfPreview({document,allowSource=false}:{document:PdfDocument;allowSource?:boolean}){
 const [solutions,setSolutions]=useState(false),[blob,setBlob]=useState(''),[error,setError]=useState('');
 const source=urlWith(document.pdf_url,{solutions:solutions?'1':'0'});
 useEffect(()=>{let active=true,objectUrl='';const abort=new AbortController();setBlob('');setError('');fetch(source,{credentials:'same-origin',signal:abort.signal}).then(async response=>{if(!response.ok){const body=await response.json().catch(()=>({detail:'Не удалось получить PDF.'}));throw new Error(body.detail||'Не удалось получить PDF.')}return response.blob()}).then(result=>{if(active){objectUrl=URL.createObjectURL(result);setBlob(objectUrl)}}).catch(error=>{if(active&&error.name!=='AbortError')setError(error.message)});return()=>{active=false;abort.abort();if(objectUrl)URL.revokeObjectURL(objectUrl)}},[source]);
 return <section className="pdf-preview"><div className="pdf-preview-toolbar"><label className="pdf-solutions-choice"><input type="checkbox" checked={solutions} onChange={event=>setSolutions(event.target.checked)}/>С доступными решениями</label><div><a className="btn secondary" href={urlWith(source,{download:'1'})}><Download size={15}/>Скачать PDF</a>{allowSource&&document.tex_url&&<a className="btn text" href={urlWith(document.tex_url,{solutions:solutions?'1':'0'})}><FileCode2 size={15}/>TeX</a>}{allowSource&&document.project_url&&<a className="btn text" href={urlWith(document.project_url,{solutions:solutions?'1':'0'})}><PackageOpen size={15}/>Проект ZIP</a>}</div></div>{error?<p className="error-panel" role="alert">{error}</p>:blob?<PdfCanvas key={blob} url={blob} title={document.title}/>:<div className="pdf-loading"><Loader2 className="spin" size={22}/>Собираем PDF…</div>}<p className="pdf-preview-note">В PDF попадают только решения, которые вам разрешено видеть.{allowSource&&' TeX и ZIP содержат тот же выбранный вариант.'}</p></section>
}

function PdfCanvas({url,title}:{url:string;title:string}){
 const canvas=useRef<HTMLCanvasElement>(null);
 const [pdf,setPdf]=useState<PDFDocumentProxy|null>(null),[page,setPage]=useState(1),[error,setError]=useState(''),[rendering,setRendering]=useState(true);
 useEffect(()=>{let active=true,loading:PDFDocumentLoadingTask|undefined;
  Promise.all([import('pdfjs-dist'),import('pdfjs-dist/build/pdf.worker.min.mjs?url')]).then(([library,worker])=>{
   if(!active)return;library.GlobalWorkerOptions.workerSrc=worker.default;
   loading=library.getDocument({url,useWasm:false,useWorkerFetch:false});
   return loading.promise.then(document=>{if(active)setPdf(document)});
  }).catch(error=>{if(active)setError(error.message||'Не удалось открыть PDF.')});
  return()=>{active=false;void loading?.destroy()};
 },[url]);
 useEffect(()=>{if(!pdf||!canvas.current)return;let active=true,task:RenderTask|undefined;setRendering(true);
  pdf.getPage(page).then(document=>{if(!active||!canvas.current)return;const viewport=document.getViewport({scale:1.5});const surface=canvas.current;surface.width=Math.ceil(viewport.width);surface.height=Math.ceil(viewport.height);task=document.render({canvas:surface,viewport});return task.promise}).then(()=>{if(active)setRendering(false)}).catch(error=>{if(active)setError(error.message||'Не удалось показать страницу.')});
  return()=>{active=false;task?.cancel()};
 },[pdf,page]);
 if(error)return <p className="error-panel" role="alert">{error}</p>;
 return <div className="pdf-reader"><div className="pdf-page-controls"><button type="button" className="btn text" disabled={!pdf||page===1} onClick={()=>setPage(page-1)}>← Назад</button><span role="status">Страница {page}{pdf?' из '+pdf.numPages:''}</span><button type="button" className="btn text" disabled={!pdf||page===pdf.numPages} onClick={()=>setPage(page+1)}>Далее →</button></div><div className="pdf-page-surface">{rendering&&<div className="pdf-rendering"><Loader2 className="spin" size={18}/>Загружаем страницу…</div>}<canvas ref={canvas} role="img" aria-label={title+' — страница '+page} style={{visibility:rendering?'hidden':'visible'}}/></div></div>;
}
