import {describe,it,expect} from 'vitest';
import {stableJSON,completeFileOrder,moveInput} from './stable-json';

describe('Firestore value equality',()=>{
 it('does not mark map-key reordering as an unsaved edit',()=>{
  expect(stableJSON({contact:{name:'A',email:'a@example.com'},step:10})).toBe(stableJSON({step:10,contact:{email:'a@example.com',name:'A'}}));
 });
 it('still detects real changes and section reordering',()=>{
  expect(stableJSON({sections:['A','B']})).not.toBe(stableJSON({sections:['B','A']}));
  expect(stableJSON({revision:1})).not.toBe(stableJSON({revision:2}));
 });
});

describe('immediately prepared serverless workspaces',()=>{
 it('initializes an empty order before a delayed status poll completes',()=>{
  expect(completeFileOrder([],2)).toEqual([0,1]);
  expect(moveInput([],2,1,-1)).toEqual([1,0]);
  expect(JSON.stringify(moveInput([],2,1,-1))).not.toContain('null');
 });
 it('rejects partial, duplicate and noninteger permutations',()=>{
  for(const value of [[null,null],[0],[1,1],['0','1'],[0,2]])expect(completeFileOrder(value,2)).toEqual([0,1]);
 });
 it('preserves valid custom order and protects move bounds',()=>{
  expect(completeFileOrder([2,0,1],3)).toEqual([2,0,1]);
  expect(moveInput([1,0],2,0,-1)).toEqual([1,0]);
 });
});
