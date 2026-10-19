(() => {
  // Pixel-based legacy styles need an explicit five-point increase.
  const originals = new Map();
  let applying = false;
  const selectLabels=new WeakMap(),measure=document.createElement('canvas').getContext('2d');
  function showFullSelections(){
    if(!measure)return;
    for(const select of document.querySelectorAll('body.app-shell select')){
      if(select.multiple||select.size>1)continue;
      const text=select.selectedOptions[0]?.textContent||'',style=getComputedStyle(select);
      measure.font=style.font;
      const clipped=select.clientWidth>0&&measure.measureText(text).width>select.clientWidth-44;
      let label=selectLabels.get(select);
      if(!label&&!clipped)continue;
      if(!label){label=document.createElement('small');label.className='full-select-value';label.setAttribute('aria-hidden','true');select.after(label);selectLabels.set(select,label);}
      if(label.textContent!==text)label.textContent=text;
      label.hidden=!clipped;
    }
  }
  document.addEventListener('change',event=>{if(event.target.matches('select'))showFullSelections();});
  window.addEventListener('resize',()=>showFullSelections());
  function resizeText() {
    if (applying) return;
    applying = true;
    for(const element of originals.keys())if(!element.isConnected)originals.delete(element);
    const large = document.documentElement.dataset.textSize === 'large';
    for (const [element, original] of originals) {
      if (element.isConnected) element.style.fontSize = original;
    }
    if (large) {
      const measurements = [...document.querySelectorAll('body.app-shell *')]
        .filter(el => !el.closest('svg, .po-preview, .document-a4') &&
          (el.matches('input,select,textarea,button') || [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())))
        .map(el => [el, parseFloat(getComputedStyle(el).fontSize)]);
      for (const [element, size] of measurements) {
        if (!originals.has(element)) originals.set(element, element.style.fontSize);
        element.style.fontSize = `${size + 20 / 3}px`;
      }
    }
    showFullSelections();
    applying = false;
  }
  new MutationObserver(resizeText).observe(document.documentElement, {attributes:true,attributeFilter:['data-text-size']});
  let timer;
  new MutationObserver(records => {if(!records.some(record=>[...record.addedNodes].some(node=>node.nodeType===1)))return;clearTimeout(timer);timer=setTimeout(resizeText,100);})
    .observe(document.body,{childList:true,subtree:true});
  document.addEventListener('click', event => {
    const link=event.target.closest('a[href]');
    if (!link) return;
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin || !/^\/(item|pricing)\//.test(url.pathname)) return;
    const previous=new URLSearchParams(location.search).get('return_to');
    url.searchParams.set('return_to',previous || location.pathname+location.search);
    link.href=url.href;
  },true);
  resizeText();
})();
