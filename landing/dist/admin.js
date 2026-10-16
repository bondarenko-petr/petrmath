let issuedCredentials=null;
const status = document.querySelector('#status');
const items = document.querySelector('#items');
let section = 'trial-requests', offset = 0, busy = false;
const limit = 20;
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
  busy = true; clearCredentials(); items.replaceChildren(); status.textContent = 'Загружаем…';
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  try {
    const params=new URLSearchParams({limit,offset});if(section==='trial-requests'){params.set('view',trialView);params.set('search',trialSearch);if(trialStatus)params.set('status',trialStatus)}
    const result = await get(`admin/${section}?${params}`);
    document.querySelector('#trial-controls').hidden=section!=='trial-requests';items.classList.toggle('trial-list',section==='trial-requests');
    if(section==='trial-requests'){document.querySelector('#trial-active').textContent='В работе ('+result.active_total+')';document.querySelector('#trial-archive').textContent='Архив ('+result.archive_total+')';document.querySelector('#trial-new-count').textContent='Новых: '+result.counts.new;document.querySelector('#trial-active').setAttribute('aria-pressed',String(trialView==='active'));document.querySelector('#trial-archive').setAttribute('aria-pressed',String(trialView==='archive'));}
    document.querySelector('#dashboard').hidden = false;
    loadLessonSummary();
    document.querySelector('#create-student').hidden = section !== 'students';
    document.querySelector('#list-title').textContent = section === 'students' ? 'Зарегистрированные ученики' : 'Заявки на пробный урок';
    document.querySelector('#count').textContent = `Всего: ${result.total}. Показано: ${result.items.length}.`;
    for(const row of result.items) {
      if(section==='trial-requests'){items.append(renderTrialRequest(row));continue;}
      const card = document.createElement('article'), title = document.createElement('h3'), fields = document.createElement('dl');
      card.className = 'record'; title.textContent = row.name;
      const badge = document.createElement('span'); badge.className = 'badge'; badge.textContent = section === 'students' ? `Ученик №${row.id}` : `Заявка №${row.id}`;
      card.append(badge);
      addField(fields,'Email',row.email);
      if(section === 'students') {
        addField(fields,'Логин',row.username);addField(fields,'Статус',row.is_active?'Активен':'В архиве');addField(fields,'Телефон',row.phone);addField(fields,'Класс',row.school_grade);addField(fields,'Цена занятия',(row.default_price_kopecks/100).toFixed(2)+' ₽');addField(fields,'Длительность',row.default_duration_minutes+' мин');
      }
      if(section === 'trial-requests') {
        addField(fields,'Дата заявки',String(row.created_at).replace('T',' '));
        addField(fields,'Телефон',row.phone); addField(fields,'Направления',row.courses);
        addField(fields,'Комментарий',row.message); addField(fields,'Согласие',row.consent ? 'Получено' : 'Нет');
      }
      card.append(title,fields);
      if(section === 'students') {
        const actions=document.createElement('div');actions.className='student-actions';
        for(const [label,handler] of [['Редактировать',()=>editStudent(row)],['Сбросить пароль',()=>resetPassword(row)],[row.is_active?'Архивировать':'Восстановить',()=>toggleActive(row)]]){const button=document.createElement('button');button.textContent=label;button.onclick=handler;actions.append(button);}
        card.append(actions);
      }
      items.append(card);
    }
    status.textContent = result.items.length ? '' : 'Пока записей нет.';
    document.querySelectorAll('button').forEach(button => button.disabled = false);
    document.querySelector('#prev').disabled = offset === 0;
    document.querySelector('#next').disabled = offset + limit >= result.total;
    return true;
  } catch(error) { status.textContent = error.message; document.querySelector('#dashboard').hidden = error.status===401||error.status===403;for(const id of ['requests-tab','students-tab','refresh','trial-active','trial-archive','trial-reset'])document.getElementById(id).disabled=false; }
  finally { busy = false; }
}
function choose(value) {
  if(busy||trialSaving)return;
  section=value; offset=0;
  document.querySelector('#requests-tab').setAttribute('aria-pressed',String(section === 'trial-requests'));
  document.querySelector('#students-tab').setAttribute('aria-pressed',String(section === 'students'));
  load();
}
document.querySelector('#requests-tab').onclick=()=>choose('trial-requests');
document.querySelector('#students-tab').onclick=()=>choose('students');
document.querySelector('#prev').onclick=()=>{offset=Math.max(0,offset-limit);load();};
document.querySelector('#next').onclick=()=>{offset+=limit;load();};
document.querySelector('#refresh').onclick=()=>load();
load();

document.querySelector('a[href="#students-tab"]').addEventListener('click', () => { if(!busy) choose('students'); });

let editing=null;
const studentForm=document.querySelector('#student-form');
const studentFormStatus=document.querySelector('#student-form-status');
async function mutate(path,method,data){
 const response=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-Requested-With':'KrugPi'},body:JSON.stringify(data)});
 const result=await response.json();if(!response.ok){const labels={name:'Имя',username:'Логин',email:'Email',school_grade:'Класс',default_price_kopecks:'Цена занятия',default_duration_minutes:'Длительность'};const detail=typeof result.detail==='string'?result.detail:Array.isArray(result.detail)?result.detail.map(issue=>(labels[issue.loc?.at(-1)]||'Поле')+': '+issue.msg).join('; '):'Проверьте заполнение полей.';throw new Error(detail);}return result;
}
function clearCredentials(){issuedCredentials=null;document.querySelector('#email-status').textContent='';document.querySelector('#send-credentials').hidden=true;document.querySelector('#credentials').hidden=true;document.querySelector('#issued-password').textContent='';document.querySelector('#issued-username').textContent='';}
function showCredentials(data){issuedCredentials=data;document.querySelector('#email-help').textContent=data.email?'Письмо будет отправлено на '+data.email+'. Оно объяснит, как войти и сменить временный пароль.':'Email не указан. Передайте пароль вручную; для отправки укажите email и выполните сброс пароля.';document.querySelector('#send-credentials').hidden=!data.email;document.querySelector('#send-credentials').disabled=false;document.querySelector('#email-status').textContent='';document.querySelector('#issued-username').textContent=data.username;document.querySelector('#issued-password').textContent=data.temporary_password;document.querySelector('#credentials').hidden=false;document.querySelector('#credentials').scrollIntoView({block:'center'});}
function editStudent(row=null){clearCredentials();editing=row?.id??null;studentForm.reset();studentFormStatus.textContent='';const login=studentForm.elements.username;const legacy=!!row&&!/^[a-zA-Z0-9._-]{3,40}$/.test(row.username);login.readOnly=legacy;login.maxLength=legacy?254:40;login.minLength=legacy?1:3;if(legacy){login.removeAttribute('pattern');studentFormStatus.textContent='Сохранён прежний логин для входа. Остальные данные можно редактировать.';}else login.setAttribute('pattern','[a-zA-Z0-9._\\-]+');document.querySelector('#student-editor').hidden=false;document.querySelector('#editor-title').textContent=row?'Редактировать ученика':'Добавить ученика';if(row){for(const field of ['name','username','email','phone','school_grade','default_duration_minutes'])studentForm.elements[field].value=row[field]??'';studentForm.elements.price.value=(row.default_price_kopecks/100).toFixed(2);}studentForm.scrollIntoView({block:'start'});studentForm.elements.name.focus();}
document.querySelector('#create-student').onclick=()=>editStudent();
document.querySelector('#cancel-editor').onclick=()=>{document.querySelector('#student-editor').hidden=true;studentForm.reset();};
document.querySelector('#close-credentials').onclick=clearCredentials;
studentForm.addEventListener('submit',async event=>{
 event.preventDefault();const price=studentForm.elements.price.value.replace(',','.');if(!/^\d+(\.\d{1,2})?$/.test(price)){studentFormStatus.textContent='Введите цену в рублях с точностью до копеек.';return;}
 const [rubles,kopecks='']=price.split('.');const data={name:studentForm.elements.name.value,username:studentForm.elements.username.value,email:studentForm.elements.email.value||null,phone:studentForm.elements.phone.value,school_grade:studentForm.elements.school_grade.value?Number(studentForm.elements.school_grade.value):null,default_price_kopecks:Number(rubles)*100+Number(kopecks.padEnd(2,'0')),default_duration_minutes:Number(studentForm.elements.default_duration_minutes.value)};
 const button=studentForm.querySelector('button[type=submit]');button.disabled=true;studentFormStatus.textContent='Сохраняем…';
 try{const result=await mutate('students'+(editing?'/'+editing:''),editing?'PUT':'POST',data);document.querySelector('#student-editor').hidden=true;studentForm.reset();offset=0;await load();status.textContent='Данные ученика сохранены. Новая цена применяется к новым занятиям.';if(result.temporary_password)showCredentials(result);}catch(error){studentFormStatus.textContent=error.message;}finally{button.disabled=false;}
});
async function resetPassword(row){if(!confirm('Сбросить пароль ученика '+row.name+'? Старые сессии будут завершены.'))return;clearCredentials();try{const data=await mutate('students/'+row.id+'/reset-password','POST',{});showCredentials(data);}catch(error){status.textContent=error.message;}}
async function toggleActive(row){if(!confirm((row.is_active?'Архивировать':'Восстановить')+' ученика '+row.name+'?'))return;clearCredentials();try{await mutate('students/'+row.id+'/active','PATCH',{is_active:!row.is_active});await load();}catch(error){status.textContent=error.message;}}

document.querySelector('#send-credentials').onclick=async()=>{
 const data=issuedCredentials;if(!data)return;
 if(!confirm('Отправить логин и временный пароль на '+data.email+'?'))return;
 const button=document.querySelector('#send-credentials');button.disabled=true;
 document.querySelector('#email-status').textContent='Отправляем письмо…';
 try{await mutate('students/'+data.id+'/send-credentials','POST',{temporary_password:data.temporary_password});if(issuedCredentials===data)document.querySelector('#email-status').textContent='Почтовый сервер принял письмо. Попросите ученика проверить входящие и папку «Спам».';}
 catch(error){if(issuedCredentials===data){document.querySelector('#email-status').textContent=error.message;button.disabled=false;}}
};
