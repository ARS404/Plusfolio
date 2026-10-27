import {test} from 'node:test';
import assert from 'node:assert/strict';
import {searchDocumentation} from '../src/documentationSearch.ts';

const section={id:'copy',title:'Личные копии',category:'Материалы',summary:'Создание копии',links:[],blocks:[
 {title:'Идентификаторы',table:{columns:['Поле','Назначение'],rows:[['document_id','Стабильный UUID листка']]}},
 {title:'Пример',code:{language:'bash',content:'curl /api/v1/worksheets/{pk}/copy'}},
],operations:[{id:'edit',method:'PATCH',path:'/api/v1/worksheet-documents/{pk}',summary:'Редактировать',description:'Проверяется авторство',parameters:[{name:'version'}]}]};

test('robot search indexes endpoint paths, parameters, examples and tables',()=>{
 for(const query of ['PATCH worksheet-documents','version','curl worksheets','стабильный uuid']){
  assert.deepEqual(searchDocumentation([section],query),[section]);
 }
 assert.deepEqual(searchDocumentation([section],'users'),[]);
});
