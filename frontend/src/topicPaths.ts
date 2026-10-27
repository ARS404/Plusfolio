type Topic={id:string;name:string;parent_id:string|null};
// API catalogues are immutable React snapshots; a replacement array gets a fresh cache.
const indexes=new WeakMap<readonly Topic[],{nodes:Map<string,Topic>;paths:Map<string,string>}>();
export function topicPath(topics:readonly Topic[],id:string){
 let index=indexes.get(topics);
 if(!index){index={nodes:new Map(topics.map(topic=>[topic.id,topic])),paths:new Map()};indexes.set(topics,index)}
 const cached=index.paths.get(id);if(cached!==undefined)return cached;
 const parts:string[]=[];const seen=new Set<string>();let node=index.nodes.get(id);
 while(node&&node.parent_id&&!seen.has(node.id)){seen.add(node.id);parts.unshift(node.name);node=index.nodes.get(node.parent_id)}
 const path=parts.join(' / ')||'Все темы';index.paths.set(id,path);return path;
}
