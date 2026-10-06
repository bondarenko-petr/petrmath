const menuButton = document.querySelector('.mobile-toggle');
const mobileMenu = document.querySelector('#mobileMenu');
function closeMenu() {
  mobileMenu.hidden = true;
  menuButton.setAttribute('aria-expanded', 'false');
}
menuButton.addEventListener('click', () => {
  mobileMenu.hidden = !mobileMenu.hidden;
  menuButton.setAttribute('aria-expanded', String(!mobileMenu.hidden));
});
mobileMenu.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMenu();
});
const dialog = document.querySelector('#feature-dialog');
document.querySelectorAll('[data-feature]').forEach(link => link.addEventListener('click', event => {
  event.preventDefault();
  document.querySelector('#feature-title').textContent = `${link.dataset.feature}: раздел в разработке`;
  dialog.showModal();
}));
dialog.querySelectorAll('.dialog-close, .dialog-done').forEach(button => button.addEventListener('click', () => dialog.close()));
const requestForm = document.querySelector('#requestForm');
const submitButton = document.querySelector('#request_submit_btn');
const formStatus = document.querySelector('#form-status');
requestForm.addEventListener('submit', async event => {
  event.preventDefault();
  const fields = new FormData(requestForm);
  const courses = fields.getAll('courses');
  if (!courses.length) {
    formStatus.textContent = 'Выберите хотя бы один предмет занятий.';
    return;
  }
  submitButton.disabled = true;
  formStatus.textContent = 'Сохраняем заявку…';
  try {
    const response = await fetch('/api/trial-requests', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: fields.get('name'), email: fields.get('email'),
        phone: fields.get('phone'), message: fields.get('message'), courses,
        consent: fields.get('consent') === 'true'})
    });
    if (!response.ok) throw new Error('request failed');
    requestForm.reset();
    formStatus.textContent = 'Заявка успешно сохранена. Спасибо!';
  } catch (error) {
    formStatus.textContent = 'Не удалось сохранить заявку. Попробуйте ещё раз или свяжитесь с нами по контактам ниже.';
  } finally { submitButton.disabled = false; }
});
const backToTop = document.querySelector('.u-back-to-top');
function scrollToTop() {
  document.querySelector('.u-header').scrollIntoView();
}
backToTop.addEventListener('click', scrollToTop);
backToTop.addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    scrollToTop();
  }
});
