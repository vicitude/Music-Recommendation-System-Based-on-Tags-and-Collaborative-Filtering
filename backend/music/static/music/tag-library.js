document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('tag-library-form')
  const select = document.getElementById('select-missing-tags')
  const clear = document.getElementById('clear-tag-selection')
  const setSelection = (checked) => {
    form.querySelectorAll('input[name="selected"]:not(:disabled)').forEach((option) => {
      option.checked = checked
    })
  }
  if (form && select && clear) {
    select.addEventListener('click', () => setSelection(true))
    clear.addEventListener('click', () => setSelection(false))
  }
})
