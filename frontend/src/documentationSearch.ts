export type DocumentationOperation = {
 id:string;method:string;path:string;summary:string;description:string;status:number;
 parameters:{name:string;in:string;required:boolean;description?:string;schema:unknown}[];
 body:unknown|null;example:unknown|null;response_example?:unknown;
};
export type DocumentationBlock = {
 title:string;paragraphs?:string[];steps?:string[];bullets?:string[];formula?:string;note?:string;
 table?:{columns:string[];rows:string[][]};code?:{language:string;content:string};
};
export type DocumentationSection = {
 id:string;category:string;title:string;summary:string;keywords?:string;
 required_for_robots?:boolean;instruction_version?:string;applies_when?:string;can_execute?:boolean;
 blocks:DocumentationBlock[];links:{label:string;href:string}[];operations?:DocumentationOperation[];
};
export type DocumentationCatalogue = {
 sections:DocumentationSection[];audience?:'human'|'robot';api_base?:string|null;read_only_token?:boolean;
 markdown_url?:string;openapi_url?:string|null;can_use_api?:boolean;
 instruction_policy_version?:string;
 mandatory_instructions?:{section_id:string;title:string;version:string;required:boolean;applies_when:string;can_execute:boolean;url:string}[];
};

const normalize=(value:string)=>value.toLocaleLowerCase('ru').replace(/ё/g,'е');
export function searchDocumentation(sections:DocumentationSection[],query:string){
 const words=normalize(query).trim().split(/\s+/).filter(Boolean);
 if(!words.length)return sections;
 return sections.filter(section=>{
  const text=normalize([section.title,section.category,section.summary,section.keywords,
   ...section.blocks.flatMap(block=>[block.title,...(block.paragraphs||[]),...(block.steps||[]),...(block.bullets||[]),block.formula,block.note,
    ...(block.table?[...block.table.columns,...block.table.rows.flat()]:[]),block.code?.content]),
   ...(section.operations||[]).flatMap(operation=>[operation.method,operation.path,operation.summary,operation.description,...operation.parameters.map(parameter=>parameter.name)])
  ].filter(Boolean).join(' '));
  return words.every(word=>text.includes(word));
 });
}
