let materialsSummaryGeneration=0;
function summaryElement(tag,text,className){const element=document.createElement(tag);if(text!==undefined)element.textContent=text;if(className)element.className=className;return element}
function renderStudentMaterial(target,category,row){
 target.replaceChildren();
 if(!row){target.append(summaryElement('p',category==='homework'?'Преподаватель пока не добавил домашнее задание.':'Преподаватель пока не добавил конспект.','muted'));return}
 const date=new Date(row.starts_at).toLocaleDateString('ru-RU',{timeZone:row.timezone,dateStyle:'long'});
 target.append(summaryElement('p','Урок '+date,'student-material-date'),summaryElement('h3',row.topic||'Математика','student-material-topic'));
 if(category==='homework'){
  let deadline;
  if(row.due_mode==='manual')deadline='Выполнить к '+String(row.due_date).slice(0,10).split('-').reverse().join('.');
  else deadline=row.next_lesson_at?'К следующему занятию: '+new Date(row.next_lesson_at).toLocaleString('ru-RU',{timeZone:row.timezone,dateStyle:'short',timeStyle:'short'}):'К следующему занятию — дата пока не назначена';
  target.append(summaryElement('p',deadline,'student-material-deadline'));
 }
 const text=row[category];
 if(text)target.append(summaryElement('p',text,'material-summary-text'));
 const files=row.files.filter(file=>file.category===category);
 if(files.length){
  target.append(summaryElement('p',category==='homework'?'Файлы задания':'Конспект и вложения','student-material-file-heading'));
  const list=summaryElement('ul',undefined,'student-material-files');
  for(const file of files){const item=summaryElement('li'),link=summaryElement('a',file.filename);link.href='/api/materials/files/'+encodeURIComponent(file.id);link.setAttribute('aria-label','Скачать '+file.filename);item.append(link,summaryElement('span',' · '+Math.max(1,Math.ceil(file.size/1024))+' КБ','muted small'));list.append(item)}
  target.append(list);
 }
 if(!text&&files.length)target.append(summaryElement('p',category==='homework'?'Задание находится в прикреплённых файлах.':'Скачайте конспект по ссылке выше.','muted small'));
 if(category==='homework')target.append(summaryElement('p','Проверим вместе в начале следующего урока.','muted small'));
}
async function loadMaterialsSummary(){
 const targets={homework:document.querySelector('[data-homework-summary]'),notes:document.querySelector('[data-notes-summary]')};
 if(!targets.homework||!targets.notes)return;
 const generation=++materialsSummaryGeneration;
 document.querySelectorAll('[data-refresh-materials]').forEach(button=>button.disabled=true);
 for(const [category,target] of Object.entries(targets)){target.setAttribute('aria-busy','true');target.textContent=category==='homework'?'Загружаем задание…':'Загружаем конспект…'}
 await Promise.allSettled(Object.entries(targets).map(async([category,target])=>{
  try{const response=await fetch('/api/materials?limit=1&content='+category,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(generation!==materialsSummaryGeneration)return;renderStudentMaterial(target,category,data.items[0]);}
  catch{if(generation!==materialsSummaryGeneration)return;target.textContent=category==='homework'?'Не удалось загрузить задание. Нажмите «Обновить материалы» или откройте историю.':'Не удалось загрузить конспект. Нажмите «Обновить материалы» или откройте историю.';}
  finally{if(generation===materialsSummaryGeneration)target.setAttribute('aria-busy','false')}
 }));
 if(generation===materialsSummaryGeneration)document.querySelectorAll('[data-refresh-materials]').forEach(button=>button.disabled=false);
}
document.querySelectorAll('[data-refresh-materials]').forEach(button=>button.addEventListener('click',()=>void loadMaterialsSummary()));
