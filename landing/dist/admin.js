let issuedCredentials=null;
const status = document.querySelector('#status');
const items = document.querySelector('#items');
let section = 'trial-requests', offset = 0, busy = false;
const limit = 20;
async function get(path) {
  const response = await fetch('/api/' + path);
  const result = await response.json();
  if(!response.ok) throw new Error(response.status === 401 ? 'Войдите в аккаунт через страницу «Мой профиль».' : response.status === 403 ? 'У вашего аккаунта нет прав администратора.' : 'Не удалось загрузить данные. Попробуйте обновить страницу.');
  return result;
}
function addField(list, label, value) {
  const term = document.createElement('dt'), description = document.createElement('dd');
  term.textContent = label; description.textContent = String(value ?? '—') || '—';
  list.append(term, description);
}
async function load() {
  if(busy) return;
  busy = true; clearCredentials(); items.replaceChildren(); status.textContent = 'Загружаем…';
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  try {
    const result = await get(`admin/${section}?limit=${limit}&offset=${offset}`);
    document.querySelector('#dashboard').hidden = false;
    loadLessonSummary();
    document.querySelector('#create-student').hidden = section !== 'students';
    document.querySelector('#list-title').textContent = section === 'students' ? 'Зарегистрированные ученики' : 'Заявки на пробный урок';
    document.querySelector('#count').textContent = `Всего: ${result.total}. Показано: ${result.items.length}.`;
    for(const row of result.items) {
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
  } catch(error) { status.textContent = error.message; document.querySelector('#dashboard').hidden = true; }
  finally { busy = false; }
}
function choose(value) {
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
async function mutate(path,method,data){
 const response=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-Requested-With':'KrugPi'},body:JSON.stringify(data)});
 const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Проверьте заполнение полей.');return result;
}
function clearCredentials(){issuedCredentials=null;document.querySelector('#email-status').textContent='';document.querySelector('#send-credentials').hidden=true;document.querySelector('#credentials').hidden=true;document.querySelector('#issued-password').textContent='';document.querySelector('#issued-username').textContent='';}
function showCredentials(data){issuedCredentials=data;document.querySelector('#email-help').textContent=data.email?'Письмо будет отправлено на '+data.email+'. Оно объяснит, как войти и сменить временный пароль.':'Email не указан. Передайте пароль вручную; для отправки укажите email и выполните сброс пароля.';document.querySelector('#send-credentials').hidden=!data.email;document.querySelector('#send-credentials').disabled=false;document.querySelector('#email-status').textContent='';document.querySelector('#issued-username').textContent=data.username;document.querySelector('#issued-password').textContent=data.temporary_password;document.querySelector('#credentials').hidden=false;document.querySelector('#credentials').scrollIntoView({block:'center'});}
function editStudent(row=null){clearCredentials();editing=row?.id??null;studentForm.reset();document.querySelector('#student-editor').hidden=false;document.querySelector('#editor-title').textContent=row?'Редактировать ученика':'Добавить ученика';if(row){for(const field of ['name','username','email','phone','school_grade','default_duration_minutes'])studentForm.elements[field].value=row[field]??'';studentForm.elements.price.value=(row.default_price_kopecks/100).toFixed(2);}studentForm.elements.name.focus();}
document.querySelector('#create-student').onclick=()=>editStudent();
document.querySelector('#cancel-editor').onclick=()=>{document.querySelector('#student-editor').hidden=true;studentForm.reset();};
document.querySelector('#close-credentials').onclick=clearCredentials;
studentForm.addEventListener('submit',async event=>{
 event.preventDefault();const price=studentForm.elements.price.value.replace(',','.');if(!/^\d+(\.\d{1,2})?$/.test(price)){status.textContent='Введите цену в рублях с точностью до копеек.';return;}
 const [rubles,kopecks='']=price.split('.');const data={name:studentForm.elements.name.value,username:studentForm.elements.username.value,email:studentForm.elements.email.value||null,phone:studentForm.elements.phone.value,school_grade:studentForm.elements.school_grade.value?Number(studentForm.elements.school_grade.value):null,default_price_kopecks:Number(rubles)*100+Number(kopecks.padEnd(2,'0')),default_duration_minutes:Number(studentForm.elements.default_duration_minutes.value)};
 const button=studentForm.querySelector('button[type=submit]');button.disabled=true;
 try{const result=await mutate('students'+(editing?'/'+editing:''),editing?'PUT':'POST',data);document.querySelector('#student-editor').hidden=true;studentForm.reset();offset=0;await load();if(result.temporary_password)showCredentials(result);}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
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
