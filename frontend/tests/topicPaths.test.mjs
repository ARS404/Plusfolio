import test from 'node:test';
import assert from 'node:assert/strict';
import {topicPath,selectableTopics} from '../src/topicPaths.ts';

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

const topic=(id,parent_id,extra={})=>({id,name:id,parent_id,is_other:false,archived:false,sort_order:0,...extra});

test('topic choices preserve order and exclude archived branches and the root',()=>{
 const nodes=[topic('root',null),topic('a','root'),topic('ao','a',{is_other:true}),topic('b','root',{archived:true}),topic('bc','b')];
 const selected=selectableTopics(nodes);
 assert.deepEqual(selected.map(node=>node.id),['a','ao']);
 assert.equal(selected[0],nodes[1]);
 assert.equal(nodes.length,5);
});
test('replacement catalogues update selectable descendants after archiving and moving',()=>{
 const original=[topic('root',null),topic('a','root'),topic('leaf','a')];
 const archived=original.map(node=>node.id==='a'?{...node,archived:true}:node);
 const moved=archived.map(node=>node.id==='leaf'?{...node,parent_id:'root'}:node);
 assert.deepEqual(selectableTopics(original).map(node=>node.id),['a','leaf']);
 assert.deepEqual(selectableTopics(archived),[]);
 assert.deepEqual(selectableTopics(moved).map(node=>node.id),['leaf']);
 assert.deepEqual(selectableTopics(original).map(node=>node.id),['a','leaf']);
 const archivedRoot=original.map(node=>node.id==='root'?{...node,archived:true}:node);
 assert.deepEqual(selectableTopics(archivedRoot),[]);
});
test('topic choices retain bounded legacy traversal for cycles and missing parents',()=>{
 const nodes=[topic('a','b'),topic('b','a'),topic('child','a'),topic('orphan','missing'),topic('root',null)];
 assert.deepEqual(selectableTopics(nodes).map(node=>node.id),['a','b','child','orphan']);
 const archived=nodes.map(node=>node.id==='b'?{...node,archived:true}:node);
 assert.deepEqual(selectableTopics(archived).map(node=>node.id),['orphan']);
});
