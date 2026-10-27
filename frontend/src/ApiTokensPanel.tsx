import {useEffect,useState,type FormEvent} from 'react';
import {Check,Copy,KeyRound,Loader2,Plus,Trash2,X} from 'lucide-react';

type Token={id:string;name:string;prefix:string;read_only:boolean;active:boolean;expires_at:string;last_used_at:string|null};
type Props={api:(path:string,method?:string,data?:unknown)=>Promise<any>};

export default function ApiTokensPanel({api}:Props){
 const [open,setOpen]=useState(false),[tokens,setTokens]=useState<Token[]|null>(null),[error,setError]=useState('');
 const [creating,setCreating]=useState(false),[busy,setBusy]=useState(false),[name,setName]=useState('Мой бот');
 const [password,setPassword]=useState(''),[days,setDays]=useState('30'),[readOnly,setReadOnly]=useState(true);
 const [secret,setSecret]=useState(''),[copied,setCopied]=useState(false);
 const reload=async()=>{const result=await api('/v1/auth/tokens');setTokens(result)};
 useEffect(()=>{
  if(!open)return;
  let active=true;
  api('/v1/auth/tokens').then(value=>{if(active)setTokens(value)}).catch(error=>{if(active)setError(error.message)});
  return()=>{active=false};
 },[open]);
 const closeSecret=()=>{setSecret('');setCopied(false)};
 const create=async(event:FormEvent)=>{
  event.preventDefault();setBusy(true);setError('');
  try{
   const result=await api('/v1/auth/tokens','POST',{password,name,expires_in_days:Number(days),read_only:readOnly});
   setSecret(result.access_token);setCopied(false);setCreating(false);await reload();
  }catch(error:any){setError(error.message)}finally{setPassword('');setBusy(false)}
 };
 const revoke=async(token:Token)=>{
  setBusy(true);setError('');
  try{await api('/v1/auth/tokens/'+token.id,'DELETE');await reload()}
  catch(error:any){setError(error.message)}finally{setBusy(false)}
 };
 const copy=async()=>{
  try{await navigator.clipboard.writeText(secret);setCopied(true)}
  catch{setError('Не удалось скопировать. Выделите токен вручную.')}
 };
 return <section className="panel account-api-panel" aria-label="API-токены">
  <div className="panel-heading"><div><h3><KeyRound size={17}/>API-токены</h3><p>Доступ для ваших ботов и интеграций.</p></div></div>
  <div className="account-api-body">
   <a href="#/documentation/api-access">Как подключить бота →</a>
   <button type="button" className="btn secondary full" aria-expanded={open} onClick={()=>{
    setOpen(!open);setError('');setPassword('');setCreating(false);closeSecret();
   }}>Управление токенами</button>
   {open&&<>
    {error&&<p className="account-form-error" role="alert">{error}</p>}
    {tokens===null&&!error&&<div className="loading"><Loader2 className="spin" size={18}/>Загружаем токены…</div>}
    {tokens?.map(token=><div className="account-api-token" key={token.id}>
     <div><b>{token.name}</b><code>{token.prefix}</code>
      <small>{token.read_only?'Только чтение':'Чтение и изменения'} · {token.active?'до '+new Date(token.expires_at).toLocaleDateString('ru-RU'):'Недействителен'}</small>
      {token.last_used_at&&<small>Использован: {new Date(token.last_used_at).toLocaleString('ru-RU')}</small>}
     </div>
     {token.active&&<button type="button" className="icon-button danger" aria-label={'Отозвать токен '+token.name} disabled={busy} onClick={()=>revoke(token)}><Trash2 size={15}/></button>}
    </div>)}
    {tokens?.length===0&&<p className="account-api-empty">Токенов пока нет. Для каждой интеграции создайте отдельный.</p>}
    {secret&&<div className="account-api-secret">
     <div><b>Скопируйте токен сейчас</b><button type="button" className="icon-button" aria-label="Скрыть новый токен" onClick={closeSecret}><X size={14}/></button></div>
     <p>Он показывается один раз и не сохраняется в браузере.</p>
     <textarea aria-label="Новый API-токен" value={secret} readOnly rows={3} spellCheck={false}/>
     <button type="button" className="btn secondary full" onClick={copy}>{copied?<Check size={14}/>:<Copy size={14}/>} {copied?'Скопировано':'Скопировать токен'}</button>
    </div>}
    {!creating?<button type="button" className="btn primary full" onClick={()=>{setCreating(true);setError('');closeSecret()}}><Plus size={15}/>Создать токен</button>:
     <form className="account-form account-api-form" onSubmit={create}>
      <label>Название интеграции<input aria-label="Название API-токена" value={name} onChange={event=>setName(event.target.value)} maxLength={100} required/></label>
      <label>Срок в днях<input aria-label="Срок API-токена в днях" type="number" min={1} max={90} value={days} onChange={event=>setDays(event.target.value)} required/></label>
      <label className="identity-no-patronymic"><input type="checkbox" checked={readOnly} onChange={event=>setReadOnly(event.target.checked)}/>Только чтение</label>
      <label>Текущий пароль<input aria-label="Пароль для создания API-токена" type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)} required/></label>
      <p>Токен действует в пределах ваших текущих ролей. Смена пароля отключит все прежние токены.</p>
      <button className="btn primary full" disabled={busy}>{busy?<Loader2 className="spin" size={15}/>:<KeyRound size={15}/>}Выпустить токен</button>
      <button type="button" className="btn text full" disabled={busy} onClick={()=>{setCreating(false);setPassword('')}}>Отмена</button>
     </form>}
   </>}
  </div>
 </section>;
}
