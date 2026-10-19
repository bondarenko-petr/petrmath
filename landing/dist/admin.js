let calendarFocusPending=false;
let issuedCredentials=null;
const status = document.querySelector('#admin-status');
const items = document.querySelector('#items');
let section = 'overview', offset = 0, busy = false;
const limit = 20;
let studentSearch='',studentView='all',studentSort='name',studentArchive=new URLSearchParams(location.search).get('archive')==='true';
const studentFilters=document.querySelector('#student-filters');
studentFilters.onsubmit=event=>{event.preventDefault();if(busy||trialSaving)return;studentSearch=studentFilters.elements.search.value.trim();studentView=studentFilters.elements.view.value;studentSort=studentFilters.elements.sort.value;offset=0;load()};
document.querySelector('#student-reset').onclick=()=>{if(busy||trialSaving)return;studentFilters.reset();studentSearch='';studentView='all';studentSort='name';offset=0;load()};
let trialView='active',trialSearch='',trialStatus='',trialSaving=false;
const trialStatuses={new:'Новая',contacting:'Связываемся',trial_scheduled:'Пробный назначен',enrolled:'Стал учеником',closed:'Закрыта'};
const trialReasons={declined:'Передумали',no_response:'Нет ответа',duplicate:'Дубль',spam:'Спам',other:'Другое'};
function trialElement(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function trialOptions(select,options,empty){if(empty!==undefined){const option=trialElement('option',empty);option.value='';select.append(option)}for(const [value,label] of Object.entries(options)){const option=trialElement('option',label);option.value=value;select.append(option)}}
function renderTrialRequest(row){
 const card=trialElement('details',undefined,'record trial-record'),summary=trialElement('summary');
 summary.append(trialElement('strong',row.name),trialElement('span',String(row.created_at).replace('T',' '),'trial-date'),trialElement('span',row.courses,'trial-courses'),trialElement('span',trialStatuses[row.status],'badge'));
 const fields=trialElement('dl');for(const [label,value] of [['Номер',row.id],['Email',row.email],['Телефон',row.phone],['Сообщение',row.message],['Причина закрытия',trialReasons[row.close_reason]],['Согласие',row.consent?'Получено':'Нет']]){if(label==='Причина закрытия'&&!row.close_reason)continue;addField(fields,label,value)}
 const form=trialElement('form',undefined,'trial-editor'),fieldset=trialElement('fieldset'),statusLabel=trialElement('label','Статус'),select=trialElement('select');select.name='status';trialOptions(select,trialStatuses);select.value=row.status;statusLabel.append(select);
 const reasonLabel=trialElement('label','Причина закрытия'),reason=trialElement('select');reason.name='reason';trialOptions(reason,trialReasons,'Выберите причину');reason.value=row.close_reason;reasonLabel.append(reason);
 const noteLabel=trialElement('label','Заметка администратора'),note=trialElement('textarea');note.name='admin_note';note.rows=3;note.maxLength=2000;note.value=row.admin_note;noteLabel.append(note);
 const help=trialElement('p','','muted small');const showReason=()=>{reasonLabel.hidden=select.value!=='closed';reason.required=select.value==='closed';help.textContent=select.value==='enrolled'?'Заявка уйдёт в архив. Аккаунт ученика создайте в разделе «Ученики».':select.value==='trial_scheduled'?'Дату и время занятия назначьте отдельно в расписании.':'';};select.onchange=showReason;showReason();
 const actions=trialElement('div',undefined,'student-actions'),save=trialElement('button','Сохранить');save.type='submit';actions.append(save);
 if(!['enrolled','closed'].includes(row.status)){const archive=trialElement('button','В архив');archive.type='button';archive.onclick=()=>{select.value='closed';showReason();reason.focus()};actions.append(archive)}else{const restore=trialElement('button','Вернуть в работу');restore.type='button';restore.onclick=()=>{select.value='new';showReason();form.requestSubmit()};actions.append(restore)}
 const feedback=trialElement('p');feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');fieldset.append(statusLabel,reasonLabel,noteLabel,help,actions);form.append(fieldset,feedback);
 form.onsubmit=async event=>{event.preventDefault();if(busy||trialSaving||fieldset.disabled)return;trialSaving=true;fieldset.disabled=true;feedback.textContent='Сохраняем…';try{await mutate('trial-requests/'+row.id,'PATCH',{status:select.value,admin_note:note.value,close_reason:select.value==='closed'?reason.value:'',version:row.version});trialSaving=false;offset=0;const loaded=await load();if(loaded)status.textContent='Заявка сохранена.';}catch(error){feedback.textContent=error.message;}finally{trialSaving=false;fieldset.disabled=false}};
 card.append(summary,fields,form);return card;
}
function chooseTrialView(value){if(busy||trialSaving)return;trialView=value;trialStatus='';offset=0;const select=document.querySelector('#trial-filters').elements.status;select.replaceChildren();trialOptions(select,value==='active'?{new:'Новая',contacting:'Связываемся',trial_scheduled:'Пробный назначен'}:{enrolled:'Стал учеником',closed:'Закрыта'},'Все статусы');load()}
document.querySelector('#trial-active').onclick=()=>chooseTrialView('active');document.querySelector('#trial-archive').onclick=()=>chooseTrialView('archive');
document.querySelector('#trial-filters').onsubmit=event=>{event.preventDefault();if(busy||trialSaving)return;trialSearch=event.currentTarget.elements.search.value.trim();trialStatus=event.currentTarget.elements.status.value;offset=0;load()};
document.querySelector('#trial-reset').onclick=()=>{if(busy||trialSaving)return;trialSearch='';trialStatus='';document.querySelector('#trial-filters').reset();offset=0;load()};

function renderStudentTable(rows){
 const wrapper=document.createElement('div');wrapper.className='student-table-scroll';wrapper.tabIndex=0;wrapper.setAttribute('aria-label','Таблица учеников');
 const table=document.createElement('table');table.className='student-table';const caption=trialElement('caption','Ученики и текущий денежный баланс');table.append(caption);
 const head=document.createElement('thead'),heading=document.createElement('tr');for(const title of ['Ученик','Логин','Класс','Цена урока','Баланс','Статус','Действия']){const th=trialElement('th',title);th.scope='col';heading.append(th)}head.append(heading);table.append(head);
 const body=document.createElement('tbody'),rub=value=>(Number(value)/100).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+' ₽';
 for(const row of rows){const tr=document.createElement('tr');const values=[row.name,row.username,row.school_grade??'—',rub(row.default_price_kopecks),rub(row.balance_kopecks),row.is_active?'Активен':'В архиве'];values.forEach((value,i)=>{const td=trialElement('td',value);if(i===3||i===4)td.className='student-money';if(i===4&&row.debt_kopecks>0){td.classList.add('student-debt');td.append(trialElement('span','Задолженность','student-debt-label'))}tr.append(td)});
 const actions=document.createElement('td');actions.className='student-table-actions';const info=trialElement('button','Информация об ученике');info.type='button';info.setAttribute('aria-label','Информация об ученике: '+row.name);info.onclick=()=>showStudentInformation(row.id);actions.append(info);const topup=trialElement('button','Пополнить баланс');topup.type='button';topup.onclick=()=>window.openAdminPayment(row.id);actions.append(topup);const link=trialElement('a','История операций');link.href='finance.html?student_id='+encodeURIComponent(row.id);link.setAttribute('aria-label','Оплаты: '+row.name);actions.append(link);const materials=trialElement('a','Материалы');materials.href='materials.html?student_id='+row.id;materials.setAttribute('aria-label','Материалы: '+row.name);actions.append(materials);
 const edit=trialElement('button','Редактировать');edit.type='button';edit.onclick=()=>editStudent(row);actions.append(edit);
 const more=document.createElement('details'),summary=trialElement('summary','Ещё');more.append(summary);for(const [label,handler] of [['Сбросить пароль',()=>resetPassword(row)],[row.is_active?'Архивировать':'Восстановить',()=>toggleActive(row)]]){const b=trialElement('button',label);b.type='button';b.onclick=handler;more.append(b)}if(!row.is_active){const remove=trialElement('button','Удалить навсегда','student-delete-button');remove.type='button';remove.onclick=()=>deleteStudentDialog(row);more.append(remove)}actions.append(more);tr.append(actions);body.append(tr)}
 table.append(body);wrapper.append(table);if(!rows.length)wrapper.append(trialElement('p','Ученики не найдены. Измените поиск или фильтр.','muted'));return wrapper;
}

async function get(path) {
  const response = await fetch('/api/' + path);
  const result = await response.json();
  if(!response.ok){const error=new Error(response.status === 401 ? 'Войдите в аккаунт через страницу «Мой профиль».' : response.status === 403 ? 'У вашего аккаунта нет прав администратора.' : 'Не удалось загрузить данные. Проверьте миграцию базы и попробуйте обновить список.');error.status=response.status;throw error;}
  return result;
}
function addField(list, label, value) {
  const term = document.createElement('dt'), description = document.createElement('dd');
  term.textContent = label; description.textContent = String(value ?? '—') || '—';
  list.append(term, description);
}
async function load() {
  if(busy||trialSaving) return;
  if(section==='overview'){await loadOverview();return;}
  busy = true; clearCredentials(); items.replaceChildren(); status.textContent = 'Загружаем…';
  document.querySelectorAll('#management button').forEach(button => button.disabled = true);
  try {
    const params=new URLSearchParams({limit,offset});if(section==='trial-requests'){params.set('view',trialView);params.set('search',trialSearch);if(trialStatus)params.set('status',trialStatus)}
    if(section==='students'){params.set('archive',String(studentArchive));params.set('include_finance','true');params.set('search',studentSearch);params.set('view',studentView);params.set('sort',studentSort)}
    const result = await get(`admin/${section}?${params}`);
    document.querySelector('#trial-controls').hidden=section!=='trial-requests';document.querySelector('#student-controls').hidden=section!=='students';items.classList.toggle('trial-list',section==='trial-requests');items.classList.toggle('student-list',section==='students');
    if(section==='trial-requests'){document.querySelector('#trial-active').textContent='В работе ('+result.active_total+')';document.querySelector('#trial-archive').textContent='Архив ('+result.archive_total+')';document.querySelector('#trial-new-count').textContent='Новых: '+result.counts.new;document.querySelector('#trial-active').setAttribute('aria-pressed',String(trialView==='active'));document.querySelector('#trial-archive').setAttribute('aria-pressed',String(trialView==='archive'));}
    document.querySelector('#dashboard').hidden = false;window.mountAdminNavigation(section==='students'?'students':'requests');

    document.querySelector('#create-student').hidden = section !== 'students';
    document.querySelector('#list-title').textContent = section === 'students' ? 'Зарегистрированные ученики' : 'Заявки на пробный урок';
    document.querySelector('#count').textContent = `Всего: ${result.total}. Показано: ${result.items.length}.`;
    if(section==='students'){document.querySelector('#students-active').textContent='Активные ('+result.counts.active+')';document.querySelector('#students-archive').textContent='Архив ('+result.counts.archive+')';document.querySelector('#students-active').setAttribute('aria-pressed',String(!studentArchive));document.querySelector('#students-archive').setAttribute('aria-pressed',String(studentArchive));document.querySelector('#list-title').textContent=studentArchive?'Архив учеников':'Активные ученики';items.append(renderStudentTable(result.items));}else for(const row of result.items)items.append(renderTrialRequest(row));
    status.textContent = result.items.length ? '' : 'Пока записей нет.';
    document.querySelectorAll('#management button').forEach(button => button.disabled = false);
    document.querySelector('#prev').disabled = offset === 0;
    document.querySelector('#next').disabled = offset + limit >= result.total;
    return true;
  } catch(error) { status.textContent = error.message; document.querySelector('#dashboard').hidden = error.status===401||error.status===403;for(const id of ['requests-tab','students-tab','admin-refresh','trial-active','trial-archive','trial-reset','student-reset'])document.getElementById(id).disabled=false; }
  finally { busy = false; }
}
function choose(value) {
  if(busy||trialSaving)return;
  section=value; offset=0;window.mountAdminNavigation(value==='overview'?'calendar':value==='students'?'students':'requests');
  document.querySelector('#overview').hidden=value!=='overview';document.querySelector('#management').hidden=value==='overview';document.querySelector('#student-editor').hidden=true;clearCredentials();
  document.querySelector('#requests-tab').setAttribute('aria-pressed',String(section === 'trial-requests'));
  document.querySelector('#students-tab').setAttribute('aria-pressed',String(section === 'students'));
  const location=new URL(window.location.href);location.searchParams.set('section',value);history.replaceState(null,'',location);
  load();
}
document.querySelector('#requests-tab').onclick=()=>choose('trial-requests');
document.querySelector('#students-tab').onclick=()=>choose('students');
document.querySelector('#prev').onclick=()=>{offset=Math.max(0,offset-limit);load();};
document.querySelector('#next').onclick=()=>{offset+=limit;load();};
document.querySelector('#admin-refresh').onclick=()=>load();
const requestedSection=new URLSearchParams(window.location.search).get('section');if(['students','trial-requests'].includes(requestedSection)){section=requestedSection;document.querySelector('#overview').hidden=true;document.querySelector('#management').hidden=false;document.querySelector('#students-tab').setAttribute('aria-pressed',String(section==='students'));document.querySelector('#requests-tab').setAttribute('aria-pressed',String(section==='trial-requests'))}
load();

window.addEventListener('admin-navigate',event=>choose(event.detail));


let editing=null;
const studentForm=document.querySelector('#student-form');
const studentFormStatus=document.querySelector('#student-form-status');
async function mutate(path,method,data){
 const response=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-Requested-With':'KrugPi'},body:JSON.stringify(data)});
 const result=await response.json();if(!response.ok){const labels={name:'Имя',username:'Логин',email:'Email',school_grade:'Класс',default_price_kopecks:'Цена занятия',default_duration_minutes:'Длительность',timezone:'Часовой пояс',parent_name:'Имя родителя',parent_phone:'Телефон родителя'};const detail=typeof result.detail==='string'?result.detail:Array.isArray(result.detail)?result.detail.map(issue=>(labels[issue.loc?.at(-1)]||'Поле')+': '+issue.msg).join('; '):'Проверьте заполнение полей.';throw new Error(detail);}return result;
}
function clearCredentials(){issuedCredentials=null;document.querySelector('#email-status').textContent='';document.querySelector('#send-credentials').hidden=true;document.querySelector('#credentials').hidden=true;document.querySelector('#issued-password').textContent='';document.querySelector('#issued-username').textContent='';}
function showCredentials(data){issuedCredentials=data;document.querySelector('#email-help').textContent=data.email?'Письмо будет отправлено на '+data.email+'. Оно объяснит, как войти и сменить временный пароль.':'Email не указан. Передайте пароль вручную; для отправки укажите email и выполните сброс пароля.';document.querySelector('#send-credentials').hidden=!data.email;document.querySelector('#send-credentials').disabled=false;document.querySelector('#email-status').textContent='';document.querySelector('#issued-username').textContent=data.username;document.querySelector('#issued-password').textContent=data.temporary_password;document.querySelector('#credentials').hidden=false;document.querySelector('#credentials').scrollIntoView({block:'center'});}
function editStudent(row=null){const picker=studentForm.elements.timezone;const saved=row?.timezone||'';picker.replaceChildren(new Option('По умолчанию для учеников',''));const zones=new Set(['UTC','Europe/Moscow','Europe/Berlin','Asia/Vladivostok',...(Intl.supportedValuesOf?Intl.supportedValuesOf('timeZone'):[]),...(saved?[saved]:[])]);const names={'Europe/Moscow':'Москва','Europe/Berlin':'Берлин','Asia/Vladivostok':'Владивосток','Asia/Yekaterinburg':'Екатеринбург','Asia/Novosibirsk':'Новосибирск','Asia/Irkutsk':'Иркутск','Asia/Krasnoyarsk':'Красноярск','Asia/Kamchatka':'Камчатка','Europe/Samara':'Самара','Europe/Kaliningrad':'Калининград'};for(const zone of [...zones].sort())picker.add(new Option(names[zone]?names[zone]+' ('+zone+')':zone,zone));picker.value=saved;clearCredentials();editing=row?.id??null;studentForm.reset();studentFormStatus.textContent='';const login=studentForm.elements.username;const legacy=!!row&&!/^[a-zA-Z0-9._-]{3,40}$/.test(row.username);login.readOnly=legacy;login.maxLength=legacy?254:40;login.minLength=legacy?1:3;if(legacy){login.removeAttribute('pattern');studentFormStatus.textContent='Сохранён прежний логин для входа. Остальные данные можно редактировать.';}else login.setAttribute('pattern','[a-zA-Z0-9._\\-]+');document.querySelector('#student-editor').hidden=false;document.querySelector('#student-editor-title').textContent=row?'Редактировать ученика':'Добавить ученика';if(row){for(const field of ['name','username','email','phone','parent_name','parent_phone','school_grade','default_duration_minutes','timezone'])studentForm.elements[field].value=row[field]??'';studentForm.elements.price.value=(row.default_price_kopecks/100).toFixed(2);}studentForm.scrollIntoView({block:'start'});studentForm.elements.name.focus();}
document.querySelector('#create-student').onclick=()=>editStudent();
document.querySelector('#cancel-editor').onclick=()=>{document.querySelector('#student-editor').hidden=true;studentForm.reset();};
document.querySelector('#close-credentials').onclick=clearCredentials;
studentForm.addEventListener('submit',async event=>{
 event.preventDefault();const price=studentForm.elements.price.value.replace(',','.');if(!/^\d+(\.\d{1,2})?$/.test(price)){studentFormStatus.textContent='Введите цену в рублях с точностью до копеек.';return;}
 const [rubles,kopecks='']=price.split('.');const data={timezone:studentForm.elements.timezone.value||null,name:studentForm.elements.name.value,username:studentForm.elements.username.value,email:studentForm.elements.email.value||null,phone:studentForm.elements.phone.value,parent_name:studentForm.elements.parent_name.value,parent_phone:studentForm.elements.parent_phone.value,school_grade:studentForm.elements.school_grade.value?Number(studentForm.elements.school_grade.value):null,default_price_kopecks:Number(rubles)*100+Number(kopecks.padEnd(2,'0')),default_duration_minutes:Number(studentForm.elements.default_duration_minutes.value)};
 const button=studentForm.querySelector('button[type=submit]');button.disabled=true;studentFormStatus.textContent='Сохраняем…';
 try{const result=await mutate('students'+(editing?'/'+editing:''),editing?'PUT':'POST',data);document.querySelector('#student-editor').hidden=true;studentForm.reset();offset=0;await load();status.textContent='Данные ученика сохранены. Новая цена применяется к новым занятиям.';if(result.temporary_password)showCredentials(result);}catch(error){studentFormStatus.textContent=error.message;}finally{button.disabled=false;}
});
async function resetPassword(row){if(!confirm('Сбросить пароль ученика '+row.name+'? Старые сессии будут завершены.'))return;clearCredentials();try{const data=await mutate('students/'+row.id+'/reset-password','POST',{});showCredentials(data);}catch(error){status.textContent=error.message;}}
async function toggleActive(row){if(busy||trialSaving)return;clearCredentials();try{let message='Восстановить ученика '+row.name+' и разрешить ему вход?';if(row.is_active){const info=await get('admin/students/'+row.id+'/deletion-preview');message='Перенести '+row.name+' в архив? Вход будет отключён; история и баланс сохранятся.';if(info.future_lessons)message+=' Есть будущие занятия: '+info.future_lessons+'. Они НЕ будут отменены. При необходимости отмените их отдельно в календаре.'}if(!confirm(message))return;await mutate('students/'+row.id+'/active','PATCH',{is_active:!row.is_active});offset=0;await load();}catch(error){status.textContent=error.message;}}


document.querySelector('#send-credentials').onclick=async()=>{
 const data=issuedCredentials;if(!data)return;
 if(!confirm('Отправить логин и временный пароль на '+data.email+'?'))return;
 const button=document.querySelector('#send-credentials');button.disabled=true;
 document.querySelector('#email-status').textContent='Отправляем письмо…';
 try{await mutate('students/'+data.id+'/send-credentials','POST',{temporary_password:data.temporary_password});if(issuedCredentials===data)document.querySelector('#email-status').textContent='Почтовый сервер принял письмо. Попросите ученика проверить входящие и папку «Спам».';}
 catch(error){if(issuedCredentials===data){document.querySelector('#email-status').textContent=error.message;button.disabled=false;}}
};

async function loadOverview(){
 busy=true;status.textContent='Проверяем доступ…';
 try{const user=await get('auth/me');if(user.role!=='admin'||user.must_change_password){const error=new Error('Для доступа войдите как администратор и смените временный пароль при необходимости.');error.status=403;throw error}document.querySelector('#dashboard').hidden=false;window.mountAdminNavigation('calendar');status.textContent='';calendarFocusPending=true;window.dispatchEvent(new Event('schedule-show-week'));focusCalendarOnOpen();
 }catch(error){status.textContent=error.message;document.querySelector('#dashboard').hidden=true}finally{busy=false}
}

window.addEventListener('admin-payment-saved',()=>{if(section==='students')void load()});

function chooseStudentArchive(archive){if(busy||trialSaving)return;studentArchive=archive;offset=0;const url=new URL(location.href);url.searchParams.set('archive',String(archive));history.replaceState(null,'',url);void load()}
document.querySelector('#students-active').onclick=()=>chooseStudentArchive(false);document.querySelector('#students-archive').onclick=()=>chooseStudentArchive(true);
async function deleteStudentDialog(row){
 if(busy||trialSaving||document.querySelector('#student-delete-dialog'))return;
 const dialog=trialElement('dialog',undefined,'student-delete-dialog');dialog.id='student-delete-dialog';const title=trialElement('h2','Удалить ученика навсегда');title.id='student-delete-title';dialog.setAttribute('aria-labelledby',title.id);const body=trialElement('div','Загружаем данные…'),feedback=trialElement('p');feedback.setAttribute('role','status');const close=trialElement('button','Отмена');close.type='button';let saving=false;close.onclick=()=>dialog.close();dialog.append(title,body,feedback,close);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove());dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault()});dialog.showModal();
 try{const info=await get('admin/students/'+row.id+'/deletion-preview');if(!dialog.open)return;if(info.is_active)throw Error('Сначала перенесите ученика в архив.');body.replaceChildren(trialElement('p',info.name+' · '+info.username));const list=trialElement('dl');for(const [label,value] of [['Занятий',info.lessons],['Будущих занятий',info.future_lessons],['Оплат',info.payments],['Записей с материалами',info.materials],['Файлов (включая убранные)',info.files],['Баланс',(info.balance_kopecks/100).toLocaleString('ru-RU',{minimumFractionDigits:2})+' ₽']])addField(list,label,value);body.append(list,trialElement('p','Будут удалены аккаунт, контакты, занятия, оплаты, задания, конспекты и файлы. Финансовая история изменится. Восстановления через кабинет нет.','student-delete-warning'));
 const form=trialElement('form'),label=trialElement('label','Для подтверждения введите логин: '+info.username),input=trialElement('input');input.type='text';input.required=true;input.autocomplete='off';input.maxLength=254;label.append(input);const submit=trialElement('button','Удалить навсегда','student-delete-button');submit.type='submit';submit.disabled=true;input.oninput=()=>submit.disabled=input.value!==info.username;form.append(label,submit);body.append(form);input.focus();form.onsubmit=async event=>{event.preventDefault();if(saving||busy||input.value!==info.username)return;saving=true;busy=true;close.disabled=input.disabled=submit.disabled=true;feedback.textContent='Удаляем…';try{const result=await mutate('students/'+row.id,'DELETE',{username:input.value});dialog.close();busy=false;offset=0;await load();status.textContent=result.file_cleanup_pending?'Ученик удалён из базы. Часть файлов ожидает очистки хранилища администратором.':'Ученик и связанные данные удалены навсегда.'}catch(e){feedback.textContent=e.message}finally{saving=false;busy=false;close.disabled=input.disabled=false;submit.disabled=input.value!==info.username}};
 }catch(e){feedback.textContent=e.message}
}

function focusCalendarOnOpen(){if(!calendarFocusPending||document.querySelector('#overview').hidden)return;const host=document.querySelector('[data-schedule-root]');if(host?.dataset.calendarReady!=='true')return;requestAnimationFrame(()=>{if(!calendarFocusPending||document.querySelector('#overview').hidden)return;const target=document.querySelector('#weekly-view');if(target.hidden)return;window.scrollTo({top:Math.max(0,target.getBoundingClientRect().top+window.scrollY-24),behavior:'auto'});calendarFocusPending=false;});}
window.addEventListener('schedule-ready',focusCalendarOnOpen);

async function showStudentInformation(id){
 if(document.querySelector('#student-information-dialog'))return;
 const dialog=trialElement('dialog',undefined,'student-information-dialog');dialog.id='student-information-dialog';dialog.setAttribute('aria-labelledby','student-information-title');const title=trialElement('h2','Информация об ученике');title.id='student-information-title';const content=trialElement('div','Загружаем данные…'),close=trialElement('button','Закрыть');close.type='button';close.onclick=()=>dialog.close();dialog.append(title,content,close);dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
 try{const row=await get('admin/students/'+id);if(!dialog.open)return;title.textContent=row.name;content.replaceChildren();
 for(const [heading,fields] of [['Данные ученика',[['Логин',row.username],['Статус',row.is_active?'Активный':'В архиве'],['Класс',row.school_grade],['Email',row.email],['Телефон ученика',row.phone],['Часовой пояс',row.effective_timezone]]],['Контакты родителя',[['Имя родителя',row.parent_name],['Телефон родителя',row.parent_phone]]],['Занятия и баланс',[['Цена урока',(row.default_price_kopecks/100).toLocaleString('ru-RU')+' ₽'],['Длительность',row.default_duration_minutes+' мин'],['Текущий баланс',(row.balance_kopecks/100).toLocaleString('ru-RU',{minimumFractionDigits:2})+' ₽'],['Проведено уроков',row.completed_lessons]]]]){const list=trialElement('dl');for(const [label,value] of fields)addField(list,label,value);content.append(trialElement('h3',heading),list)}
 const actions=trialElement('div',undefined,'student-actions'),edit=trialElement('button','Редактировать профиль'),payment=trialElement('button','Пополнить баланс');edit.type=payment.type='button';edit.onclick=()=>{dialog.close();editStudent(row)};payment.onclick=()=>{dialog.close();window.openAdminPayment(row.id)};actions.append(edit,payment);content.append(actions);
 }catch(e){if(dialog.open)content.textContent=e.message}
}
