import {useEffect,useState} from 'react';

type Filters=Record<string,string|string[]>;
export type CatalogueReply={kind:string;results:{entity:any;match:string;excerpt:string}[];semantic:boolean;pending:number;notice:string};
export function useCatalogueSearch(kind:string|undefined,query:string,filters:Filters={}){
 const params=new URLSearchParams({kind:kind||'',q:query.trim(),limit:'100'});
 for(const [name,values] of Object.entries(filters))for(const value of Array.isArray(values)?values:[values])if(value)params.append(name,value);
 const key=kind&&query.trim()?params.toString():'';
 const [result,setResult]=useState<{key:string;data:CatalogueReply|null;error:string}>({key:'',data:null,error:''});
 useEffect(()=>{
  if(!key)return;
  const abort=new AbortController();
  const timer=setTimeout(async()=>{
   try{
    const response=await fetch('/api/catalogue-search?'+key,{credentials:'same-origin',signal:abort.signal});
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Поиск временно недоступен.');
    if(!abort.signal.aborted)setResult({key,data,error:''});
   }catch(error:any){if(!abort.signal.aborted)setResult({key,data:null,error:error.message})}
  },500);
  return()=>{clearTimeout(timer);abort.abort()};
 },[key]);
 return {data:result.key===key?result.data:null,error:result.key===key?result.error:'',busy:!!key&&result.key!==key};
}
export function CatalogueSearchStatus({data,busy,error}:{data?:CatalogueReply|null;busy?:boolean;error?:string}){
 if(error)return <p className="search-help" role="status">Поиск по смыслу недоступен: {error}</p>;
 if(busy)return <p className="search-help" role="status">Ищем по названию, описанию и смыслу…</p>;
 if(!data)return null;
 return <div className="search-help" role="status">{data.semantic?'По тексту и смыслу':'По тексту'} · показано {data.results.length}{data.results.length===100?' (уточните запрос для остальных)':''}{data.notice&&<div>{data.notice}</div>}</div>;
}
