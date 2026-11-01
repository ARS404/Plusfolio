import {test} from 'node:test';
import assert from 'node:assert/strict';
import {builderProblem,initialBlocks,moveBlock,numberedBlocks,plainToTex,serializeWorksheetBlocks} from '../src/worksheetBlocks.ts';
import {journalView} from '../src/journalView.ts';
test('text blocks do not consume problem numbers when reordered',()=>{
 const blocks=[{kind:'text',text:'Введение'},{kind:'problem',problem_id:'a'},{kind:'text',text:'Определение'},{kind:'problem',problem_id:'b'}];
 assert.deepEqual(numberedBlocks(blocks).map(item=>item.number),[null,1,null,2]);
 const moved=moveBlock(blocks,3,0);assert.deepEqual(numberedBlocks(moved).map(item=>item.number),[1,null,2,null]);
 assert.equal(blocks[0].kind,'text');assert.equal(moveBlock(blocks,-1,0),blocks);
});
test('legacy tasks and existing blocks initialize without dropping theory',()=>{
 assert.deepEqual(initialBlocks({problem_ids:['a','b']}).map(item=>item.problem_id),['a','b']);
 const blocks=initialBlocks({blocks:[{kind:'text',style:'definition',text:'Теория'},{kind:'problem',problem_id:'a'}]});
 assert.equal(blocks[0].text,'Теория');assert.ok(blocks.every(item=>item._key));
});
test('adding TikZ preserves plain text, formulas and uploaded-image markers',()=>{
 const image='\\pfimage{12345678-1234-1234-1234-123456789abc}';
 assert.equal(plainToTex('Счёт 20% & $a_b$\n'+image),'Счёт 20\\% \\& $a_b$\n'+image);
});
test('numbering can start at zero and excluded tasks still receive their printed number',()=>{
 const blocks=initialBlocks({blocks:[{kind:'problem',problem_id:'a',include_in_journal:false},{kind:'text',text:'Теория'},{kind:'problem',problem_id:'b'}]});
 assert.deepEqual(numberedBlocks(blocks,0).map(item=>item.number),[0,null,1]);
 assert.equal(blocks[0].include_in_journal,false);assert.equal(blocks[2].include_in_journal,true);
 assert.equal(initialBlocks({problem_ids:['a']})[0].include_in_journal,true);
 assert.deepEqual(numberedBlocks(moveBlock(blocks,2,0),0).map(item=>item.number),[0,1,null]);
});
test('the journal preserves zero and numbering gaps supplied by the worksheet',()=>{
 const blocks=[{issue_id:1,issued_on:'2026-11-01',problems:[{id:'a',worksheet_position:0},{id:'c',worksheet_position:2}]}];
 assert.deepEqual(journalView(blocks,[],false,'newest')[0].problems.map(problem=>problem.worksheet_position),[0,2]);
 assert.equal(journalView(blocks,[{problem_id:'a',discussed:true}],true,'newest')[0].problems[0].worksheet_position,2);
});
test('API blocks omit editor keys without copying large content or losing journal flags',()=>{
 const images=[{id:'asset',width:70,align:'center',caption:''}];
 const blocks=[{kind:'problem',problem_id:'a',include_in_journal:false,_key:'editor-a'},
  {kind:'text',style:'definition',title:'Теория',text:'Текст',tex:'',images,_key:'editor-b'}];
 const serialized=serializeWorksheetBlocks(blocks);
 assert.equal(serialized[0].include_in_journal,false);assert.ok(serialized.every(block=>!('_key' in block)));
 assert.equal(serialized[1].images,images);assert.equal(blocks[0]._key,'editor-a');
});
test('builder problem summaries retain display fields without bank solutions or attachments',()=>{
 const source={id:'a',title:'Задача',public_id:'P-1',statement:'Условие',solution:'Большое решение',solution_tex:'TeX',solution_images:[{id:'private'}]};
 assert.deepEqual(builderProblem(source),{id:'a',title:'Задача',public_id:'P-1',statement:'Условие'});
 assert.ok('solution' in source);
});
