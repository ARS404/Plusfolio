import {test} from 'node:test';
import assert from 'node:assert/strict';
import {searchDocumentation} from '../src/documentationSearch.ts';

const sections=[
 {id:'invites',category:'Доступ',title:'Приглашения',summary:'Новый участник',keywords:'инвайт',blocks:[{title:'Создать',steps:['Укажите email и выберите кружок.'],note:'Ссылка действует 7 суток.'}],links:[]},
 {id:'analytics',category:'Результаты',title:'Аналитика',summary:'Учёт прогресса',blocks:[{title:'Формула',paragraphs:['Уникальные пары школьник × задача.'],formula:'Процент = решённые / назначенные × 100%'}],links:[]},
];

test('search reads complete instructions, aliases and formulae',()=>{
 assert.deepEqual(searchDocumentation(sections,'инвайт').map(s=>s.id),['invites']);
 assert.deepEqual(searchDocumentation(sections,'email кружок').map(s=>s.id),['invites']);
 assert.deepEqual(searchDocumentation(sections,'7 суток').map(s=>s.id),['invites']);
 assert.deepEqual(searchDocumentation(sections,'решенные 100%').map(s=>s.id),['analytics']);
});
test('search handles Russian case, ё and whitespace',()=>{
 assert.deepEqual(searchDocumentation(sections,'  УЧЕТ   прогресса  ').map(s=>s.id),['analytics']);
 assert.equal(searchDocumentation(sections,'  '),sections);
 assert.deepEqual(searchDocumentation(sections,'несуществующая инструкция'),[]);
});
test('search never adds sections outside its permission-filtered input',()=>{
 const allowed=sections.filter(s=>s.id==='analytics');
 assert.deepEqual(searchDocumentation(allowed,'инвайт'),[]);
 assert.deepEqual(searchDocumentation(allowed,''),allowed);
});
