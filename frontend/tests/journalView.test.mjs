import {test} from 'node:test';
import assert from 'node:assert/strict';
import {journalView,journalTotals} from '../src/journalView.ts';

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
