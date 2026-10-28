export type TopicNode={id:string;name:string;parent_id:string|null};
export type Topic=TopicNode&{public_id?:string;is_other:boolean;archived:boolean;sort_order:number};
// API catalogues are immutable React snapshots; a replacement array gets a fresh cache.
const indexes=new WeakMap<readonly TopicNode[],{nodes:Map<string,TopicNode>;paths:Map<string,string>}>();
export function topicPath(topics:readonly TopicNode[],id:string){
 let index=indexes.get(topics);
 if(!index){index={nodes:new Map(topics.map(topic=>[topic.id,topic])),paths:new Map()};indexes.set(topics,index)}
 const cached=index.paths.get(id);if(cached!==undefined)return cached;
 const parts:string[]=[];const seen=new Set<string>();let node=index.nodes.get(id);
 while(node&&node.parent_id&&!seen.has(node.id)){seen.add(node.id);parts.unshift(node.name);node=index.nodes.get(node.parent_id)}
 const path=parts.join(' / ')||'Все темы';index.paths.set(id,path);return path;
}

export function selectableTopics(topics:readonly Topic[]):Topic[]{
 const nodes=new Map(topics.map(topic=>[topic.id,topic]));
 return topics.filter(topic=>{
  if(!topic.parent_id)return false;
  const seen=new Set<string>();let node:Topic|undefined=topic;
  while(node&&!seen.has(node.id)){
   if(node.archived)return false;
   seen.add(node.id);node=node.parent_id?nodes.get(node.parent_id):undefined;
  }
  return true;
 });
}
