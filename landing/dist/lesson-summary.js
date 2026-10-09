async function loadLessonSummary(){
 const next=document.querySelector('[data-next-lesson]'),week=document.querySelector('[data-week-lessons]');if(!next&&!week)return;
 try{const response=await fetch('/api/lessons/summary',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();
 const describe=row=>new Date(row.starts_at).toLocaleString('ru-RU',{timeZone:data.timezone,dateStyle:'short',timeStyle:'short'})+' · '+row.student_name+' · '+row.duration_minutes+' мин'+(row.topic?' · '+row.topic:'')+' · '+({scheduled:'Запланировано',completed:'Проведено',cancelled:'Отменено'}[row.status]);
 if(next){next.textContent=data.upcoming.length?describe(data.upcoming[0]):'Ближайших занятий пока нет.'}
 if(week){week.replaceChildren();for(const row of data.week){const p=document.createElement('p');p.textContent=describe(row);week.append(p)}if(!data.week.length)week.textContent='На этой неделе занятий нет.'}
 for(const [selector,rows,empty] of [['[data-next-lessons]',next?data.upcoming.slice(1):data.upcoming,'Других ближайших занятий пока нет.'],['[data-today-lessons]',data.today,'Сегодня занятий нет.']]){const target=document.querySelector(selector);if(target){target.replaceChildren();for(const row of rows){const p=document.createElement('p');p.textContent=describe(row);target.append(p)}if(!rows.length)target.textContent=empty}}
 document.querySelectorAll('[data-lesson-zone]').forEach(e=>e.textContent='Часовой пояс: '+data.timezone);
 }catch(e){if(next)next.textContent='Не удалось загрузить расписание. Попробуйте обновить страницу.';if(week)week.textContent='Расписание временно недоступно.'}
}
