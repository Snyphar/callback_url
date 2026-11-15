const checkbox = document.getElementById('human-checkbox');
if (checkbox) {
  checkbox.addEventListener('change', () => {
    if (checkbox.checked) {
      document.getElementById('verification-status').textContent = 'Opening login…';
      document.getElementById('verification-form').requestSubmit();
    }
  });
}
