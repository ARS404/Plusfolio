type Entity={id:string|number;extra_ids?:string[];public_id?:string;user_public_id?:string;student_public_id?:string;teacher_public_id?:string};
const prefixes=new Set(['U','S','T','C','P','W','TOP','TAG','INV','ISS']);
export function matchesEntity(entity:Entity,query:string,...text:string[]):boolean{
 const needle=query.trim().toLocaleLowerCase('ru-RU');if(!needle)return true;
 const ids=[entity.public_id,entity.user_public_id,entity.student_public_id,entity.teacher_public_id,...(entity.extra_ids||[])].filter(Boolean) as string[];
 const typed=/^([a-z]+)\s*-\s*([0-9]+)$/i.exec(needle);
 if(typed&&prefixes.has(typed[1].toUpperCase()))return ids.some(id=>id.toLowerCase()===typed[1]+'-'+(typed[2].replace(/^0+/,'')||'0'));
 if(/^[0-9]+$/.test(needle))return entity.public_id?.split('-').at(-1)===(needle.replace(/^0+/,'')||'0');
 return String(entity.id).toLowerCase()===needle||text.join(' ').toLocaleLowerCase('ru-RU').includes(needle);
}
