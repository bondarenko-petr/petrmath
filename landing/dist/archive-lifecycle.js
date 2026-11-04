/* Independent archive, notification and cleanup states; textContent only. */
window.renderArchiveLifecycle=function(row){
 const box=document.createElement('div');box.className='archive-lifecycle';
 if(['deleting','delete_failed','deleted','missing'].includes(row.status)){const p=document.createElement('p');p.textContent={deleting:'Удаляется с Google Диска. Скачивание отключено.',delete_failed:'Удаление требует проверки администратором. Скачивание отключено.',deleted:'Архив удалён. Файлы без исходных копий больше недоступны.',missing:'Архив недоступен на Google Диске. Скачивание отключено.'}[row.status];box.append(p);if(row.zip_deleted_at){const date=document.createElement('p');date.textContent='Удалён: '+new Date(row.zip_deleted_at*1000).toLocaleString('ru-RU');box.append(date)}return box}
 const notification={checking:'Проверка и отправка выполняются',pending:'Ожидает отправки',blocked:'Требуется подтверждённая почта активного ученика',sent:'Письмо передано почтовому серверу',error:'Не удалось проверить или отправить письмо',waiting_archive:'Ожидает проверки архива'};
 const cleanup={completed:'Исходники удалены, архив доступен',disabled:'Выключена',waiting_archive:'Ожидает проверки архива',waiting_notice:'Ожидает уведомления ученика',waiting_period:'Период ожидания',ready:'Срок наступил, ожидает повторных проверок',blocked:'Отложена до устранения причины'};
 const add=(label,value)=>{const p=document.createElement('p');const strong=document.createElement('strong');strong.textContent=label+': ';p.append(strong,document.createTextNode(value));box.append(p)};
 const date=stamp=>new Date(stamp*1000).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'});
 add('Уведомление',notification[row.notification_status]||'Ожидает проверки');
 if(row.notification_status==='sent'&&row.notified_at)add('Передано',date(row.notified_at));
 add('Очистка',cleanup[row.cleanup_status]||'Ожидает проверки');
 if(row.cleanup_not_before&&!['disabled','completed'].includes(row.cleanup_status))add('Не ранее',date(row.cleanup_not_before));
 if(row.cleanup_at)add('Очищено',row.purged_count+' файлов · '+date(row.cleanup_at));
 if(row.cloud_status){add('Автоочистка ZIP',({disabled:'Выключена',waiting_warning:'Ожидает срока предупреждения',warning_sent:'Предупреждение передано почтовому серверу',blocked:'Отложена'})[row.cloud_status]||'Ожидает проверки');if(row.cloud_expires_at)add('Срок хранения ZIP',date(row.cloud_expires_at));if(row.cloud_warning_at)add('Предупреждение передано',date(row.cloud_warning_at));if(row.cloud_delete_not_before)add('Удаление ZIP не ранее',date(row.cloud_delete_not_before));if(row.cloud_issue)add('Причина отсрочки ZIP',row.cloud_issue)}
 for(const [label,error] of [['Ошибка уведомления',row.notification_error],['Причина отсрочки',row.cleanup_issue]]){if(error){const p=document.createElement('p');p.className='archive-failure';p.textContent=label+': '+error;box.append(p)}}
 if(row.last_check_at)add('Последняя проверка',date(row.last_check_at));
 if(row.last_error){const details=document.createElement('details'),summary=document.createElement('summary'),p=document.createElement('p');summary.textContent='Предыдущая попытка'+(row.last_error_at?' · '+date(row.last_error_at):' · дата не сохранена');p.textContent=row.last_error;details.append(summary,p);box.append(details)}
 return box;
};
