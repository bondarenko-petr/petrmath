(()=>{
 const q=s=>document.querySelector(s),status=q('#status');let busy=false,offset=0,generation=0,timer=null,ready=false,noticePending=null,cleanupBusy=false;
 const states={building:'Создаётся',uploading:'Загружается',verifying:'Проверяется',verified:'Проверен',failed:'Ошибка'};
 async function request(path,method='GET',data){const response=await fetch('/api/'+path,{method,cache:'no-store',headers:method==='GET'?{}:{'Content-Type':'application/json','X-Requested-With':'KrugPi'},...(data?{body:JSON.stringify(data)}:{})});const result=await response.json();if(!response.ok){const error=Error(typeof result.detail==='string'?result.detail:result.detail?.message||'Не удалось выполнить запрос.');error.code=result.detail?.code;throw error}return result}
 function selection(){const owner=q('#archive-student').value;q('#archive-create').disabled=busy||!owner;q('#archive-selection-help').hidden=!!owner;const url=new URL(location.href);if(owner)url.searchParams.set('student_id',owner);else url.searchParams.delete('student_id');history.replaceState(null,'',url)}
 const el=(tag,value)=>{const node=document.createElement(tag);if(value!==undefined)node.textContent=value;return node};
 const date=value=>value?value.split('-').reverse().join('.'):'—';
 const cleanupDialog=q('#cleanup-dialog'),cleanupTitle=q('#cleanup-title'),cleanupMessage=q('#cleanup-message'),cleanupDetails=q('#cleanup-details'),cleanupConfirm=q('#cleanup-confirm'),cleanupClose=q('#cleanup-close'),cleanupEarly=q('#cleanup-early'),cleanupAck=q('#cleanup-early-ack'),cleanupAckLabel=q('#cleanup-early-label');
 let deleting=false,cleanupOwner=null;
 cleanupClose.onclick=()=>cleanupDialog.close();
 cleanupDialog.addEventListener('cancel',event=>{if(deleting)event.preventDefault()});
 cleanupDialog.addEventListener('close',()=>{const button=Array.from(document.querySelectorAll('.archive-cleanup-button')).find(node=>node.dataset.archiveId===cleanupOwner);(button||q('#archive-refresh')).focus()});
 function cleanupView(title,message){cleanupTitle.textContent=title;cleanupMessage.textContent=message;cleanupConfirm.hidden=true;cleanupConfirm.disabled=false;cleanupConfirm.textContent='Удалить файлы с сервера';cleanupEarly.hidden=true;cleanupAckLabel.hidden=true;cleanupAck.checked=false;cleanupClose.disabled=false;cleanupClose.textContent='Закрыть';cleanupDialog.removeAttribute('aria-busy')}
 function cleanupButton(row){
  const button=el('button','Удалить исходные файлы');button.type='button';button.className='archive-cleanup-button';button.dataset.archiveId=row.id;
  button.onclick=async()=>{
   if(cleanupBusy)return;cleanupBusy=true;cleanupOwner=row.id;button.disabled=true;clearTimeout(timer);
   cleanupDetails.textContent=(row.student_name||'Ученик #'+row.student_id)+' · '+row.filename;
   cleanupView('Проверка перед очисткой','Проверяем ZIP на Google Диске и исходные файлы. Пока ничего не удаляется…');
   cleanupDialog.setAttribute('aria-busy','true');cleanupDialog.showModal();cleanupClose.focus();
   try{
    const path='material-archives/'+encodeURIComponent(row.id);
    let preview,early=false;
    try{preview=await request(path+'/cleanup-preview','POST')}
    catch(error){
     if(error.code!=='waiting_period'||!cleanupDialog.open)throw error;
     cleanupView('Срок очистки ещё не наступил',error.message+' Можно удалить исходники досрочно после дополнительных проверок и подтверждения.');
     cleanupEarly.hidden=false;cleanupClose.textContent='Отмена';
     const proceed=await new Promise(resolve=>{
      const finish=value=>{cleanupDialog.removeEventListener('close',cancel);cleanupEarly.onclick=null;resolve(value)};
      const cancel=()=>finish(false);cleanupDialog.addEventListener('close',cancel,{once:true});cleanupEarly.onclick=()=>finish(true);
     });
     if(!proceed)return;
     early=true;cleanupView('Проверка досрочной очистки','Проверяем ZIP на Google Диске и исходники. Пока ничего не удаляется…');cleanupDialog.setAttribute('aria-busy','true');
     preview=await request(path+'/cleanup-preview?early=true','POST');
    }
    if(!cleanupDialog.open)return;
    const amount=preview.bytes<1024*1024?(preview.bytes/1024).toLocaleString('ru-RU',{maximumFractionDigits:1})+' КБ':(preview.bytes/1024/1024).toLocaleString('ru-RU',{maximumFractionDigits:1})+' МБ';
    cleanupView('Удалить исходные файлы?','С сервера сайта будут удалены файлы: '+preview.file_count+' · '+amount+'. ZIP на Google Диске, тексты заданий и история занятий сохранятся. Исходные вложения будут доступны через архив.');
    if(early){
     const deadline=new Date(preview.cleanup_not_before*1000).toLocaleString('ru-RU');
     cleanupTitle.textContent='Досрочное удаление исходников';cleanupMessage.textContent='Обычная очистка доступна: '+deadline+'.\n\n'+cleanupMessage.textContent;
     cleanupAckLabel.hidden=false;cleanupConfirm.disabled=true;cleanupConfirm.textContent='Всё равно удалить';cleanupAck.onchange=()=>{cleanupConfirm.disabled=!cleanupAck.checked};
    }
    cleanupConfirm.hidden=false;cleanupClose.textContent='Отмена';cleanupClose.focus();
    const confirmed=await new Promise(resolve=>{
     const finish=value=>{cleanupDialog.removeEventListener('close',cancel);cleanupConfirm.onclick=null;resolve(value)};
     const cancel=()=>finish(false);cleanupDialog.addEventListener('close',cancel,{once:true});cleanupConfirm.onclick=()=>finish(true);
    });
    if(!confirmed){status.textContent='Удаление отменено. Файлы сохранены.';return}
    const earlyAcknowledged=early&&cleanupAck.checked;
    deleting=true;cleanupView('Удаление исходников','Повторно проверяем архив и удаляем только подтверждённые исходные вложения. Дождитесь результата…');cleanupClose.disabled=true;cleanupDialog.setAttribute('aria-busy','true');
    const result=await request(path+'/cleanup','POST',{token:preview.token,early,early_ack:earlyAcknowledged});status.textContent=result.message;
    cleanupView('Очистка завершена',result.message);cleanupClose.focus();
   }catch(error){
    status.textContent=error.message;
    if(cleanupDialog.open){cleanupView(deleting?'Не удалось завершить очистку':'Очистка пока недоступна',error.message);cleanupClose.textContent='Понятно';cleanupClose.focus()}
   }finally{deleting=false;cleanupBusy=false;button.disabled=false;await load()}
  };return button;
 }
 async function load(){if(!ready||cleanupBusy)return;clearTimeout(timer);const token=++generation;try{const params=new URLSearchParams({limit:20,offset,errors_only:q('#errors-only').checked});if(q('#archive-student').value)params.set('student_id',q('#archive-student').value);const result=await request('material-archives?'+params);if(token!==generation)return;const body=q('#archive-rows');body.replaceChildren();let active=false;for(const row of result.items){const tr=el('tr'),name=el('td',row.student_name||'Ученик #'+row.student_id),period=el('td',date(row.period_from)+' — '+date(row.period_to)),size=el('td',row.file_count+' файлов');size.append(el('small',row.lesson_count+' занятий · '+(row.size?(row.size/1024/1024).toLocaleString('ru-RU',{maximumFractionDigits:1})+' МБ':'размер уточняется')));period.append(el('small','Создан: '+new Date(row.created_at*1000).toLocaleDateString('ru-RU')));const state=el('td'),badge=el('span',states[row.status]||row.status);badge.className='archive-status '+row.status;state.append(badge);if(row.error){const error=el('small',row.error);error.className='archive-failure';state.append(error)}state.append(window.renderArchiveLifecycle(row));const action=el('td');if(row.status==='verified'){const link=el('a','Скачать ZIP →');link.href='/api/material-archives/'+encodeURIComponent(row.id)+'/download';action.append(link);if(!row.cleanup_at){const button=el('button','Проверить и отправить уведомление');button.type='button';button.onclick=async()=>{if(!confirm('Проверить архив и отправить письмо ученику? Исходные файлы не удаляются.'))return;button.disabled=true;noticePending=row.id;status.textContent='Проверяем архив и уведомление…';try{await request('material-archives/'+encodeURIComponent(row.id)+'/notify','POST');status.textContent='Проверка запущена без удаления файлов. Обновите список через несколько секунд.';setTimeout(()=>void load(),2000)}catch(error){noticePending=null;status.textContent=error.message}finally{button.disabled=false}};action.append(button);action.append(cleanupButton(row))}}else action.textContent='—';tr.append(name,period,size,state,action);body.append(tr);if(['building','uploading','verifying'].includes(row.status)||row.notification_status==='checking')active=true}if(noticePending){const checked=result.items.find(row=>row.id===noticePending);if(checked&&checked.notification_status!=='checking'&&checked.last_check_at){status.textContent='Проверка завершена. Результат указан в строке архива.';noticePending=null}}q('#archive-empty').hidden=!!result.items.length;q('#count').textContent='Всего: '+result.total;q('#previous').disabled=offset===0;q('#next').disabled=offset+20>=result.total;if(active)timer=setTimeout(()=>{if(!document.hidden)void load()},5000)}catch(error){if(token===generation)status.textContent=error.message}}
 q('#archive-student').onchange=()=>{offset=0;status.textContent='';selection();void load()};q('#errors-only').onchange=()=>{offset=0;status.textContent='';void load()};q('#archive-refresh').onclick=()=>{status.textContent='';void load()};q('#previous').onclick=()=>{offset=Math.max(0,offset-20);void load()};q('#next').onclick=()=>{offset+=20;void load()};
 q('#archive-create').onclick=async()=>{const owner=Number(q('#archive-student').value);if(!owner||busy)return;const name=q('#archive-student').selectedOptions[0].textContent;if(!confirm('Подготовить архив: '+name+'? Исходные материалы останутся на сайте.'))return;busy=true;selection();status.textContent='Запускаем создание архива…';try{await request('material-archives','POST',{student_id:owner,include_recent:q('#include-recent').checked});q('#errors-only').checked=false;offset=0;status.textContent='Архив создаётся. Статус обновится автоматически.';await load()}catch(error){status.textContent=error.message}finally{busy=false;selection()}};
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)void load()});window.addEventListener('pagehide',()=>clearTimeout(timer));
 (async()=>{try{const user=await request('auth/me');if(user.role!=='admin'||user.must_change_password)throw Error('Войдите как администратор с постоянным паролем.');window.mountAdminNavigation('archives');let start=0,total=0;const students=[];do{const page=await request('admin/students?limit=100&offset='+start+'&sort=name');students.push(...page.items);total=page.total;start+=100}while(start<total);const picker=q('#archive-student');for(const student of students){const option=el('option',student.name+' ('+student.username+')'+(student.is_active?'':' · В архиве'));option.value=student.id;picker.append(option)}const requested=new URLSearchParams(location.search).get('student_id');if(requested!==null){if(!/^[1-9][0-9]*$/.test(requested)||!students.some(student=>String(student.id)===requested))throw Error('Ученик из ссылки не найден. Откройте раздел через меню.');picker.value=requested}ready=true;selection();q('#archive-content').hidden=false;status.textContent='';await load()}catch(error){status.textContent=error.message}})();
})();
