const form=document.querySelector('#auth-form'), status=document.querySelector('#status');
let currentUser=null,profileScrollY=0,returnToProfile=false,profileNavigationOpened=false;
const profileDialog=document.querySelector('#profile-dialog');
async function api(path,data){
 const response=await fetch('/api/auth/'+path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'KrugPi'},body:JSON.stringify(data)}:{});
 const result=await response.json();
 if(!response.ok){const error=new Error(typeof result.detail==='string'?result.detail:'Проверьте заполнение полей.');error.status=response.status;throw error;}return result;
}
function passwordPanel(){
 if(profileDialog.open){returnToProfile=true;profileDialog.close()}

 document.querySelector('#profile-panel').hidden=true;document.querySelector('#auth-panel').hidden=true;document.querySelector('#password-panel').hidden=false;
 document.querySelector('main').classList.remove('profile-view');document.querySelector('#cancel-password').hidden=Boolean(currentUser.must_change_password);
 document.querySelector('#change-help').textContent=currentUser.must_change_password?'Перед входом в кабинет замените временный пароль своим.':'Выберите новый пароль длиной от 10 символов.';
 document.querySelector('#password-panel').scrollIntoView({block:'start'});
}
async function loadProfile(){
 currentUser=await api('me');clearStudentDashboard();status.textContent='';document.querySelector('#auth-panel').hidden=true;
 if(currentUser.must_change_password){passwordPanel();return;}
 if(currentUser.role==='admin'&&new URLSearchParams(location.search).get('profile')!=='1'){location.replace('admin.html');return;}
 document.querySelector('#password-panel').hidden=true;document.querySelector('#profile-panel').hidden=false;document.querySelector('main').classList.add('profile-view');
 document.querySelector('#welcome').textContent='Здравствуйте, '+currentUser.name+'!';document.querySelector('#profile-name').textContent=currentUser.name;
 document.querySelector('#profile-edit-form').hidden=true;document.querySelector('#profile-contact-email').textContent=currentUser.email||'Не указан';document.querySelector('#profile-phone').textContent=currentUser.phone||'Не указан';document.querySelector('#profile-parent-name').textContent=currentUser.parent_name||'Не указано';document.querySelector('#profile-parent-phone').textContent=currentUser.parent_phone||'Не указан';document.querySelector('#profile-timezone').textContent=currentUser.effective_timezone;
 document.querySelector('#profile-email').textContent=currentUser.username;document.querySelector('#profile-role').textContent=currentUser.role==='admin'?'Администратор':'Ученик';
 if(currentUser.role==='student'){void loadStudentCalendar();loadLessonSummary();loadFinanceSummary();loadMaterialsSummary();}
 document.querySelector('#open-profile').hidden=false;document.querySelector('#admin-link').hidden=true;document.querySelectorAll('.student-content').forEach(e=>e.hidden=currentUser.role==='admin');if(currentUser.role==='student'){window.mountStudentNavigation('calendar');if(new URLSearchParams(location.search).get('profile')==='1'&&!profileNavigationOpened){profileNavigationOpened=true;document.querySelector('#open-profile').click()}}
 if(currentUser.role==='admin'){window.mountAdminNavigation('profile');if(!profileNavigationOpened){profileNavigationOpened=true;document.querySelector('#open-profile').click()}}
}
form.addEventListener('submit',async event=>{event.preventDefault();const button=document.querySelector('#submit');button.disabled=true;status.textContent='Входим…';try{await api('login',{username:form.elements.username.value,password:form.elements.password.value});form.reset();history.replaceState(null,'','account.html');await loadProfile();}catch(error){status.textContent=error.message;}finally{button.disabled=false;}});
document.querySelector('#password-form').addEventListener('submit',async event=>{
 event.preventDefault();const next=document.querySelector('#new-password').value;if(next!==document.querySelector('#repeat-password').value){status.textContent='Пароли не совпадают.';return;}
 const button=document.querySelector('#save-password');button.disabled=true;
 try{await api('change-password',{current_password:document.querySelector('#current-password').value,new_password:next});event.target.reset();await loadProfile();status.textContent='Пароль изменён.';reopenProfileAfterPassword('Пароль изменён.');}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector('#open-password').onclick=passwordPanel;document.querySelector('#cancel-password').onclick=()=>loadProfile().then(()=>reopenProfileAfterPassword()).catch(error=>status.textContent=error.message);
document.querySelector('#logout').onclick=async()=>{try{await api('logout',{});if(currentUser?.role==='admin'){location.replace('account.html');return}currentUser=null;returnToProfile=false;if(profileDialog.open)profileDialog.close();clearStudentDashboard();document.querySelector('#profile-panel').hidden=true;document.querySelector('#password-panel').hidden=true;document.querySelector('#auth-panel').hidden=false;document.querySelector('main').classList.remove('profile-view');status.textContent='Вы вышли из аккаунта.';}catch(error){status.textContent=error.message;}};
loadProfile().catch(error=>{if(error.status!==401)status.textContent='Не удалось загрузить профиль. Проверьте подключение и миграцию базы.';});

document.querySelector('#password-logout').onclick=()=>document.querySelector('#logout').onclick();

function clearStudentDashboard(){window.unmountStudentNavigation?.();document.querySelector('#profile-edit-form').hidden=true;document.querySelector('#profile-edit-form').reset();stopStudentCalendar();lessonSummaryGeneration++;financeSummaryGeneration++;materialsSummaryGeneration++;document.querySelectorAll('[data-next-lesson],[data-next-lessons],[data-week-lessons],[data-finance-summary],[data-homework-summary],[data-notes-summary]').forEach(e=>e.replaceChildren());}

const profileEdit=document.querySelector('#profile-edit-form');
document.querySelector('#edit-profile').onclick=()=>{
 if(currentUser?.role!=='student')return;
 profileEdit.reset();profileEdit.elements.email.value=currentUser.email||'';profileEdit.elements.phone.value=currentUser.phone||'';profileEdit.elements.parent_name.value=currentUser.parent_name||'';profileEdit.elements.parent_phone.value=currentUser.parent_phone||'';const picker=profileEdit.elements.timezone;picker.replaceChildren(new Option('По умолчанию ('+currentUser.effective_timezone+')',''));const names={'Europe/Moscow':'Москва','Europe/Berlin':'Берлин','Asia/Vladivostok':'Владивосток','Asia/Yekaterinburg':'Екатеринбург','Asia/Novosibirsk':'Новосибирск','Europe/Kaliningrad':'Калининград','UTC':'UTC'},zones=new Set(['UTC','Europe/Moscow','Europe/Berlin','Asia/Vladivostok',...(Intl.supportedValuesOf?Intl.supportedValuesOf('timeZone'):[]),...(currentUser.timezone?[currentUser.timezone]:[])]);for(const zone of [...zones].sort())picker.add(new Option(names[zone]?names[zone]+' ('+zone+')':zone,zone));picker.value=currentUser.timezone||'';document.querySelector('#profile-edit-status').textContent='';profileEdit.hidden=false;profileEdit.elements.email.focus();
};
document.querySelector('#cancel-profile-edit').onclick=()=>{profileEdit.hidden=true;profileEdit.reset()};
profileEdit.onsubmit=async event=>{event.preventDefault();const button=profileEdit.querySelector('[type=submit]'),feedback=document.querySelector('#profile-edit-status');button.disabled=true;feedback.textContent='Сохраняем…';try{await api('profile',{email:profileEdit.elements.email.value.trim()||null,phone:profileEdit.elements.phone.value,parent_name:profileEdit.elements.parent_name.value,parent_phone:profileEdit.elements.parent_phone.value,timezone:profileEdit.elements.timezone.value||null});await loadProfile();status.textContent='Профиль сохранён. Расписание обновлено в вашем часовом поясе.';document.querySelector('#profile-dialog-status').textContent='Профиль сохранён.'}catch(e){feedback.textContent=e.message}finally{button.disabled=false}};

document.querySelector('#open-profile').onclick=()=>{if(!currentUser)return;profileScrollY=window.scrollY;document.querySelector('#profile-dialog-status').textContent='';profileDialog.showModal();window.setStudentNavActive?.('profile')};
document.querySelector('#close-profile').onclick=()=>profileDialog.close();
profileDialog.addEventListener('close',()=>{window.setStudentNavActive?.('calendar');document.querySelector('#profile-edit-form').hidden=true;if(currentUser?.role==='admin'&&!returnToProfile){location.replace('admin.html');return}if(!returnToProfile)requestAnimationFrame(()=>window.scrollTo({top:profileScrollY,behavior:'auto'}))});
function reopenProfileAfterPassword(message=''){if(!returnToProfile)return;returnToProfile=false;document.querySelector('#profile-dialog-status').textContent=message;profileDialog.showModal();window.setStudentNavActive?.('profile')}
