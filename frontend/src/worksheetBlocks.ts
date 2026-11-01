export type ContentImage={id:string;width:number;align:'left'|'center'|'right';caption:string};
export type TextBlock={kind:'text';style:string;title:string;text:string;tex:string;images:ContentImage[];_key?:string};
export type ProblemBlock={kind:'problem';problem_id:string;include_in_journal?:boolean;_key?:string};
export type WorksheetBlock=TextBlock|ProblemBlock;
export const blockStyles:Record<string,string>={plain:'Обычный текст',heading:'Заголовок',definition:'Определение',theorem:'Теорема',lemma:'Лемма',example:'Пример',remark:'Замечание'};
export function initialBlocks(value:any):WorksheetBlock[]{return (value.blocks?.length?value.blocks:(value.problem_ids||value.problems||[]).map((problem:any)=>({kind:'problem',problem_id:typeof problem==='string'?problem:problem.id}))).map((block:WorksheetBlock)=>({...block,...(block.kind==='problem'?{include_in_journal:block.include_in_journal!==false}:{}),_key:crypto.randomUUID()}))}
export function numberedBlocks(blocks:WorksheetBlock[],start=1){let number=start;return blocks.map(block=>({block,number:block.kind==='problem'?number++:null}))}
export function moveBlock(blocks:WorksheetBlock[],from:number,to:number){if(from<0||to<0||from>=blocks.length||to>=blocks.length)return blocks;const next=[...blocks];const [block]=next.splice(from,1);next.splice(to,0,block);return next}
export function plainToTex(text:string){const escapes:Record<string,string>={'\\':'\\textbackslash{}','{':'\\{','}':'\\}','$':'\\$','&':'\\&','#':'\\#','%':'\\%','_':'\\_','^':'\\textasciicircum{}','~':'\\textasciitilde{}'};return text.split(/(\$[^$\n]+\$|\\pfimage\{[0-9a-f-]{36}\})/g).map(part=>part.startsWith('$')&&part.endsWith('$')||/^\\pfimage\{[0-9a-f-]{36}\}$/.test(part)?part:part.replace(/[\\{}$&#%_^~]/g,character=>escapes[character])).join('')}

export type BuilderProblem={id:string;title:string;public_id?:string;statement?:string};
export function builderProblem(problem:any):BuilderProblem{return {id:problem.id,title:problem.title,public_id:problem.public_id,statement:problem.statement}}
export function serializeWorksheetBlocks(blocks:WorksheetBlock[]):WorksheetBlock[]{return blocks.map(({_key,...block})=>block)}
