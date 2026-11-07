(() => {
 const settings = fetch('/api/lessons/board-settings', {cache:'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null);
 window.addLessonBoardAction = (parent, lesson, timezone) => {
  if (!parent || !lesson || lesson.status === 'cancelled' || (lesson.status === 'completed' && !lesson.board_created)) return;
  const slot = document.createElement('div'); slot.className = 'lesson-actions'; parent.append(slot);
  void settings.then(async config => {
   if (!config?.enabled || !slot.isConnected) return;
   const opensAt = Date.parse(lesson.starts_at) - config.open_before_seconds * 1000;
   const button = document.createElement('button'); button.type = 'button';
   button.textContent = lesson.status === 'completed' ? 'Посмотреть доску' : 'Открыть доску';
   const status = document.createElement('small'); status.setAttribute('role','status');
   const hint = document.createElement('p'); hint.className = 'muted small';
   hint.textContent = 'Для работы на общей доске нажмите «Открыть доску». Доступ открывается за 30 минут до начала занятия.';
   const video = document.createElement('button'); video.type = 'button'; video.disabled = true; video.textContent = 'Видеосвязь · Скоро';
   let lifecycle = {}, timer;
   const format = value => new Date(value * 1000).toLocaleString('ru-RU', {timeZone:timezone,dateStyle:'short',timeStyle:'short'});
   function render() {
    clearTimeout(timer);
    if (!slot.isConnected) return;
    if (lifecycle.deleted_at) { status.textContent='Доска удалена. PDF доступен в материалах занятия.'; slot.replaceChildren(status); return; }
    const remaining = opensAt - Date.now();
    if (lesson.status === 'scheduled' && remaining > 0) {
     status.textContent='Доска откроется '+format(opensAt / 1000);
     slot.replaceChildren(status,video,hint);
     timer=setTimeout(render,Math.min(remaining,60000));
    } else {
     status.textContent=lifecycle.expires_at && !config.cleanup_enabled ? 'Автоматическое удаление доски пока выключено.' : lifecycle.expires_at ? 'Доска доступна до '+format(lifecycle.expires_at)+(lifecycle.error ? '. Удаление отложено: не удалось сохранить PDF или завершить очистку.' : '') : '';
     slot.replaceChildren(button,video,status,hint);
    }
   }
   button.onclick = async () => {
    const tab=window.open('about:blank','_blank'); if(tab) tab.opener=null; button.disabled=true;
    try {
     const response=await fetch('/api/lessons/'+lesson.id+'/board',{method:'POST',headers:{'X-Requested-With':'KrugPi'}});
     const data=await response.json(); if(!response.ok) throw Error(data.detail || 'Не удалось открыть доску');
     (tab || window).location.assign(data.url);
    } catch(error) { tab?.close(); status.textContent=error.message; }
    finally { button.disabled=false; }
   };
   async function refresh() {
    if(!slot.isConnected) { clearTimeout(timer); document.removeEventListener('visibilitychange',onVisible); window.removeEventListener('focus',refresh); return; }
    if(lesson.status==='completed') {
     try {const response=await fetch('/api/lessons/'+lesson.id+'/board-status',{cache:'no-store'});if(response.ok)lifecycle=await response.json();}catch{}
    }
    render();
   }
   function onVisible() {if(!document.hidden)void refresh();}
   document.addEventListener('visibilitychange',onVisible); window.addEventListener('focus',refresh);
   await refresh();
  });
 };
})();
