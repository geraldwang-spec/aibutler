(() => {
  const dialog = document.getElementById('calendar-details');
  if (!dialog) return;
  const content = dialog.querySelector('.calendar-detail-content');
  document.querySelectorAll('[data-calendar-details]').forEach(button => {
    button.addEventListener('click', () => {
      const template = document.getElementById(button.dataset.calendarDetails);
      if (!template) return;
      content.replaceChildren(template.content.cloneNode(true));
      dialog.showModal();
    });
  });
  dialog.querySelector('.calendar-detail-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
})();
