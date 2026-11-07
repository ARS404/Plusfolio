import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createMaterialDetailLoader} from '../src/materialDetail.ts';

function fixture(){
 const requests=[],opened=[],errors=[];
 const loader=createMaterialDetailLoader({
  load:(path,signal)=>new Promise((resolve,reject)=>requests.push({path,signal,resolve,reject})),
  onOpen:(data,kind)=>opened.push({data,kind}),
  onError:message=>errors.push(message),
 });
 return {loader,requests,opened,errors};
}

test('leaving any material preview owner suppresses its delayed privileged response',async()=>{
 for(const path of ['/materials/problem/1?circle=old-circle','/my-problems/1','/my-issues/1','/materials/problem/1']){
  const {loader,requests,opened,errors}=fixture();
  const pending=loader.open(path);
  assert.equal(requests[0].path,path);
  loader.cancel(); // The hook cleanup runs on unmount or account/circle/material-kind change.
  assert.equal(requests[0].signal.aborted,true);
  requests[0].resolve({id:'1',solution:'Adult-only solution'}); // Even a transport ignoring abort cannot open it.
  await pending;
  assert.deepEqual(opened,[]);
  assert.deepEqual(errors,[]);
 }
});

test('the latest material wins and completed requests are released',async()=>{
 const {loader,requests,opened,errors}=fixture();
 const old=loader.open('/materials/problem/old');
 const latest=loader.open('/my-issues/new','worksheet');
 assert.equal(requests[0].signal.aborted,true);
 requests[1].resolve({id:'new'});await latest;
 requests[0].resolve({id:'old'});await old;
 assert.deepEqual(opened,[{data:{id:'new'},kind:'worksheet'}]);
 assert.deepEqual(errors,[]);
 loader.cancel();
 assert.equal(requests[1].signal.aborted,false);
});

test('an obsolete failure cannot clear the newer pending request or show a toast',async()=>{
 const {loader,requests,opened,errors}=fixture();
 const old=loader.open('/materials/problem/old');
 const latest=loader.open('/materials/problem/new');
 requests[0].reject(new Error('Obsolete error'));await old;
 loader.cancel();
 assert.equal(requests[1].signal.aborted,true);
 requests[1].resolve({id:'new'});await latest;
 assert.deepEqual(opened,[]);
 assert.deepEqual(errors,[]);
});

test('an active load failure remains visible and cancellation can be reused after effect rehearsal',async()=>{
 const {loader,requests,opened,errors}=fixture();
 loader.cancel();
 const failed=loader.open('/materials/problem/missing');
 requests[0].reject(new Error('Unavailable'));await failed;
 assert.deepEqual(errors,['Unavailable']);
 const retry=loader.open('/materials/problem/available');
 requests[1].resolve({id:'available'});await retry;
 assert.deepEqual(opened,[{data:{id:'available'},kind:'problem'}]);
});
