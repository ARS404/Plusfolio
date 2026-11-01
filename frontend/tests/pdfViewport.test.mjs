import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PDF_CANVAS_MAX_PIXELS,PDF_CANVAS_MAX_SIDE,pdfViewportScale} from '../src/pdfViewport.ts';

test('ordinary A4 pages retain the existing preview resolution',()=>{
 assert.equal(pdfViewportScale(595.28,841.89),1.5);
});
test('oversized and very wide PDF pages keep canvas dimensions and pixels bounded',()=>{
 for(const [width,height] of [[100000,100000],[1000000,8000],[7000,123456],[1000000,.01]]){
  const scale=pdfViewportScale(width,height);
  const columns=Math.max(1,Math.min(PDF_CANVAS_MAX_SIDE,Math.ceil(width*scale)));
  const rows=Math.max(1,Math.min(PDF_CANVAS_MAX_SIDE,Math.ceil(height*scale)));
  assert.ok(scale>0&&scale<=1.5);assert.ok(columns<=PDF_CANVAS_MAX_SIDE&&rows<=PDF_CANVAS_MAX_SIDE);
  assert.ok(columns*rows<=PDF_CANVAS_MAX_PIXELS);
 }
});
test('invalid PDF dimensions fail before allocating a canvas',()=>{
 for(const size of [0,-1,NaN,Infinity])assert.throws(()=>pdfViewportScale(size,800));
});
