import {useEffect,useMemo,useState} from 'react';
import {ArrowLeft,ChevronDown,ChevronRight,Code2,Copy,Download,LockKeyhole,Search,ShieldCheck,X} from 'lucide-react';
import MultiSelect from './MultiSelect';
import {constraints,endpoints,filterEndpoints,resolveSchema,schemaFields,typeName,variants,type ApiSpec,type Endpoint,type Media,type Schema} from './apiReference';

function JsonExample({value,label}:{value:unknown;label:string}){
 const [copied,setCopied]=useState(false);
 const text=JSON.stringify(value,null,2);
 const copy=async()=>{try{await navigator.clipboard.writeText(text);setCopied(true)}catch{setCopied(false)}};
 return <details className="api-json"><summary><Code2 size={14}/>{label}<ChevronDown size={14}/></summary><div className="documentation-code"><div><span>JSON</span><button type="button" onClick={copy}><Copy size={13}/>{copied?'Скопировано':'Копировать'}</button></div><pre><code>{text}</code></pre></div></details>;
}

function Fields({schema,spec,label}:{schema:Schema|undefined;spec:ApiSpec;label:string}){
 const [choice,setChoice]=useState(0),[expanded,setExpanded]=useState(false);
 const resolved=resolveSchema(schema,spec),options=variants(resolved,spec);
 if(options.length>1)return <div className="api-schema"><div className="api-variants" role="group" aria-label={'Вариант формата: '+label}>{options.map((option,i)=><button type="button" key={i} className={choice===i?'selected':''} onClick={()=>setChoice(i)}>{resolveSchema(option,spec).title||'Вариант '+(i+1)}</button>)}</div>{resolved.description&&<p>{resolved.description}</p>}<Fields key={choice} schema={options[choice]||options[0]} spec={spec} label={label}/></div>;
 if(resolved.type==='array'&&variants(resolved.items,spec).length>1)return <div className="api-schema"><p className="api-format-note">Массив. Формат каждого элемента:</p><Fields schema={resolved.items} spec={spec} label={label+' — элемент массива'}/></div>;
 const rows=schemaFields(schema,spec,expanded),limits=constraints(schema,spec),hasNested=schemaFields(schema,spec,true).some(row=>row.depth>0);
 return <div className="api-schema"><div className="api-schema-caption"><b>{typeName(schema,spec)}</b>{hasNested&&<button type="button" onClick={()=>setExpanded(!expanded)} aria-expanded={expanded}>{expanded?'Свернуть вложенные поля':'Показать вложенные поля'}</button>}</div>{resolved.description&&<p className="api-format-note">{resolved.description}</p>}{limits.length>0&&<p className="api-format-note">{limits.join(' · ')}</p>}
  <div className="documentation-table-wrap"><table aria-label={label}><thead><tr><th>Поле</th><th>Тип</th><th>Наличие</th><th>Описание и ограничения</th></tr></thead><tbody>{rows.map((row,i)=><tr key={row.name+i}><td><code>{row.name}</code></td><td>{row.type}</td><td><span className={row.required?'api-required':'api-optional'}>{row.required?'Обязательно':'По условию'}</span></td><td>{row.description||'—'}{row.constraints.map((limit,j)=><small key={j}>{limit}</small>)}</td></tr>)}</tbody></table></div>
  {rows.some(row=>!row.required)&&<p className="api-field-note">«По условию» — поле необязательно либо зависит от роли, параметров или типа ответа. Условия указаны в описании.</p>}
 </div>;
}

function Content({content,spec,label}:{content:Record<string,Media>;spec:ApiSpec;label:string}){
 const types=Object.keys(content),[selected,setSelected]=useState(types[0]||'');
 const current=types.includes(selected)?selected:types[0];const media=content[current];
 if(!media)return <p className="api-format-note">Тело отсутствует.</p>;
 const binary=media.schema?.format==='binary';
 return <><div className="api-media"><span>Content-Type</span>{types.length>1?<div className="api-variants" role="group" aria-label={'Формат содержимого: '+label}>{types.map(type=><button key={type} type="button" className={type===current?'selected':''} onClick={()=>setSelected(type)}>{type}</button>)}</div>:<code>{current}</code>}</div>
  {binary?<p className="api-format-note">Содержимое файла. Ответ сохраняется как двоичные данные и не имеет JSON-полей.</p>:<Fields key={current} schema={media.schema} spec={spec} label={label}/>}
  {media.example!==undefined&&<JsonExample value={media.example} label="Пример JSON — иллюстративные данные"/>}
  {media.schema&&<JsonExample value={media.schema} label="Исходная JSON-схема"/>}
 </>;
}

function EndpointBody({item,spec}:{item:Endpoint;spec:ApiSpec}){
 const responses=Object.entries(item.responses),success=responses.filter(([status])=>/^2/.test(status));
 const errors=responses.filter(([status])=>!/^2/.test(status));
 const parameters=item.parameters||[];
 return <div className="api-endpoint-body">
  <p className="api-endpoint-description">{item.description||'Операция выполняется в пределах доступных данных. Сервер повторно проверяет права.'}</p>
  <div className="api-auth-note">{item.security?.length===0?<><ShieldCheck size={15}/><span>Предварительная авторизация не обязательна. Дополнительные условия указаны в описании.</span></>:<><LockKeyhole size={15}/><span>Нужен <code>Authorization: Bearer &lt;token&gt;</code> с текущими правами аккаунта.</span></>}</div>
  <section className="api-contract-section"><h3>Входные данные</h3>
   {parameters.length>0&&<><h4>Параметры пути и запроса</h4><div className="documentation-table-wrap"><table aria-label={'Параметры '+item.method+' '+item.path}><thead><tr><th>Параметр</th><th>Где</th><th>Тип</th><th>Наличие</th><th>Описание</th></tr></thead><tbody>{parameters.map(parameter=><tr key={parameter.in+parameter.name}><td><code>{parameter.name}</code></td><td>{({path:'В пути',query:'В строке запроса',header:'В заголовке'} as Record<string,string>)[parameter.in]||parameter.in}</td><td>{typeName(parameter.schema,spec)}</td><td>{parameter.required?'Обязательно':'Необязательно'}</td><td>{parameter.description}{constraints(parameter.schema,spec).map((limit,i)=><small key={i}>{limit}</small>)}</td></tr>)}</tbody></table></div></>}
   {item.requestBody?<><h4>Тело запроса {item.requestBody.required&&<span className="api-required">обязательно</span>}</h4><Content content={item.requestBody.content} spec={spec} label="Поля тела запроса"/></>:<p className="api-no-body">Тело запроса не требуется.{!parameters.length&&' Параметров пути и запроса нет.'}</p>}
  </section>
  <section className="api-contract-section"><h3>Выходные данные</h3>{success.map(([status,response])=><div key={status}><div className="api-response-heading"><span className="badge green">HTTP {status}</span><p>{response.description}</p></div>{response.content?<Content content={response.content} spec={spec} label={'Поля ответа HTTP '+status}/>:<p className="api-no-body">Успешный ответ без тела.</p>}</div>)}</section>
  {errors.length>0&&<section className="api-contract-section"><h3>Ошибки</h3><div className="documentation-table-wrap"><table aria-label="Коды ошибок ручки"><thead><tr><th>Код</th><th>Значение</th></tr></thead><tbody>{errors.map(([status,response])=><tr key={status}><td><code>{status}</code></td><td>{response.description}</td></tr>)}</tbody></table></div><details className="api-error-shape"><summary>Формат тела ошибки<ChevronRight size={14}/></summary><Fields schema={errors[0][1].content?.['application/json']?.schema} spec={spec} label="Поля ошибки"/></details></section>}
  <p className="api-reference-static-note">Это описание контракта. Примеры не содержат ваших данных, а ручка с этой страницы не вызывается.</p>
 </div>;
}

export default function ApiReferencePage({spec,operationId}:{spec:ApiSpec|null;operationId?:string}){
 const [query,setQuery]=useState(''),[methods,setMethods]=useState<string[]>([]),[selectedGroups,setGroups]=useState<string[]>([]);
 const [opened,setOpened]=useState<string|null>(operationId||null);
 useEffect(()=>{setOpened(operationId||null)},[operationId]);
 const items=useMemo(()=>spec?endpoints(spec):[],[spec]);
 const filtered=filterEndpoints(items,query,methods,selectedGroups);
 const groups=[...new Map(items.map(item=>[item.group,item.groupLabel])).entries()];
 const visibleGroups=groups.filter(([group])=>filtered.some(item=>item.group===group));
 const availableMethods=[...new Set(items.map(item=>item.method))];
 return <>
  <a className="back-link" href="#/documentation?audience=robot"><ArrowLeft size={15}/>Руководство и сценарии</a>
  <div className="page-heading"><div><span className="eyebrow">КОНТРАКТ В ПОНЯТНОМ ВИДЕ</span><h1>Справочник API<span className="heading-dot">.</span></h1><p>Методы, адреса, входные и выходные данные каждой доступной ручки.</p></div><span className="documentation-heading-icon" aria-hidden="true"><Code2 size={28}/></span></div>
  <div className="api-reference-intro"><div><ShieldCheck size={19}/><p>Доступные ручки отобраны по вашим правам. Справочник только описывает API.<small>JSON-схема и это представление используют один контракт.</small></p></div><a className="btn secondary" href="/api/v1/openapi.json" download="plusfolio-openapi.json"><Download size={15}/>OpenAPI JSON</a></div>
  {spec&&<><div className="api-reference-meta"><span>Базовый путь <code>{spec.servers[0]?.url}</code></span><span>Версия {spec.info.version}</span><span>{items.length} методов</span></div>
   <div className="api-reference-filters"><div className="search-field"><Search size={17}/><input type="search" aria-label="Поиск ручек API" placeholder="Адрес, назначение или поле: например, worksheet или version" value={query} onChange={event=>setQuery(event.target.value)}/>{query&&<button type="button" className="icon-button" aria-label="Очистить поиск ручек" onClick={()=>setQuery('')}><X size={15}/></button>}</div><MultiSelect label="HTTP-методы" value={methods} onChange={setMethods} placeholder="Все методы" options={availableMethods.map(method=>({value:method,label:method}))}/><MultiSelect label="Разделы API" value={selectedGroups} onChange={setGroups} placeholder="Все разделы" options={groups.map(([value,label])=>({value,label}))}/></div>
   <div className="api-reference-results"><span>Найдено методов: {filtered.length}</span><button type="button" className="btn text" disabled={!query&&!methods.length&&!selectedGroups.length} onClick={()=>{setQuery('');setMethods([]);setGroups([])}}>Сбросить фильтры</button></div>
   {operationId&&!items.some(item=>item.id===operationId)&&<div className="error-panel">Ручка отсутствует или недоступна с вашими правами.</div>}
   <div className="api-reference-list">{visibleGroups.map(([group,label])=><section key={group} className="api-reference-group"><h2>{label}<span>{filtered.filter(item=>item.group===group).length}</span></h2>{filtered.filter(item=>item.group===group).map(item=><div className={'api-endpoint '+(opened===item.id?'is-open':'')} key={item.id}>
    <button type="button" className="api-endpoint-toggle" aria-expanded={opened===item.id} aria-controls={'api-operation-'+item.id} onClick={()=>setOpened(opened===item.id?null:item.id)}><span className={'documentation-method method-'+item.method.toLowerCase()}>{item.method}</span><div><code>{item.path}</code><span>{item.summary}</span></div><ChevronRight size={17}/></button>
    {opened===item.id&&<div id={'api-operation-'+item.id}><EndpointBody item={item} spec={spec}/></div>}
   </div>)}</section>)}{!filtered.length&&<div className="panel documentation-empty"><Search size={28}/><h2>Ручки не найдены</h2><p>Измените запрос, методы или выбранные разделы.</p></div>}</div>
  </>}
 </>;
}
