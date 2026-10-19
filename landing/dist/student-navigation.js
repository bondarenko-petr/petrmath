(()=>{
 const sections=[['calendar','Расписание','account.html'],['materials','Задания и конспекты','materials.html'],['balance','Баланс','finance.html']];
 window.setStudentNavActive=active=>document.querySelectorAll('#student-navigation [data-student-nav]').forEach(link=>{if(link.dataset.studentNav===active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current')});
 window.unmountStudentNavigation=()=>{document.querySelector('#student-navigation')?.remove();document.querySelector('#student-logout')?.remove();document.body.classList.remove('student-shell')};
 window.mountStudentNavigation=active=>{
  let nav=document.querySelector('#student-navigation');
  if(!nav){nav=document.createElement('nav');nav.id='student-navigation';nav.className='student-navigation';nav.setAttribute('aria-label','Разделы кабинета ученика');const heading=document.querySelector('#profile-panel .profile-heading');if(heading)heading.after(nav);else document.querySelector('main').prepend(nav)}
  nav.replaceChildren();
  for(const [id,label,href] of sections){const link=document.createElement('a');link.href=href;link.textContent=label;link.dataset.studentNav=id;nav.append(link)}
  const profileButton=document.querySelector('#open-profile');if(profileButton)profileButton.hidden=false;else{const back=document.querySelector('#back');if(back){back.href='account.html?profile=1';back.textContent='Мой профиль';back.classList.add('student-profile-link')}}if(!document.querySelector('#logout')&&!document.querySelector('#student-logout')){const header=document.querySelector('header');if(header){const button=document.createElement('button');button.id='student-logout';button.type='button';button.textContent='Выйти';button.onclick=async()=>{button.disabled=true;try{const response=await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin',headers:{'X-Requested-With':'KrugPi','Content-Type':'application/json'},body:'{}'});if(!response.ok)throw Error('Не удалось выйти. Попробуйте ещё раз.');window.location.assign('account.html')}catch(error){button.disabled=false;const status=document.querySelector('#status');if(status)status.textContent=error.message}};header.append(button)}}document.body.classList.add('student-shell');window.setStudentNavActive(active);
 };
})();
