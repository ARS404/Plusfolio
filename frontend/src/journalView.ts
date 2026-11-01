export type JournalOrder='newest'|'oldest';
type JournalProblem={id:string;worksheet_position?:number;[key:string]:any};
type JournalBlock={issue_id:number;issued_on:string;problems:JournalProblem[];[key:string]:any};

export function journalView(blocks:JournalBlock[],discussions:{problem_id:string;discussed:boolean}[],hideDiscussed:boolean,order:JournalOrder):JournalBlock[]{
 const discussed=hideDiscussed?new Set(discussions.filter(state=>state.discussed).map(state=>state.problem_id)):null;
 return blocks.flatMap(block=>{
  let problems:JournalProblem[]|null=null;
  for(let index=0;index<block.problems.length;index++){
   const problem=block.problems[index];
   if(discussed?.has(problem.id)){problems??=block.problems.slice(0,index);continue}
   if(problem.worksheet_position==null){problems??=block.problems.slice(0,index);problems.push({...problem,worksheet_position:index+1})}
   else problems?.push(problem);
  }
  if(problems===null)return [block];
  return block.problems.length&&!problems.length?[]:[{...block,problems}];
 }).sort((a,b)=>((a.issued_on.localeCompare(b.issued_on)||a.issue_id-b.issue_id)*(order==='oldest'?1:-1)));
}

export function journalTotals(blocks:JournalBlock[],states:{student_id:number;problem_id:string;solved:boolean}[]){
 const problems=new Set<string>();
 for(const block of blocks)for(const problem of block.problems)problems.add(problem.id);
 const solved=new Map<number,Set<string>>();
 for(const state of states){
  if(!state.solved||!problems.has(state.problem_id))continue;
  const tasks=solved.get(state.student_id)??new Set<string>();
  tasks.add(state.problem_id);solved.set(state.student_id,tasks);
 }
 return {total:problems.size,solved:new Map([...solved].map(([student,tasks])=>[student,tasks.size]))};
}
