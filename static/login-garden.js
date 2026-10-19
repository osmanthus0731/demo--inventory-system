(() => {
  const cards = [...document.querySelectorAll('.account-card')], body = document.body;
  const layers = [...document.querySelectorAll('.wallpaper-layer')];
  const greeting = document.querySelector('#garden-greeting');
  const imageCache = new Map();
  const flowerBase = document.querySelector('.brand-flower-art use').getAttribute('href').split('#')[0];
  function setBrandFlower(style='cosmos') {document.querySelectorAll('.brand-flower-art use').forEach(use => use.setAttribute('href',flowerBase+'#'+style));}
  const pastels = [['#dbe9ce','#617b50'],['#e7dcf4','#88729b'],['#f7dfbf','#a27a53'],['#d5e7ec','#618996'],['#f0dce5','#a3758b'],['#e1e8c9','#7d8955']];
  let selected, generation = 0, activeLayer = 0, currentWallpaper = '';
  function loadImage(url) {
    if (!imageCache.has(url)) imageCache.set(url,new Promise(resolve => {
      const image = new Image();image.onload = () => resolve(true);image.onerror = () => resolve(false);
      image.referrerPolicy = 'no-referrer';image.src = url;
    }));
    return imageCache.get(url);
  }
  async function wallpaper(url) {
    const version = ++generation;
    if (url === currentWallpaper) return;
    if (!url) {layers.forEach(layer => layer.classList.remove('visible'));currentWallpaper = '';return;}
    const loaded = await loadImage(url);
    if (version !== generation) return;
    if (!loaded) {layers.forEach(layer => layer.classList.remove('visible'));currentWallpaper = '';return;}
    activeLayer = 1 - activeLayer;
    layers[activeLayer].style.backgroundImage = `linear-gradient(#fff6d91a,#303e462b),url(${JSON.stringify(url)})`;
    layers[activeLayer].classList.add('visible');
    layers[1-activeLayer].classList.remove('visible');currentWallpaper = url;
  }
  function preview(card) {
    body.style.setProperty('--garden-accent',card.dataset.highlight);
    body.style.setProperty('--brand-tint',card.dataset.slide);
    body.style.setProperty('--brand-accent',card.dataset.highlight);
    greeting.textContent = `Welcome, ${card.dataset.name}. Make yourself at home.`;
    setBrandFlower(card.dataset.flower || 'cosmos');
    wallpaper(card.dataset.wallpaper || '');
  }
  function restore() {
    // Wait until focus/pointer has reached its next card, avoiding an intermediate reset.
    requestAnimationFrame(() => {
      const hovered = cards.find(card => card.matches(':hover'));
      const focused = cards.find(card => card === document.activeElement);
      if (hovered || focused || selected) preview(hovered || focused || selected);
      else {['--garden-accent','--brand-tint','--brand-accent'].forEach(key => body.style.removeProperty(key));greeting.textContent = 'Pick your little corner of the garden.';setBrandFlower();wallpaper('');}
    });
  }
  cards.forEach(card => {
    if (card.dataset.customAppearance !== '1') {
      const palette = pastels[cards.indexOf(card) % pastels.length];
      card.dataset.slide = palette[0];card.dataset.highlight = palette[1];
    }
    const slide = card.querySelector('.account-slide');
    [0,1,2].forEach(() => {
      const bloom = document.createElement('span');bloom.className = 'slider-flower';const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 100 100');
      const use=document.createElementNS('http://www.w3.org/2000/svg','use');use.setAttribute('href',flowerBase+'#'+(card.dataset.flower || 'cosmos'));svg.append(use);bloom.append(svg);slide.append(bloom);
    });
    const picture = card.dataset.picture;
    if (picture) {
      const image = new Image();image.alt = '';image.width = 36;image.height = 36;
      image.onload = () => card.querySelector('.account-avatar').replaceChildren(image);
      image.src = picture;
    }
    card.style.setProperty('--slide-color',card.dataset.slide);
    card.style.setProperty('--highlight-color',card.dataset.highlight);
    card.addEventListener('pointerenter',() => preview(card));card.addEventListener('pointerleave',restore);
    card.addEventListener('focus',() => preview(card));card.addEventListener('blur',restore);
    card.addEventListener('click',() => {
      selected = card;cards.forEach(other => {other.classList.toggle('selected',other === card);other.setAttribute('aria-pressed',String(other === card));});
      document.querySelector('#selected-user').value = card.dataset.username;
      const pin=document.querySelector('#account-pin');
      if(pin){pin.disabled=false;pin.value='';pin.focus();}
      document.querySelector('.account-login').disabled = Boolean(pin);preview(card);
    });
  });
  const form=document.querySelector('#account-form'),pinInput=document.querySelector('#account-pin');
  if(pinInput)pinInput.addEventListener('input',()=>{pinInput.value=pinInput.value.replace(/\D/g,'').slice(0,8);form.querySelector('.account-login').disabled=!document.querySelector('#selected-user').value||!/^\d{4,8}$/.test(pinInput.value);});
  let signingIn=false;
  if(form)form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(signingIn)return;
    signingIn=true;
    const button=form.querySelector('[type="submit"]');button.disabled=true;
    let error=document.querySelector('#login-session-error');
    if(error)error.remove();
    try{
      // Mobile browsers can restore a form whose token predates the current cookie.
      const response=await fetch('/auth/login-token',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw Error('Unable to refresh your sign-in session. Please try again.');
      const data=await response.json();
      if(typeof data.token!=='string'||!data.token)throw Error('Unable to refresh your sign-in session. Please reload this page.');
      form.elements.platform_csrf.value=data.token;
      HTMLFormElement.prototype.submit.call(form);
    }catch(failure){
      error=document.createElement('p');error.id='login-session-error';error.className='platform-error';error.setAttribute('role','alert');error.textContent=failure.message||'Connection interrupted. Please try again.';form.before(error);
      signingIn=false;button.disabled=!document.querySelector('#selected-user').value;
    }
  });
  window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
  // Warm the image cache without competing with the initial meadow render.
  const preload = () => cards.forEach(card => {if(card.dataset.wallpaper) loadImage(card.dataset.wallpaper);});
  if ('requestIdleCallback' in window) requestIdleCallback(preload);else setTimeout(preload,1000);
})();
