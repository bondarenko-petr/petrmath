const menu = document.querySelector('.menu');
const navigation = document.querySelector('#navigation');
function closeMenu() {
  menu.setAttribute('aria-expanded', 'false');
  navigation.classList.remove('open');
}
menu.addEventListener('click', () => {
  const expanded = menu.getAttribute('aria-expanded') !== 'true';
  menu.setAttribute('aria-expanded', String(expanded));
  navigation.classList.toggle('open', expanded);
});
navigation.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMenu();
});
const dialog = document.querySelector('#booking-dialog');
const selectedDirection = dialog.querySelector('.selected-direction');
document.querySelectorAll('.booking').forEach(button => {
  button.addEventListener('click', () => {
    const direction = button.dataset.direction;
    selectedDirection.hidden = !direction;
    selectedDirection.textContent = direction ? `Ваше направление: ${direction}` : '';
    dialog.showModal();
  });
});
dialog.querySelectorAll('.close, .close-dialog').forEach(button => {
  button.addEventListener('click', () => dialog.close());
});
const solutionToggle = document.querySelector('.solution-toggle');
const solution = document.querySelector('#example-solution');
solutionToggle.addEventListener('click', () => {
  const expanded = solutionToggle.getAttribute('aria-expanded') !== 'true';
  solutionToggle.setAttribute('aria-expanded', String(expanded));
  solution.hidden = !expanded;
  solutionToggle.innerHTML = `${expanded ? 'Скрыть решение' : 'Посмотреть решение'} <span aria-hidden="true">${expanded ? '−' : '＋'}</span>`;
});
