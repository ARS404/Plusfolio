export type JournalOrder='newest'|'oldest';
type JournalProblem={id:string;worksheet_position?:number;[key:string]:any};
type JournalBlock={issue_id:number;issued_on:string;problems:JournalProblem[];recipient_ids?:number[];[key:string]:any};

export function journalProblemProgress(blocks:JournalBlock[],states:ReadonlyMap<string,{solved:boolean}>,people:{id:number}[]){
 type Cohort={readonly key:string;readonly ids:ReadonlySet<number>};
 const cohort=(ids:ReadonlySet<number>):Cohort=>({key:[...ids].sort((a,b)=>a-b).join(','),ids});
 const visible=new Set(people.map(person=>person.id)),recipients=new Map<string,Cohort>();
 for(const block of blocks){
  if(!block.problems.length)continue;
  const selected=new Set<number>();
  for(const student of block.recipient_ids??[])if(visible.has(student))selected.add(student);
  const group=cohort(selected),unions=new Map<Cohort,Cohort>();
  for(const problem of block.problems){
   const previous=recipients.get(problem.id);
   if(!previous){recipients.set(problem.id,group);continue}
   if(previous===group)continue;
   let merged=unions.get(previous);
   if(!merged){
    merged=previous;
    // Cohorts are shared by tasks; unions must not mutate an earlier cohort.
    if(previous.key!==group.key)for(const student of group.ids)if(!previous.ids.has(student)){merged=cohort(new Set([...previous.ids,...group.ids]));break}
    unions.set(previous,merged);
   }
   if(merged!==previous)recipients.set(problem.id,merged);
  }
 }
 const result=new Map<string,{solved:number;assigned:number;percent:number|null}>();
 for(const [problem,{ids:assigned}] of recipients){
  let solved=0;for(const student of assigned)if(states.get(student+':'+problem)?.solved)solved++;
  result.set(problem,{solved,assigned:assigned.size,percent:assigned.size?100*solved/assigned.size:null});
 }
 return result;
}

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

export function journalTotals(blocks:JournalBlock[],states:{student_id:number;problem_id:string;solved:boolean}[],discussions:{problem_id:string;discussed:boolean}[]=[]){
 const problems=new Set<string>();
 for(const block of blocks)for(const problem of block.problems)problems.add(problem.id);
 const solved=new Map<number,Set<string>>();
 for(const state of states){
  if(!state.solved||!problems.has(state.problem_id))continue;
  const tasks=solved.get(state.student_id)??new Set<string>();
  tasks.add(state.problem_id);solved.set(state.student_id,tasks);
 }
 const discussed=new Set<string>();
 for(const state of discussions)if(state.discussed&&problems.has(state.problem_id))discussed.add(state.problem_id);
 const counts=new Map<number,number>(),solvedDiscussed=new Map<number,number>();
 for(const [student,tasks] of solved){
  counts.set(student,tasks.size);let covered=0;
  for(const id of tasks)if(discussed.has(id))covered++;
  solvedDiscussed.set(student,covered);
 }
 return {total:problems.size,discussed:discussed.size,solved:counts,solvedDiscussed};
}

export function journalStudentSummary(totals:ReturnType<typeof journalTotals>,student:number){
 const solved=totals.solved.get(student)||0,discussedUnsolved=totals.discussed-(totals.solvedDiscussed.get(student)||0);
 return {solved,available:totals.total-solved-discussedUnsolved,discussedUnsolved,total:totals.total};
}
