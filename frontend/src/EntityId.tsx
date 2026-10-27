import {useState} from 'react';
import {Check,Copy} from 'lucide-react';
export default function EntityId({value,copyable=false}:{value?:string|null;copyable?:boolean}){
 const [copied,setCopied]=useState(false),[failed,setFailed]=useState(false);
 if(!value)return null;
 if(!copyable)return <span className="entity-id" title={'ID: '+value}>{value}</span>;
 return <button type="button" className="entity-id copyable" title="Скопировать ID" aria-label={'Скопировать ID '+value} onClick={async()=>{try{await navigator.clipboard.writeText(value);setCopied(true);setFailed(false);setTimeout(()=>setCopied(false),1800)}catch{setFailed(true)}}}><span>{value}</span>{copied?<Check size={12}/>:<Copy size={12}/>}<span className="entity-id-feedback" role="status">{copied?'Скопировано':failed?'Выделите и скопируйте ID':''}</span></button>;
}
