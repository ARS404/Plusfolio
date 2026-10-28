import {test} from 'node:test';
import assert from 'node:assert/strict';
import {matchesEntity} from '../src/entitySearch.ts';
import {roleNames,roleLabel} from '../src/access.ts';
const student={id:3,public_id:'S-3',user_public_id:'U-19'};
test('typed IDs are exact and distinguish the profile from the account',()=>{
 assert.equal(matchesEntity(student,'s-003'),true);
 assert.equal(matchesEntity(student,'U-19'),true);
 assert.equal(matchesEntity(student,'S-19'),false);
 assert.equal(matchesEntity(student,'P-3','P-3 in name'),false);
 assert.equal(matchesEntity(student,'3'),true);
 assert.equal(matchesEntity(student,'19'),false);
});
test('UUID and ordinary names remain searchable',()=>{
 const circle={id:'c94220ed-fcde-4f8a-9695-4e19bbfb451c',public_id:'C-12'};
 assert.equal(matchesEntity(circle,circle.id),true);
 assert.equal(matchesEntity(circle,'москва','Школа','Москва'),true);
 assert.equal(matchesEntity(circle,'C - 0012'),true);
 assert.equal(matchesEntity(circle,'C-1'),false);
 assert.equal(matchesEntity(circle,'   '),true);
});

test('issue aliases find the right worksheet choice',()=>{
 const sheet={id:'uuid',public_id:'W-12',extra_ids:['ISS-19']};
 assert.equal(matchesEntity(sheet,'iss-19'),true);
 assert.equal(matchesEntity(sheet,'ISS-1'),false);
 assert.equal(matchesEntity(sheet,'W-12'),true);
});

test('shared role labels retain form order and unknown-role fallback',()=>{
 assert.deepEqual(Object.keys(roleNames),['admin','teacher','analyst','student']);
 assert.deepEqual(Object.values(roleNames),['Администратор','Преподаватель','Аналитик','Школьник']);
 for(const [role,label] of Object.entries(roleNames))assert.equal(roleLabel(role),label);
 for(const role of ['future-role','constructor','__proto__'])assert.equal(roleLabel(role),role);
});
