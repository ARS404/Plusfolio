import {test} from 'node:test';
import assert from 'node:assert/strict';
import {journalView,journalTotals,journalStudentSummary,journalProblemProgress} from '../src/journalView.ts';

const blocks=[
 {issue_id:3,issued_on:'2026-10-22',problems:[{id:'a'},{id:'b'},{id:'c'}]},
 {issue_id:2,issued_on:'2026-10-22',problems:[{id:'a'}]},
 {issue_id:1,issued_on:'2026-10-01',problems:[{id:'b'},{id:'a'}]},
 {issue_id:4,issued_on:'2026-10-25',problems:[]},
];
test('journal sorts by issue date with a stable tie break in either direction',()=>{
 assert.deepEqual(journalView(blocks,[],false,'newest').map(block=>block.issue_id),[4,3,2,1]);
 assert.deepEqual(journalView(blocks,[],false,'oldest').map(block=>block.issue_id),[1,2,3,4]);
 assert.deepEqual(blocks.map(block=>block.issue_id),[3,2,1,4]);
});
test('hiding discussed tasks preserves worksheet numbers, repeated tasks and theory',()=>{
 const visible=journalView(blocks,[{problem_id:'a',discussed:true},{problem_id:'b',discussed:false}],true,'oldest');
 assert.deepEqual(visible.map(block=>[block.issue_id,block.problems.map(problem=>[problem.id,problem.worksheet_position])]),[
  [1,[['b',1]]],[3,[['b',2],['c',3]]],[4,[]],
 ]);
 assert.equal(blocks[0].problems.length,3);
 assert.equal(blocks[0].problems[1].worksheet_position,undefined);
});
test('clearing the filter restores every task with its original numbering',()=>{
 const discussed=['a','b','c'].map(problem_id=>({problem_id,discussed:true}));
 assert.deepEqual(journalView(blocks,discussed,true,'newest').map(block=>block.issue_id),[4]);
 assert.deepEqual(journalView(blocks,discussed,false,'oldest').map(block=>block.problems.length),[2,1,3,0]);
 const filtered=[{issue_id:9,issued_on:'2026-10-01',problems:[{id:'c',worksheet_position:7}]}];
 assert.equal(journalView(filtered,[],true,'newest')[0].problems[0].worksheet_position,7);
});
test('row totals count unique tasks across worksheets and separate each student',()=>{
 const totals=journalTotals(blocks,[
  {student_id:1,problem_id:'a',solved:true},{student_id:1,problem_id:'a',solved:true},
  {student_id:1,problem_id:'b',solved:true},{student_id:1,problem_id:'c',solved:false},
  {student_id:2,problem_id:'c',solved:true},{student_id:2,problem_id:'foreign',solved:true},
 ]);
 assert.equal(totals.total,3);assert.equal(totals.solved.get(1),2);assert.equal(totals.solved.get(2),1);
 assert.equal(totals.solved.get(3)??0,0);
});
test('totals reflect visible tasks and changed solve marks',()=>{
 const visible=journalView(blocks,[{problem_id:'a',discussed:true}],true,'oldest');
 const states=[{student_id:1,problem_id:'a',solved:true},{student_id:1,problem_id:'b',solved:true}];
 assert.equal(journalTotals(visible,states).total,2);assert.equal(journalTotals(visible,states).solved.get(1),1);
 assert.equal(journalTotals(visible,[...states,{student_id:1,problem_id:'c',solved:true}]).solved.get(1),2);
 assert.equal(journalTotals([blocks[1]],states).total,1);assert.equal(journalTotals([blocks[1]],states).solved.get(1),1);
});
test('empty and theory-only views have no solved tasks',()=>{
 const states=[{student_id:1,problem_id:'a',solved:true}];
 for(const view of [[],[blocks[3]]]){
  const totals=journalTotals(view,states);assert.equal(totals.total,0);assert.equal(totals.solved.size,0);
 }
});
test('numbered server tasks and unaffected blocks are shared without cloning',()=>{
 const original=[
  {issue_id:1,issued_on:'2026-10-01',problems:[{id:'a',worksheet_position:0},{id:'b',worksheet_position:2}]},
  {issue_id:2,issued_on:'2026-10-02',problems:[{id:'c',worksheet_position:1}]},
 ];
 const all=journalView(original,[],false,'oldest');
 assert.notEqual(all,original);assert.equal(all[0],original[0]);assert.equal(all[1],original[1]);
 const hidden=journalView(original,[{problem_id:'a',discussed:true}],true,'oldest');
 assert.equal(hidden[1],original[1]);assert.equal(hidden[0].problems[0],original[0].problems[1]);
 assert.equal(hidden[0].problems[0].worksheet_position,2);assert.equal(original[0].problems.length,2);
});

test('summary partitions selected unique tasks into solved, available and discussed unsolved',()=>{
 const slice=[{issue_id:1,issued_on:'2026-01-01',problems:[{id:'a'},{id:'b'},{id:'c'},{id:'d'}]},{issue_id:2,issued_on:'2026-02-01',problems:[{id:'a'}]}];
 const discussions=[{problem_id:'a',discussed:true},{problem_id:'b',discussed:true}];
 const marks=[{student_id:1,problem_id:'a',solved:true},{student_id:1,problem_id:'c',solved:true}];
 assert.deepEqual(journalStudentSummary(journalTotals(slice,marks,discussions),1),{solved:2,available:1,discussedUnsolved:1,total:4});
 assert.deepEqual(journalStudentSummary(journalTotals(slice,marks,discussions),2),{solved:0,available:2,discussedUnsolved:2,total:4});
 const hidden=journalView(slice,discussions,true,'oldest');
 assert.deepEqual(journalStudentSummary(journalTotals(hidden,marks,discussions),1),{solved:1,available:1,discussedUnsolved:0,total:2});
});

test('task progress unions recipients across selected issues and ignores solves from nonrecipients',()=>{
 const slice=[
  {issue_id:1,issued_on:'2026-01-01',recipient_ids:[1,2],problems:[{id:'a'},{id:'b'}]},
  {issue_id:2,issued_on:'2026-02-01',recipient_ids:[2,3],problems:[{id:'a'}]},
 ];
 const states=new Map([['1:a',{solved:true}],['2:a',{solved:false}],['3:a',{solved:true}],['3:b',{solved:true}],['4:a',{solved:true}]]);
 const progress=journalProblemProgress(slice,states,[1,2,3,4].map(id=>({id})));
 assert.deepEqual(progress.get('a'),{solved:2,assigned:3,percent:200/3});
 assert.deepEqual(progress.get('b'),{solved:0,assigned:2,percent:0});
 assert.deepEqual(journalProblemProgress([slice[0]],states,[{id:2},{id:3}]).get('a'),{solved:0,assigned:1,percent:0});
 assert.deepEqual(journalProblemProgress(slice,states,[{id:3}]).get('a'),{solved:1,assigned:1,percent:100});
 assert.deepEqual(journalProblemProgress(slice,states,[]).get('a'),{solved:0,assigned:0,percent:null});
 assert.deepEqual(slice[0].recipient_ids,[1,2]);
});

test('task progress follows hidden tasks and does not invent recipients without assignment metadata',()=>{
 const slice=[{issue_id:1,issued_on:'2026-01-01',recipient_ids:[1],problems:[{id:'a'},{id:'b'}]}];
 const visible=journalView(slice,[{problem_id:'a',discussed:true}],true,'oldest');
 const progress=journalProblemProgress(visible,new Map(),[{id:1}]);
 assert.equal(progress.has('a'),false);assert.equal(progress.get('b').assigned,1);
 assert.deepEqual(journalProblemProgress(blocks,new Map(),[{id:1}]).get('a'),{solved:0,assigned:0,percent:null});
});

test('many different issue cohorts do not enlarge tasks confined to an earlier issue',()=>{
 const slice=Array.from({length:100},(_,index)=>({issue_id:index+1,issued_on:'2026-01-01',recipient_ids:[index+1],problems:[{id:'shared'},...(index===0?[{id:'early'}]:[])]}));
 const states=new Map(Array.from({length:100},(_,index)=>[(index+1)+':shared',{solved:true}]));
 states.set('2:early',{solved:true});
 const result=journalProblemProgress(slice,states,Array.from({length:100},(_,index)=>({id:index+1})));
 assert.deepEqual(result.get('shared'),{solved:100,assigned:100,percent:100});
 assert.deepEqual(result.get('early'),{solved:0,assigned:1,percent:0});
});
