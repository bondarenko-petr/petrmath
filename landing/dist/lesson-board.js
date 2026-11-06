(() => {
 const settings = fetch('/api/lessons/board-settings', {cache: 'no-store'})
  .then(response => response.ok ? response.json() : null)
  .catch(() => null);

 window.addLessonBoardAction = (parent, lesson, timezone) => {
  if (!lesson || lesson.status === 'cancelled' || (lesson.status === 'completed' && !lesson.board_created)) return;
  const slot = document.createElement('div');
  slot.className = 'lesson-actions';
  parent.append(slot);
  void settings.then(config => {
   if (!config?.enabled) return;
   const opensAt = Date.parse(lesson.starts_at) - config.open_before_seconds * 1000;
   const button = document.createElement('button');
   button.type = 'button';
   button.textContent = lesson.status === 'completed' ? 'Посмотреть доску' : 'Открыть доску';
   const status = document.createElement('small');
   status.setAttribute('role', 'status');
   function render() {
    const remaining = opensAt - Date.now();
    if (lesson.status === 'scheduled' && remaining > 0) {
     status.textContent = 'Доска откроется в ' + new Date(opensAt).toLocaleTimeString('ru-RU', {
      timeZone: timezone, hour: '2-digit', minute: '2-digit',
     });
     slot.replaceChildren(status);
     setTimeout(() => { if (slot.isConnected) render(); }, Math.min(remaining, 60000));
    } else {
     status.textContent = '';
     slot.replaceChildren(button, status);
    }
   }
   button.onclick = async () => {
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    button.disabled = true;
    try {
     const response = await fetch('/api/lessons/' + lesson.id + '/board', {
      method: 'POST', headers: {'X-Requested-With': 'KrugPi'},
     });
     const data = await response.json();
     if (!response.ok) throw Error(data.detail || 'Не удалось открыть доску');
     (tab || window).location.assign(data.url);
    } catch (error) {
     tab?.close();
     status.textContent = error.message;
    } finally {
     button.disabled = false;
    }
   };
   render();
  });
 };
})();
