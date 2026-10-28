export type Schema={
 $ref?:string;type?:string|string[];title?:string;description?:string;format?:string;
 properties?:Record<string,Schema>;required?:string[];items?:Schema;anyOf?:Schema[];oneOf?:Schema[];
 enum?:unknown[];const?:unknown;default?:unknown;minimum?:number;maximum?:number;minLength?:number;maxLength?:number;
 minItems?:number;maxItems?:number;additionalProperties?:boolean|Schema;writeOnly?:boolean;
};
export type Media={schema?:Schema;example?:unknown};
export type Parameter={name:string;in:string;required?:boolean;description?:string;schema?:Schema};
export type Operation={operationId:string;summary?:string;description?:string;tags?:string[];
 parameters?:Parameter[];requestBody?:{required?:boolean;content:Record<string,Media>};
 responses:Record<string,{description?:string;content?:Record<string,Media>}>;security?:Record<string,unknown>[]};
export type ApiSpec={openapi:string;info:{title:string;version:string;description?:string};servers:{url:string}[];
 paths:Record<string,Record<string,Operation>>;components?:{schemas?:Record<string,Schema>};security?:Record<string,unknown>[]};
export type Endpoint=Operation&{id:string;method:string;path:string;group:string;groupLabel:string;searchText?:string};
export type FieldRow={name:string;type:string;required:boolean;description:string;constraints:string[];depth:number};

const GROUPS:Record<string,string>={auth:'Вход и токены',account:'Личный кабинет',tex:'TeX и проверка вёрстки',circles:'Кружки и журнал','problem-search':'Поиск задач','catalogue-search':'Поиск названий и описаний',materials:'Задачи и листки',
 'worksheet-documents':'Версии листков',worksheets:'Копирование листков','my-materials':'Мои материалы','my-problems':'Мои задачи','my-issues':'Мои выдачи',
 topics:'Темы',tags:'Теги',analytics:'Аналитика',invitations:'Приглашения',accept:'Принятие приглашений',mailbox:'Почта демо',users:'Пользователи',documentation:'Руководства','openapi.json':'Схема API'};
const METHOD_SET=new Set(['get','post','patch','put','delete','head','options']);

export function endpoints(spec:ApiSpec):Endpoint[]{
 const base=spec.servers[0]?.url?.replace(/\/$/,'')||'/api/v1';
 return Object.entries(spec.paths).flatMap(([path,methods])=>Object.entries(methods).filter(([method])=>METHOD_SET.has(method)).map(([method,operation])=>{
  const group=operation.tags?.[0]||path.split('/')[1]||'other';
  const seen=new Set<string>();
  const schemaText=(value:unknown):string=>{
   if(Array.isArray(value))return value.map(schemaText).join(' ');
   if(value&&typeof value==='object'){
    const entry=value as Record<string,unknown>,reference=entry.$ref;
    const extra=typeof reference==='string'&&!seen.has(reference)?(seen.add(reference),schemaText(spec.components?.schemas?.[reference.split('/').pop()||''])):'';
    return Object.entries(entry).map(([key,item])=>key+' '+schemaText(item)).join(' ')+' '+extra;
   }
   return typeof value==='string'?value:'';
  };
  return {...operation,id:operation.operationId||method+path,method:method.toUpperCase(),path:base+path,group,groupLabel:GROUPS[group]||group,searchText:schemaText(operation)};
 }));
}

const normalize=(value:string)=>value.toLocaleLowerCase('ru').replace(/ё/g,'е');
export function filterEndpoints(items:Endpoint[],query:string,methods:string[]=[],groups:string[]=[]){
 const words=normalize(query).trim().split(/\s+/).filter(Boolean);
 return items.filter(item=>{
  if(methods.length&&!methods.includes(item.method)||groups.length&&!groups.includes(item.group))return false;
  if(!words.length)return true;
  const text=normalize([item.method,item.path,item.summary,item.description,item.groupLabel,item.searchText,...(item.parameters||[]).map(p=>p.name+' '+p.description)].join(' '));
  return words.every(word=>text.includes(word));
 });
}

export function resolveSchema(schema:Schema|undefined,spec:ApiSpec):Schema{
 let result=schema||{};const seen=new Set<string>();
 while(result.$ref){
  const reference=result.$ref;
  if(seen.has(reference))return {type:'object',description:result.description||'Повторная ссылка на объект.'};
  seen.add(reference);
  const target=spec.components?.schemas?.[reference.split('/').pop()||''];
  if(!target)return {description:result.description||'Схема '+reference};
  const {$ref:_,...overrides}=result;result={...target,...overrides};
 }
 return result;
}

export function variants(schema:Schema|undefined,spec:ApiSpec){
 const resolved=resolveSchema(schema,spec);
 const options=resolved.anyOf||resolved.oneOf||[];
 return options.filter(option=>resolveSchema(option,spec).type!=='null');
}

export function typeName(schema:Schema|undefined,spec:ApiSpec,depth=0):string{
 if(depth>6)return 'объект';
 const s=resolveSchema(schema,spec),options=s.anyOf||s.oneOf;
 if(options){
  const nonNull=options.filter(option=>resolveSchema(option,spec).type!=='null');
  const labels=[...new Set(nonNull.map(option=>typeName(option,spec,depth+1)))];
  return (labels.length===1?labels[0]:'один из: '+labels.join(' / '))+(nonNull.length<options.length?' или null':'');
 }
 const types=Array.isArray(s.type)?s.type:[s.type];
 if(types.includes('array'))return 'массив <'+typeName(s.items,spec,depth+1)+'>';
 const labels:Record<string,string>={string:'строка',integer:'целое число',number:'число',boolean:'да/нет',object:'объект',null:'null'};
 const label=types.filter(Boolean).map(t=>t==='string'&&s.format==='uuid'?'UUID':t==='string'&&s.format==='date'?'дата':t==='string'&&s.format==='date-time'?'дата и время':labels[t!]||t).join(' или ');
 return label||((s.enum?.length||s.const!==undefined)?'значение из списка':'JSON');
}

export function constraints(schema:Schema|undefined,spec:ApiSpec):string[]{
 const s=resolveSchema(schema,spec);const result:string[]=[];
 if(s.enum)result.push('Значения: '+s.enum.map(value=>JSON.stringify(value)).join(', '));
 if(s.const!==undefined)result.push('Всегда: '+JSON.stringify(s.const));
 if(s.default!==undefined)result.push('По умолчанию: '+JSON.stringify(s.default));
 if(s.minimum!==undefined||s.maximum!==undefined)result.push('Диапазон: '+(s.minimum??'…')+' — '+(s.maximum??'…'));
 if(s.minLength!==undefined||s.maxLength!==undefined)result.push('Длина: '+(s.minLength??0)+' — '+(s.maxLength??'…'));
 if(s.minItems!==undefined||s.maxItems!==undefined)result.push('Элементов: '+(s.minItems??0)+' — '+(s.maxItems??'…'));
 if(s.writeOnly)result.push('Секретное входное поле');
 if(s.format&& !['uuid','date','date-time'].includes(s.format))result.push('Формат: '+s.format);
 return result;
}

export function schemaFields(schema:Schema|undefined,spec:ApiSpec,expanded=false,prefix=''):FieldRow[]{
 const result:FieldRow[]=[];
 const walk=(input:Schema|undefined,path:string,depth:number,required:boolean,ancestors:Set<string>,root=false)=>{
  if(depth>4||result.length>=250)return;
  let s=resolveSchema(input,spec);
  const choices=variants(s,spec);
  if(choices.length===1)s={...resolveSchema(choices[0],spec),description:s.description||resolveSchema(choices[0],spec).description};
  if(root&&s.type==='array'){walk(s.items,path+'[]',depth,required,ancestors,true);return}
  if(root&&s.properties){
   for(const [name,child] of Object.entries(s.properties))walk(child,path?(path+'.'+name):name,depth,s.required?.includes(name)||false,ancestors);
   return;
  }
  result.push({name:path||'значение',type:typeName(input,spec),required,description:s.description||'',constraints:constraints(input,spec),depth});
  if(!expanded)return;
  const target=input?.$ref;
  if(target&&ancestors.has(target))return;
  const next=new Set(ancestors);if(target)next.add(target);
  if(s.properties)for(const [name,child] of Object.entries(s.properties))walk(child,(path?path+'.':'')+name,depth+1,s.required?.includes(name)||false,next);
  if(s.type==='array'&&s.items){
   const item=resolveSchema(s.items,spec);
   if(item.properties)for(const [name,child] of Object.entries(item.properties))walk(child,path+'[].'+name,depth+1,item.required?.includes(name)||false,next);
  }
 };
 walk(schema,prefix,0,true,new Set(),true);
 return result;
}
