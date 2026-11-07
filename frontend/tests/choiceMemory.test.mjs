import {test} from 'node:test';
import assert from 'node:assert/strict';
import {rememberChoices} from '../src/choiceMemory.ts';

test('selected labels survive a filtered page and refresh from current options',()=>{
 const first={value:'a',label:'Old title'},second={value:'b',label:'Second'};
 const initial=rememberChoices(new Map(),[first,second],[]);
 const filtered=rememberChoices(initial,[{value:'c',label:'New page'}],['a']);
 assert.equal(filtered.get('a'),first);
 assert.equal(filtered.has('b'),false);
 const updated={value:'a',label:'Renamed'};
 assert.equal(rememberChoices(filtered,[updated],['a']).get('a'),updated);
 assert.deepEqual([...rememberChoices(filtered,[],[]).keys()],[]);
 assert.equal(initial.get('b'),second);
});

test('many result pages retain only the current page and absent selections',()=>{
 let known=rememberChoices(new Map(),[{value:'selected',label:'Kept'}],['selected']);
 for(let page=0;page<1000;page++){
  const options=Array.from({length:100},(_,index)=>({value:`${page}:${index}`,label:'Result'}));
  known=rememberChoices(known,options,['selected']);
  assert.equal(known.size,101);
  assert.equal(known.get('selected').label,'Kept');
 }
 assert.equal(known.has('0:0'),false);
 assert.equal(rememberChoices(known,[],['never-loaded']).size,0);
});
