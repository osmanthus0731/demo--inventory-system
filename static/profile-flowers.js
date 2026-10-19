(() => {
  const select=document.querySelector('#flower-style');if(!select)return;
  const preview=document.querySelector('#profile-flower-preview'), form=select.form;
  const base=preview.querySelector('use').getAttribute('href').split('#')[0];
  function render(){preview.querySelector('use').setAttribute('href',base+'#'+select.value);preview.style.color=form.elements.highlight_color.value;}
  select.addEventListener('change',render);form.elements.highlight_color.addEventListener('input',render);
})();
