import {test} from 'node:test';
import assert from 'node:assert/strict';
import {endpoints,filterEndpoints,resolveSchema,schemaFields,typeName,variants} from '../src/apiReference.ts';

const spec={openapi:'3.1.0',info:{title:'Test',version:'1'},servers:[{url:'/api/v1'}],components:{schemas:{
 Person:{type:'object',title:'Школьник',required:['id'],properties:{id:{type:'integer',description:'ID школьника'},name:{type:'string'}}},
 Row:{type:'object',required:['user'],properties:{user:{$ref:'#/components/schemas/Person'},grade:{anyOf:[{type:'integer'},{type:'null'}]}}},
 Loop:{$ref:'#/components/schemas/Loop'},
}},paths:{'/worksheets/{pk}/copy':{post:{operationId:'copy',summary:'Скопировать листок',description:'Личная версия',tags:['worksheets'],responses:{201:{description:'OK'}}}},'/account':{get:{operationId:'profile',summary:'Мой профиль',responses:{200:{description:'OK'}}},parameters:[]}}};

test('reference reads only actual HTTP operations from the supplied scoped schema',()=>{
 const items=endpoints(spec);
 assert.equal(items.length,2);
 assert.equal(items[0].path,'/api/v1/worksheets/{pk}/copy');
 assert.equal(items[0].method,'POST');
 assert.deepEqual(filterEndpoints(items,'листок',['POST'],['worksheets']).map(i=>i.id),['copy']);
 assert.deepEqual(filterEndpoints(items,'',['GET','POST'],['account']).map(i=>i.id),['profile']);
 assert.deepEqual(filterEndpoints(items,'users'),[]);
});
test('field tables resolve references, preserve required fields and show nested arrays',()=>{
 const rows=schemaFields({type:'array',items:{$ref:'#/components/schemas/Row'}},spec,true);
 assert.equal(rows.find(row=>row.name==='[].user').required,true);
 assert.equal(rows.find(row=>row.name==='[].user.id').type,'целое число');
 assert.equal(rows.find(row=>row.name==='[].user.name').required,false);
 assert.equal(rows.find(row=>row.name==='[].grade').type,'целое число или null');
});
test('schema choices distinguish list/page variants and nullable values',()=>{
 assert.equal(variants({anyOf:[{type:'string'},{type:'null'}]},spec).length,1);
 assert.equal(variants({anyOf:[{type:'array',items:{type:'string'}},{type:'object'}]},spec).length,2);
 assert.equal(typeName({type:['integer','null']},spec),'целое число или null');
 assert.equal(typeName({type:'string',format:'uuid'},spec),'UUID');
 assert.equal(resolveSchema({$ref:'#/components/schemas/Loop'},spec).type,'object');
});
