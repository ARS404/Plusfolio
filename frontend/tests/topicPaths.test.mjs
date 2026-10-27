import test from 'node:test';
import assert from 'node:assert/strict';
import {topicPath} from '../src/topicPaths.ts';

test('root, unknown nodes and distinct Other branches keep their paths',()=>{
 const nodes=[{id:'root',name:'Математика',parent_id:null},{id:'a',name:'Алгебра',parent_id:'root'},{id:'b',name:'Геометрия',parent_id:'root'},{id:'ao',name:'Прочее',parent_id:'a'},{id:'bo',name:'Прочее',parent_id:'b'}];
 for(let repeat=0;repeat<2;repeat++){
  assert.equal(topicPath(nodes,'root'),'Все темы');assert.equal(topicPath(nodes,'missing'),'Все темы');
  assert.equal(topicPath(nodes,'ao'),'Алгебра / Прочее');assert.equal(topicPath(nodes,'bo'),'Геометрия / Прочее');
 }
});
test('new catalogue snapshots invalidate renamed and moved ancestors',()=>{
 const original=[{id:'root',name:'Root',parent_id:null},{id:'a',name:'Before',parent_id:'root'},{id:'b',name:'Leaf',parent_id:'a'}];
 assert.equal(topicPath(original,'b'),'Before / Leaf');
 const renamed=original.map(node=>node.id==='a'?{...node,name:'After'}:node);
 assert.equal(topicPath(renamed,'b'),'After / Leaf');
 const moved=renamed.map(node=>node.id==='b'?{...node,parent_id:'root'}:node);
 assert.equal(topicPath(moved,'b'),'Leaf');assert.equal(topicPath(original,'b'),'Before / Leaf');
});
test('malformed cycles retain bounded path traversal',()=>{
 const nodes=[{id:'a',name:'A',parent_id:'b'},{id:'b',name:'B',parent_id:'a'}];
 assert.equal(topicPath(nodes,'a'),'B / A');assert.equal(topicPath(nodes,'b'),'A / B');
});
