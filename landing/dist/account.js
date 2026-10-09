const form=document.querySelector('#auth-form'), status=document.querySelector('#status');
let currentUser=null;
async function api(path,data){
 const response=await fetch('/api/auth/'+path,data?{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'KrugPi'},body:JSON.stringify(data)}:{});
 const result=await response.json();
 if(!response.ok){const error=new Error(typeof result.detail==='string'?result.detail:'Проверьте заполнение полей.');error.status=response.status;throw error;}return result;
}
function passwordPanel(){
 document.querySelector('#profile-panel').hidden=true;document.querySelector('#auth-panel').hidden=true;document.querySelector('#password-panel').hidden=false;
 document.querySelector('main').classList.remove('profile-view');document.querySelector('#cancel-password').hidden=Boolean(currentUser.must_change_password);
 document.querySelector('#change-help').textContent=currentUser.must_change_password?'Перед входом в кабинет замените временный пароль своим.':'Выберите новый пароль длиной от 10 символов.';
}
async function loadProfile(){
 currentUser=await api('me');status.textContent='';document.querySelector('#auth-panel').hidden=true;
 if(currentUser.must_change_password){passwordPanel();return;}
 document.querySelector('#password-panel').hidden=true;document.querySelector('#profile-panel').hidden=false;document.querySelector('main').classList.add('profile-view');
 document.querySelector('#welcome').textContent='Здравствуйте, '+currentUser.name+'!';document.querySelector('#profile-name').textContent=currentUser.name;
 document.querySelector('#profile-email').textContent=currentUser.username;document.querySelector('#profile-role').textContent=currentUser.role==='admin'?'Администратор':'Ученик';
 if(currentUser.role==='student')loadLessonSummary();
 document.querySelector('#admin-link').hidden=currentUser.role!=='admin';document.querySelectorAll('.student-content').forEach(e=>e.hidden=currentUser.role==='admin');
}
form.addEventListener('submit',async event=>{event.preventDefault();const button=document.querySelector('#submit');button.disabled=true;status.textContent='Входим…';try{await api('login',{username:form.elements.username.value,password:form.elements.password.value});form.reset();await loadProfile();}catch(error){status.textContent=error.message;}finally{button.disabled=false;}});
document.querySelector('#password-form').addEventListener('submit',async event=>{
 event.preventDefault();const next=document.querySelector('#new-password').value;if(next!==document.querySelector('#repeat-password').value){status.textContent='Пароли не совпадают.';return;}
 const button=document.querySelector('#save-password');button.disabled=true;
 try{await api('change-password',{current_password:document.querySelector('#current-password').value,new_password:next});event.target.reset();await loadProfile();status.textContent='Пароль изменён.';}catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector('#open-password').onclick=passwordPanel;document.querySelector('#cancel-password').onclick=()=>loadProfile().catch(error=>status.textContent=error.message);
document.querySelector('#logout').onclick=async()=>{try{await api('logout',{});currentUser=null;document.querySelector('#profile-panel').hidden=true;document.querySelector('#password-panel').hidden=true;document.querySelector('#auth-panel').hidden=false;document.querySelector('main').classList.remove('profile-view');status.textContent='Вы вышли из аккаунта.';}catch(error){status.textContent=error.message;}};
loadProfile().catch(error=>{if(error.status!==401)status.textContent='Не удалось загрузить профиль. Проверьте подключение и миграцию базы.';});

document.querySelector('#password-logout').onclick=()=>document.querySelector('#logout').onclick();
