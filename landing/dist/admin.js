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
  busy = true; items.replaceChildren(); status.textContent = 'Загружаем…';
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  try {
    const result = await get(`admin/${section}?limit=${limit}&offset=${offset}`);
    document.querySelector('#dashboard').hidden = false;
    document.querySelector('#list-title').textContent = section === 'students' ? 'Зарегистрированные ученики' : 'Заявки на пробный урок';
    document.querySelector('#count').textContent = `Всего: ${result.total}. Показано: ${result.items.length}.`;
    for(const row of result.items) {
      const card = document.createElement('article'), title = document.createElement('h3'), fields = document.createElement('dl');
      card.className = 'record'; title.textContent = `№${row.id} · ${row.name}`;
      addField(fields,'Email',row.email);
      if(section === 'trial-requests') {
        addField(fields,'Дата заявки',String(row.created_at).replace('T',' '));
        addField(fields,'Телефон',row.phone); addField(fields,'Направления',row.courses);
        addField(fields,'Комментарий',row.message); addField(fields,'Согласие',row.consent ? 'Получено' : 'Нет');
      }
      card.append(title,fields); items.append(card);
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
