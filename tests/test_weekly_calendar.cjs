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

test('Berlin secondary scale follows the displayed dates including DST week',()=>{
 const summer=calendar.secondaryHours('2026-10-12',8,'Europe/Moscow','Europe/Berlin');
 assert.equal(summer[0].values[0].time,'07:00');
 const transition=calendar.secondaryHours('2026-10-19',8,'Europe/Moscow','Europe/Berlin');
 assert.equal(transition[0].values[0].time,'07:00');
 assert.equal(transition[6].values[0].time,'06:00');
 const winter=calendar.secondaryHours('2026-10-26',8,'Europe/Moscow','Europe/Berlin');
 assert.equal(winter[0].values[0].time,'06:00');
});
test('marks secondary dates and rejects missing or ambiguous primary wall time',()=>{
 const rows=calendar.secondaryHours('2026-10-12',0,'Europe/Moscow','Europe/Berlin');
 assert.equal(rows[0].values[0].dayOffset,-1);
 assert.equal(calendar.instants('2027-03-28',150,'Europe/Berlin').length,0);
 assert.equal(calendar.instants('2027-10-31',150,'Europe/Berlin').length,2);
 assert.equal(calendar.selection('2027-03-28',90,180,'Europe/Berlin'),null);
});
test('selected intervals use 15-minute cells and support reverse drag',()=>{
 const forward=calendar.selection('2027-01-04',900,930,'Europe/Moscow');
 assert.equal(forward.value,'2027-01-04T15:00');assert.equal(forward.duration,45);
 const reverse=calendar.selection('2027-01-04',930,900,'Europe/Moscow');
 assert.equal(reverse.value,forward.value);assert.equal(reverse.duration,45);
 const midnight=calendar.selection('2027-01-04',1425,1425,'Europe/Moscow');
 assert.equal(midnight.duration,15);assert.equal(midnight.end,1440);
});

class FakeElement{
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.dataset={};this.attrs={};this.scrollTop=0;this.textContent='';this.className='';this.classList={toggle:()=>{}};}
 append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node)}}
 replaceChildren(...nodes){this.children=[];this.append(...nodes)}
 setAttribute(k,v){this.attrs[k]=v}
 getBoundingClientRect(){return {top:0,bottom:2000}}
 setPointerCapture(id){this.capture=id}
 hasPointerCapture(id){return this.capture===id}
 releasePointerCapture(){this.capture=null}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this)}
}
function renderedCalendar(weekStart='2099-01-05',secondaryZone='Europe/Berlin',options={},rows=[]){
 const document={createElement:tag=>new FakeElement(tag),addEventListener:()=>{},removeEventListener:()=>{}};
 const subject=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../landing/dist/weekly-calendar.js'),'utf8')+';WeeklyCalendar',{Intl,Date,document,setInterval:()=>1,clearInterval:()=>{}});
 const root=new FakeElement('div'),calls=[];
 const dispose=subject.render(root,rows,{...options,weekStart,timezone:'Europe/Moscow',secondaryZone,onCreate:(...args)=>calls.push(args),onOpen:options.onOpen||(()=>{})});
 const day=root.children[0].children.find(n=>n.className.split(' ').includes('time-day'));
 return {subject,root,day,calls,dispose};
}
test('opens exactly at 08:00 and preserves manual scroll on rerender',()=>{
 const {subject,root,dispose}=renderedCalendar();assert.equal(root.scrollTop,8*64);dispose();root.scrollTop=700;
 const stop=subject.render(root,[],{weekStart:'2099-01-12',timezone:'Europe/Moscow',onCreate:()=>{},onOpen:()=>{}});assert.equal(root.scrollTop,700);stop();
});
test('drag stages one interval and suppresses duplicate click; touch keeps native tap',()=>{
 const {day,calls,dispose}=renderedCalendar(),slots=day.children.filter(n=>n.className==='time-slot');
 assert.equal(slots.length,96);assert.equal(slots[61].attrs['aria-label'],'Создать урок 2099-01-05 в 15:15');
 const down={pointerType:'mouse',button:0,pointerId:1,clientY:960,preventDefault:()=>{}};
 slots[60].onpointerdown(down);day.onpointermove({pointerId:1,clientY:992});
 assert.equal(calls.length,0);
 day.onpointerup({pointerId:1});assert.equal(calls.length,1);assert.equal(calls[0][1],45);
 slots[60].onclick({detail:1});assert.equal(calls.length,1);
 slots[64].onclick({detail:0});assert.equal(calls.length,2);assert.equal(calls[1][1],undefined);dispose();
});

test('DST corrections show exact Sunday time only after the autumn transition',()=>{
 const {root,dispose}=renderedCalendar('2026-10-19');
 const week=root.children[0],days=week.children.filter(n=>n.className.split(' ').includes('time-day'));
 assert.equal(week.children[0].textContent,'Москва');
 assert.equal(days[0].children.filter(n=>n.className==='timezone-correction').length,0);
 const marks=days[6].children.filter(n=>n.className==='timezone-correction');
 assert.equal(marks.length,20);assert.equal(marks[0].style.top,'256px');assert.equal(marks[0].textContent,'Берлин 02:00');
 assert.equal(marks.find(n=>n.style.top==='512px').textContent,'Берлин 06:00');
 const axis=week.children.find(n=>n.className==='time-axis secondary-axis');
 assert.equal(axis.children[8].textContent,'07:00');assert.equal(axis.children[8].children.length,0);
 assert.equal(week.children.filter(n=>n.className.includes('time-day-heading')).at(-1).children.at(-1).textContent,'Перевод часов · Берлин');dispose();
});
test('spring corrections skip the missing Berlin hour and ordinary weeks stay clean',()=>{
 const {root,dispose}=renderedCalendar('2027-03-22');
 const sunday=root.children[0].children.filter(n=>n.className.split(' ').includes('time-day'))[6];
 const marks=sunday.children.filter(n=>n.className==='timezone-correction');
 assert.equal(marks[0].style.top,'256px');assert.equal(marks[0].textContent,'Берлин 03:00');dispose();
 for(const zone of ['Europe/Berlin','']){const normal=renderedCalendar('2026-10-26',zone);const days=normal.root.children[0].children.filter(n=>n.className.split(' ').includes('time-day'));assert.ok(days.every(day=>day.children.every(n=>n.className!=='timezone-correction')));normal.dispose()}
});

test('cropped range aligns axes, clips ongoing lessons and supports 45-minute drag',()=>{
 const rows=[lesson(1,'2099-01-05T10:15:00Z','2099-01-05T11:15:00Z'),lesson(2,'2099-01-05T09:00:00Z','2099-01-05T10:00:00Z')];
 const {root,day,calls,dispose}=renderedCalendar('2099-01-05','Europe/Berlin',{startMinute:810},rows);
 assert.equal(root.scrollTop,0);assert.equal(day.style.height,'672px');
 const axis=root.children[0].children.find(n=>n.className==='time-axis');
 assert.equal(axis.children[0].textContent,'13:30');assert.equal(axis.children[0].style.top,'0px');assert.equal(axis.children[1].style.top,'32px');
 const slots=day.children.filter(n=>n.className==='time-slot');assert.equal(slots.length,42);assert.equal(slots[0].style.top,'0px');
 const events=day.children.filter(n=>n.className.startsWith('calendar-event'));assert.equal(events.length,1);assert.equal(events[0].style.top,'0px');assert.equal(events[0].style.height,'46px');
 slots[0].onpointerdown({pointerType:'mouse',button:0,pointerId:1,clientY:0,preventDefault:()=>{}});
 day.onpointermove({pointerId:1,clientY:32});day.onpointerup({pointerId:1});
 assert.equal(calls[0][0],'2099-01-05T13:30');assert.equal(calls[0][1],45);dispose();
});
test('switching to full day restores all slots and resets range scroll',()=>{
 const {subject,root,dispose}=renderedCalendar('2099-01-05','',{startMinute:810});dispose();root.scrollTop=300;
 const stop=subject.render(root,[],{weekStart:'2099-01-05',timezone:'Europe/Moscow',secondaryZone:'',startMinute:0,onCreate:()=>{},onOpen:()=>{}});
 assert.equal(root.scrollTop,0);const day=root.children[0].children.find(n=>n.className.split(' ').includes('time-day'));
 assert.equal(day.children.filter(n=>n.className==='time-slot').length,96);stop();
});

test('student read-only calendar opens lessons without creating editable time slots',()=>{
 const opened=[],rows=[lesson(1,'2099-01-05T10:00:00Z','2099-01-05T10:45:00Z')];
 const {day,calls,dispose}=renderedCalendar('2099-01-05','',{readOnly:true,startMinute:0,onOpen:row=>opened.push(row)},rows);
 assert.equal(day.children.filter(n=>n.className==='time-slot').length,0);
 const event=day.children.find(n=>n.className.startsWith('calendar-event'));assert.ok(event);assert.equal(event.style.height,'46px');
 event.onclick();assert.equal(opened[0].id,1);assert.equal(event.tag,'button');assert.equal(calls.length,0);dispose();
});

test('student ranges default to 08:00 or use the pupil timezone and clamp at midnight',()=>{
 assert.equal(calendar.studentRange('fixed','Asia/Vladivostok','2027-01-04T10:37:00Z'),480);
 assert.equal(calendar.studentRange('current','Asia/Vladivostok','2027-01-04T10:37:00Z'),1170);
 assert.equal(calendar.studentRange('current','Europe/Moscow','2027-01-04T10:37:00Z'),750);
 assert.equal(calendar.studentRange('current','Europe/Berlin','2027-01-04T23:30:00Z'),0);
 assert.equal(calendar.studentRange('current','UTC','2027-01-04T23:59:00Z'),1365);
});

test('automatic range surrounds weekly lessons and includes now only for the current week',()=>{
 const rows=[lesson(1,'2099-01-05T15:00:00Z','2099-01-05T15:45:00Z'),lesson(2,'2099-01-06T19:00:00Z','2099-01-06T19:45:00Z')];
 const future=calendar.studentWindow('auto',rows,'2099-01-05','UTC','2098-12-01T09:00:00Z');
 assert.equal(future.startMinute,840);assert.equal(future.endMinute,1245);
 const current=calendar.studentWindow('auto',rows,'2099-01-05','UTC','2099-01-05T09:10:00Z');
 assert.equal(current.startMinute,480);assert.equal(current.endMinute,1245);
 const late=calendar.studentWindow('auto',rows,'2099-01-05','UTC','2099-01-05T23:50:00Z');assert.equal(late.endMinute,1440);
 const empty=calendar.studentWindow('auto',[],'2099-01-05','Europe/Moscow','2099-01-05T09:10:00Z');assert.equal(empty.startMinute,660);assert.equal(empty.endMinute,1440);
 const midnight=calendar.studentWindow('auto',[lesson(3,'2099-01-05T23:30:00Z','2099-01-06T00:15:00Z')],'2099-01-05','UTC','2098-12-01T09:00:00Z');assert.equal(midnight.startMinute,0);assert.equal(midnight.endMinute,1440);
});
test('bounded calendar clips the end of lessons and excludes later events',()=>{
 const rows=[lesson(1,'2099-01-05T10:00:00Z','2099-01-05T12:00:00Z'),lesson(2,'2099-01-05T13:00:00Z','2099-01-05T14:00:00Z')];
 const {day,dispose}=renderedCalendar('2099-01-05','',{startMinute:780,endMinute:840,readOnly:true},rows);
 assert.equal(day.style.height,'64px');const events=day.children.filter(n=>n.className.startsWith('calendar-event'));assert.equal(events.length,1);assert.equal(events[0].style.height,'62px');dispose();
});

test('admin compact window includes all lessons with one hour before and two hours after',()=>{
 const completed={...lesson(1,'2099-01-05T09:00:00Z','2099-01-05T09:45:00Z'),status:'completed'};
 const scheduled=lesson(2,'2099-01-06T17:00:00Z','2099-01-06T17:45:00Z');
 const range=calendar.adminWindow([completed,scheduled],'2099-01-05','UTC','2099-01-05T15:10:00Z');
 assert.equal(range.startMinute,480);assert.equal(range.endMinute,1185);
 const later=calendar.adminWindow([scheduled],'2099-01-05','UTC','2099-01-05T15:10:00Z');assert.equal(later.startMinute,840);
 const empty=calendar.adminWindow([],'2099-01-05','Europe/Moscow','2099-01-05T10:40:00Z');assert.equal(empty.startMinute,750);assert.equal(empty.endMinute,945);
 const midnight=calendar.adminWindow([lesson(3,'2099-01-04T23:30:00Z','2099-01-05T00:15:00Z')],'2099-01-05','UTC','2099-01-05T15:00:00Z');assert.equal(midnight.startMinute,0);
});

test('admin compact window matches 12:00–20:00 example and keeps current time visible after lessons',()=>{
 const rows=[lesson(1,'2099-01-05T15:00:00Z','2099-01-05T18:00:00Z')];
 const range=calendar.adminWindow(rows,'2099-01-05','UTC','2099-01-05T13:00:00Z');assert.equal(range.startMinute,720);assert.equal(range.endMinute,1200);
 const late=calendar.adminWindow(rows,'2099-01-05','UTC','2099-01-05T23:00:00Z');assert.equal(late.endMinute,1440);
});
