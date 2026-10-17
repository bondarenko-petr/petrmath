const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const calendar=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../landing/dist/weekly-calendar.js'),'utf8')+';WeeklyCalendar',{Intl,Date});
const lesson=(id,start,end)=>({id,starts_at:start,ends_at:end,status:'scheduled',student_name:'Тест'});

test('uses the explicit schedule timezone instead of browser time',()=>{
 const value=calendar.local('2026-10-17T10:30:00Z','Europe/Moscow');
 assert.equal(value.day,'2026-10-17');assert.equal(value.minute,13*60+30);
 const berlin=calendar.local('2026-10-17T10:30:00Z','Europe/Berlin');assert.equal(berlin.minute,12*60+30);
});
test('places and sizes the event at wall-clock start and end',()=>{
 const result=calendar.segments([lesson(1,'2026-10-17T10:30:00Z','2026-10-17T12:00:00Z')],'2026-10-17','Europe/Moscow');
 assert.equal(result.length,1);assert.equal(result[0].start,810);assert.equal(result[0].end,900);
});
test('splits a lesson across midnight without duplicating end midnight',()=>{
 const event=lesson(1,'2026-10-17T20:30:00Z','2026-10-17T22:00:00Z');
 const first=calendar.segments([event],'2026-10-17','Europe/Moscow')[0];
 const second=calendar.segments([event],'2026-10-18','Europe/Moscow')[0];
 assert.equal(first.start,1410);assert.equal(first.end,1440);assert.equal(second.start,0);assert.equal(second.end,60);
 const midnight=lesson(2,'2026-10-17T20:00:00Z','2026-10-17T21:00:00Z');
 assert.equal(calendar.segments([midnight],'2026-10-18','Europe/Moscow').length,0);
});
test('overlapping events use separate lanes and adjacent ones reuse lanes',()=>{
 const events=[{row:{id:1},start:60,end:120},{row:{id:2},start:90,end:150},{row:{id:3},start:120,end:140},{row:{id:4},start:180,end:240}];
 const result=calendar.lanes(events);
 assert.equal(result[0].lanes,2);assert.notEqual(result[0].lane,result[1].lane);
 assert.equal(result.find(e=>e.row.id===3).lane,0);assert.equal(result[3].lanes,1);
 assert.equal(events[0].lane,undefined);
});
test('handles month and year boundaries',()=>{
 assert.equal(calendar.plus('2026-12-28',7),'2027-01-04');assert.equal(calendar.plus('2026-03-01',-1),'2026-02-28');
});
test('short event visual intervals do not cover one another',()=>{
 const rows=[lesson(1,'2026-10-17T09:00:00Z','2026-10-17T09:01:00Z'),lesson(2,'2026-10-17T09:05:00Z','2026-10-17T09:10:00Z')];
 const result=calendar.lanes(calendar.segments(rows,'2026-10-17','UTC'));
 assert.equal(result[0].lanes,2);assert.notEqual(result[0].lane,result[1].lane);
});
