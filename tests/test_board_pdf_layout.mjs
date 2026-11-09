import test from 'node:test';
import assert from 'node:assert/strict';
import {planPdfPages} from '../board/frontend/src/pdf-layout.mjs';
test('empty sheet',()=>assert.deepEqual(planPdfPages([]),[]));
test('short sheet fits without stretching vertically',()=>{const p=planPdfPages([[0,0,800,300]]);assert.equal(p.length,1);assert.equal(p[0].width,832);assert.equal(p[0].height,332)});
test('long sheet splits in gaps without cutting tasks',()=>{
 const boxes=Array.from({length:8},(_,i)=>[0,i*600,800,i*600+460]);const pages=planPdfPages(boxes);
 assert.equal(pages.length,4);assert.ok(pages.every(p=>!p.hardCut));
 for(const box of boxes)assert.ok(pages.some(p=>p.y<=box[1] && p.y+p.height>=box[3]));
});
test('same width and left edge on each page',()=>{const p=planPdfPages([[0,0,800,300],[400,1500,800,1800]]);assert.ok(p.every(b=>b.width===p[0].width&&b.x===p[0].x));});
test('one oversized image continues with overlap',()=>{const p=planPdfPages([[0,0,800,5000]]);assert.ok(p.length>1);for(let i=1;i<p.length;i++)assert.ok(p[i].y<p[i-1].y+p[i-1].height);assert.ok(p.at(-1).y+p.at(-1).height>=5000)});
test('far vertical gaps are skipped',()=>{const p=planPdfPages([[0,0,800,300],[0,50000,800,50300]]);assert.equal(p.length,2);assert.ok(p[1].y>49000)});
test('negative coordinates preserved',()=>{const p=planPdfPages([[-500,-500,300,-100]]);assert.equal(p[0].x,-516);assert.equal(p[0].y,-516)});
test('extreme sheets fail safely rather than creating unbounded pages',()=>assert.throws(()=>planPdfPages([[0,0,1,10000000]])));

test('invalid bounds fail without producing an empty PDF',()=>assert.throws(()=>planPdfPages([[0,0,NaN,100]])));
