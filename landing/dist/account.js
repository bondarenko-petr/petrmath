const form = document.querySelector('#auth-form');
const status = document.querySelector('#status');
const submit = document.querySelector('#submit');
let mode = new URLSearchParams(location.search).get('mode') === 'register' ? 'register' : 'login';
function setMode(value) {
  mode = value;
  const registering = mode === 'register';
  ['name-group','repeat-group','password-help'].forEach(id => document.getElementById(id).hidden = !registering);
  form.elements.name.required = registering;
  document.querySelector('#repeat').required = registering;
  form.elements.password.minLength = registering ? 10 : 1;
  form.elements.password.autocomplete = registering ? 'new-password' : 'current-password';
  document.querySelector('#auth-title').textContent = registering ? 'Создать аккаунт' : 'Вход в личный кабинет';
  submit.textContent = registering ? 'Зарегистрироваться' : 'Войти';
  document.querySelector('#login-tab').setAttribute('aria-pressed', String(!registering));
  document.querySelector('#register-tab').setAttribute('aria-pressed', String(registering));
  status.textContent = '';
}
async function api(path, data) {
  const response = await fetch('/api/auth/' + path, data ? {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'KrugPi'}, body:JSON.stringify(data)} : {});
  const result = await response.json();
  if (!response.ok) {
    const error = new Error(typeof result.detail === 'string' ? result.detail : 'Проверьте заполнение полей.');
    error.status = response.status;
    throw error;
  }
  return result;
}
async function loadProfile() {
  const user = await api('me');
  document.querySelector('#auth-panel').hidden = true;
  document.querySelector('#profile-panel').hidden = false;
  document.querySelector('#welcome').textContent = 'Здравствуйте, ' + user.name + '!';
  document.querySelector('#profile-name').textContent = user.name;
  document.querySelector('#profile-email').textContent = user.email;
  document.querySelector('#admin-link').hidden = user.role !== 'admin';
  document.querySelector('#profile-role').textContent = ({student:'Ученик',admin:'Администратор',teacher:'Преподаватель'})[user.role] || user.role;
}
document.querySelector('#login-tab').onclick = () => setMode('login');
document.querySelector('#register-tab').onclick = () => setMode('register');
form.addEventListener('submit', async event => {
  event.preventDefault();
  if(mode === 'register' && form.elements.password.value !== document.querySelector('#repeat').value){ status.textContent='Пароли не совпадают.'; return; }
  submit.disabled = true;
  status.textContent = 'Подождите…';
  try {
    const data = {email:form.elements.email.value, password:form.elements.password.value};
    if(mode === 'register') data.name = form.elements.name.value;
    await api(mode, data);
    form.reset();
    await loadProfile();
    status.textContent = '';
  } catch(error) { status.textContent = error.message; }
  finally { submit.disabled = false; }
});
document.querySelector('#logout').onclick = async () => {
  const button = document.querySelector('#logout'); button.disabled = true;
  try { await api('logout', {}); document.querySelector('#profile-panel').hidden = true; document.querySelector('#auth-panel').hidden = false; setMode('login'); status.textContent = 'Вы вышли из аккаунта.'; }
  catch(error){status.textContent=error.message;}
  finally{button.disabled=false;}
};
setMode(mode);
loadProfile().catch(error => { if(error.status !== 401) status.textContent = 'Не удалось загрузить профиль. Попробуйте обновить страницу.'; });
