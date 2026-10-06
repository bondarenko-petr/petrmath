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
document.querySelector('#requestForm').addEventListener('submit', event => event.preventDefault());
document.querySelector('#request_submit_btn').addEventListener('click', event => event.preventDefault());
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
