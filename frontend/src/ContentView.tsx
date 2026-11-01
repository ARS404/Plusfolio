import React from 'react';
import katex from 'katex';
import type {ContentImage,WorksheetBlock} from './worksheetBlocks';
import {blockStyles} from './worksheetBlocks';
function Plain({text}:{text:string}){return <>{text.split(/(\$[^$\n]+\$)/g).map((part,index)=>part.startsWith('$')&&part.endsWith('$')?<span key={index} dangerouslySetInnerHTML={{__html:katex.renderToString(part.slice(1,-1),{throwOnError:false,trust:false,maxExpand:300,maxSize:20})}}/>:<React.Fragment key={index}>{part}</React.Fragment>)}</>}
export function ContentView({text='',tex='',images=[]}:{text?:string;tex?:string;images?:ContentImage[]}){
 const used=new Set<string>();
 const figure=(image:ContentImage)=>{used.add(image.id);return <figure key={image.id} className={'content-figure align-'+image.align}><img src={'/api/images/'+image.id} alt={image.caption||'Иллюстрация'} style={{width:image.width+'%'}}/>{image.caption&&<figcaption>{image.caption}</figcaption>}</figure>};
 return <div className="content-view">{tex?<p className="content-tex-note">Точная вёрстка с TeX и TikZ доступна в PDF.</p>:text.split(/(\\pfimage\{[0-9a-f-]{36}\})/g).map((part,index)=>{const match=part.match(/^\\pfimage\{([0-9a-f-]{36})\}$/);if(match){const image=images.find(image=>image.id===match[1]);return image?figure(image):null}return <span key={'text-'+index} className="content-paragraph"><Plain text={part}/></span>})}{images.filter(image=>!used.has(image.id)).map(figure)}</div>
}
export function WorksheetContents({blocks,problems,onProblem,numberingStart=1}:{numberingStart?:number;blocks:WorksheetBlock[];problems:any[];onProblem:(problem:any)=>void}){
 const lookup=new Map(problems.map(problem=>[problem.id,problem]));let number=numberingStart-1;
 return <div className="worksheet-content-list">{blocks.map((block,index)=>{if(block.kind==='problem'){const problem=lookup.get(block.problem_id);number++;return problem?<button type="button" key={index} className="worksheet-problem-row" onClick={()=>onProblem(problem)}><span className="square-icon">{number}</span><div><h4>{problem.title}</h4><span className="entity-id">{problem.public_id}</span>{!problem.statement_tex&&<p>{problem.statement?.replace(/\\pfimage\{[^}]+\}/g,'')}</p>}</div></button>:null}return <section key={index} className={'worksheet-text-block text-'+block.style}>{(block.title||block.style!=='plain')&&<h4>{block.style!=='plain'&&block.style!=='heading'?blockStyles[block.style]+(block.title?': ':''):''}{block.title}</h4>}<ContentView text={block.text} tex={block.tex} images={block.images}/></section>})}</div>
}
