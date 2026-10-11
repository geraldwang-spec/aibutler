(function () {
  'use strict';

  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  function visualWrapper(input) {
    /* Exam answers use a div wrapper; settings commonly use the label itself. */
    return input.closest('.answer-choice, .choice-card, .task-item') || input.closest('label');
  }

  function syncControl(input) {
    var wrapper = visualWrapper(input);
    if (!wrapper) return;

    wrapper.classList.add('selectable-control');
    wrapper.classList.toggle('is-selected', !!input.checked);
    wrapper.classList.toggle('is-disabled', !!input.disabled);
    wrapper.setAttribute('data-selected', input.checked ? 'true' : 'false');
  }

  function syncRadioGroup(input) {
    if (input.type !== 'radio' || !input.name) {
      syncControl(input);
      return;
    }
    document.querySelectorAll('input[type="radio"]').forEach(function (radio) {
      if (radio.name === input.name) syncControl(radio);
    });
  }

  var choices = Array.prototype.slice.call(
    document.querySelectorAll('input[type="checkbox"], input[type="radio"]')
  );

  choices.forEach(function (input) {
    syncControl(input);

    input.addEventListener('change', function () {
      syncRadioGroup(input);
    });

    input.addEventListener('focus', function () {
      var wrapper = visualWrapper(input);
      if (wrapper) wrapper.classList.add('has-focus');
    });

    input.addEventListener('blur', function () {
      var wrapper = visualWrapper(input);
      if (wrapper) wrapper.classList.remove('has-focus');
    });
  });

  /* Multiple-selects get an explicit count so the state is visible even after focus leaves. */
  document.querySelectorAll('select[multiple]').forEach(function (select) {
    var label = select.closest('label');
    var badge = document.createElement('span');
    badge.className = 'multi-select-count pill';
    badge.style.marginLeft = '8px';
    badge.style.verticalAlign = 'middle';

    function syncMultiSelect() {
      var count = Array.prototype.filter.call(select.options, function (option) {
        return option.selected;
      }).length;
      badge.textContent = count ? ('已選 ' + count + ' 項') : '尚未選擇';
      badge.style.background = count ? '#e8f7f6' : '#eef2f2';
      badge.style.color = count ? '#176d74' : '#68777b';
    }

    if (label) {
      var firstText = label.childNodes[0];
      if (firstText && firstText.nodeType === Node.TEXT_NODE) {
        label.insertBefore(badge, select);
      } else {
        label.insertBefore(badge, select);
      }
    }

    syncMultiSelect();
    select.addEventListener('change', syncMultiSelect);
  });
})();
