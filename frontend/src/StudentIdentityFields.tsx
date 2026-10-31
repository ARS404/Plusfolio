export type StudentIdentity={last_name:string;first_name:string;patronymic:string;no_patronymic:boolean;graduation_year:string};

export const studentIdentity=(user?:{last_name?:string;first_name?:string;patronymic?:string;no_patronymic?:boolean;graduation_year?:number|null}):StudentIdentity=>({
 last_name:user?.last_name??'',first_name:user?.first_name??'',patronymic:user?.patronymic??'',
 no_patronymic:!!user?.no_patronymic,graduation_year:String(user?.graduation_year??''),
});

export default function StudentIdentityFields({value,onChange}:{value:StudentIdentity;onChange:(value:StudentIdentity)=>void}){
 return <>
  {([['last_name','Фамилия','family-name'],['first_name','Имя','given-name'],['patronymic','Отчество','additional-name']] as const).map(([field,label,autoComplete])=><label key={field}>{label}<input aria-label={label} autoComplete={autoComplete} maxLength={120} value={value[field]} disabled={field==='patronymic'&&value.no_patronymic} required={field!=='patronymic'||!value.no_patronymic} onChange={event=>onChange({...value,[field]:event.target.value})}/></label>)}
  <label className="identity-no-patronymic"><input type="checkbox" checked={value.no_patronymic} onChange={event=>onChange({...value,no_patronymic:event.target.checked,patronymic:event.target.checked?'':value.patronymic})}/>У меня нет отчества</label>
  <label>Год окончания 11-го класса<input aria-label="Год окончания 11-го класса" type="number" min={1900} max={2200} step={1} value={value.graduation_year} onChange={event=>onChange({...value,graduation_year:event.target.value})} required/></label>
 </>;
}
