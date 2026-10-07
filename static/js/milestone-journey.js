(() => {
  for (const link of document.querySelectorAll('[data-milestone-target]')) {
    link.addEventListener('click', () => {
      const phase = document.getElementById(link.dataset.milestoneTarget);
      if (phase) phase.open = true;
    });
  }
})();
