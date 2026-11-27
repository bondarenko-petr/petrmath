import test from 'node:test';
import assert from 'node:assert/strict';
import {GEOMETRY,geometryBounds} from '../board/frontend/src/geometry.mjs';
test('templates have unique names and native editable elements',()=>{
 assert.equal(new Set(GEOMETRY.map(s=>s.id)).size,GEOMETRY.length);
 assert.equal(new Set(GEOMETRY.map(s=>s.name)).size,GEOMETRY.length);
 for(const spec of GEOMETRY){assert.ok(spec.objects.length);assert.ok(spec.objects.every(o=>['line','arrow','rectangle','diamond','ellipse'].includes(o.type)));const b=geometryBounds(spec.objects);assert.ok(b.every(Number.isFinite));assert.ok(b[2]>b[0] && b[3]>b[1]);}
});
test('equilateral triangle sides are equal',()=>{const p=GEOMETRY.find(s=>s.id==='equilateral').objects[0].points;const lengths=p.slice(1).map((v,i)=>Math.hypot(v[0]-p[i][0],v[1]-p[i][1]));assert.ok(lengths.every(v=>Math.abs(v-140)<.0001));});
test('isosceles triangle sides are equal',()=>{const p=GEOMETRY.find(s=>s.id==='isosceles').objects[0].points;assert.equal(Math.hypot(p[1][0]-p[0][0],p[1][1]-p[0][1]),Math.hypot(p[2][0]-p[1][0],p[2][1]-p[1][1]));});
test('right trapezoid has perpendicular bases and side',()=>{const p=GEOMETRY.find(s=>s.id==='right-trapezoid').objects[0].points;assert.equal(p[0][0],p[3][0]);assert.equal(p[0][1],p[1][1]);assert.equal(p[2][1],p[3][1]);});
test('isosceles trapezoid legs have equal length',()=>{const p=GEOMETRY.find(s=>s.id==='isosceles-trapezoid').objects[0].points;assert.equal(Math.hypot(p[3][0]-p[0][0],p[3][1]-p[0][1]),Math.hypot(p[2][0]-p[1][0],p[2][1]-p[1][1]));});
test('palette contains only twelve geometric figures in three categories',()=>{
 assert.equal(GEOMETRY.length,12);
 assert.deepEqual([...new Set(GEOMETRY.map(s=>s.category))],['Треугольники','Четырёхугольники','Окружность']);
 assert.ok(GEOMETRY.every(s=>s.objects.length===1));
});
for (const spec of GEOMETRY) {
 test(`${spec.name}: nonzero bounds match resize dimensions`, () => {
  assert.equal(spec.objects.length, 1);
  const object = spec.objects[0];
  const [left, top, right, bottom] = geometryBounds(spec.objects);
  assert(object.width > 0 && object.height > 0);
  assert.equal(object.width, right - left);
  assert.equal(object.height, bottom - top);
  if (object.points) {
   assert.deepEqual(object.points[0], [0, 0]);
   assert.deepEqual(object.points.at(-1), object.points[0]);
  }
 });
}
