import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createWorksheetCopy} from '../src/worksheetCopy.ts';

function fixture(){
 const requests=[],completed=[],errors=[],busy=[];
 const operation=createWorksheetCopy({
  copy:id=>new Promise((resolve,reject)=>requests.push({id,resolve,reject})),
  onCopied:reply=>completed.push(reply),
  onError:message=>errors.push(message),
  onBusy:value=>busy.push(value),
 });
 return {operation,requests,completed,errors,busy};
}

test('an active copy reports its result and releases the pending operation',async()=>{
 const {operation,requests,completed,errors,busy}=fixture();
 const first=operation.run('sheet');
 requests[0].resolve({document_id:'copy'});await first;
 assert.deepEqual(completed,[{document_id:'copy'}]);
 assert.deepEqual(errors,[]);
 assert.deepEqual(busy,[true,false]);
 const next=operation.run('sheet');
 assert.equal(requests.length,2);
 requests[1].resolve({document_id:'another-copy'});await next;
});

test('a rapid second click cannot create a duplicate pending copy',async()=>{
 const {operation,requests,completed}=fixture();
 const first=operation.run('sheet');await operation.run('sheet');
 assert.equal(requests.length,1);
 requests[0].resolve({document_id:'copy'});await first;
 assert.equal(completed.length,1);
});

test('closing or replacing the preview leaves the POST running but prevents stale UI changes',async()=>{
 const {operation,requests,completed,errors,busy}=fixture();
 const pending=operation.run('sheet');
 operation.cancel();
 assert.equal(requests.length,1);
 requests[0].resolve({document_id:'created-on-server'});await pending;
 assert.deepEqual(completed,[]); // No closing a newer modal, refresh, navigation or success toast.
 assert.deepEqual(errors,[]);
 assert.deepEqual(busy,[true]); // No state write into the departed owner.
});

test('a cancelled failure cannot toast or clear a replacement operation',async()=>{
 const {operation,requests,completed,errors,busy}=fixture();
 const old=operation.run('old-sheet');operation.cancel();
 const current=operation.run('new-sheet');
 requests[0].reject(new Error('Old context error'));await old;
 await operation.run('duplicate-new-sheet');
 assert.equal(requests.length,2);
 assert.deepEqual(errors,[]);
 requests[1].resolve({document_id:'new-copy'});await current;
 assert.deepEqual(completed,[{document_id:'new-copy'}]);
 assert.deepEqual(busy,[true,true,false]);
});

test('a failure in the current preview reports the error and clears busy state',async()=>{
 const {operation,requests,completed,errors,busy}=fixture();
 const pending=operation.run('missing-sheet');
 requests[0].reject(new Error('Cannot copy'));await pending;
 assert.deepEqual(completed,[]);
 assert.deepEqual(errors,['Cannot copy']);
 assert.deepEqual(busy,[true,false]);
});
