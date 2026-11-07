/** Preserve labels across filtered pages without retaining every visited result. */
export function rememberChoices<T extends {value:string}>(previous:ReadonlyMap<string,T>,options:readonly T[],selected:readonly string[]):Map<string,T>{
 const current=new Map(options.map(option=>[option.value,option]));
 for(const value of selected){
  const remembered=previous.get(value);
  if(!current.has(value)&&remembered)current.set(value,remembered);
 }
 return current;
}
