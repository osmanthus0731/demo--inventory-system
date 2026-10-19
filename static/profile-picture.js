(() => {
  const form=document.querySelector('#profile-picture-form');if(!form)return;
  const file=form.elements.profile_picture, panel=document.querySelector('#picture-crop');
  const canvas=document.querySelector('#picture-canvas'), avatar=document.querySelector('#picture-avatar');
  const error=document.querySelector('#picture-error'), save=form.querySelector('button[type=submit]');
  const zoom=form.elements.crop_zoom, x=form.elements.crop_x, y=form.elements.crop_y;
  let image, generation=0, drag;
  function draw() {
    if(!image)return;
    const side=Math.min(image.naturalWidth,image.naturalHeight)/Number(zoom.value);
    const left=(image.naturalWidth-side)*Number(x.value)/100, top=(image.naturalHeight-side)*Number(y.value)/100;
    for(const target of [canvas,avatar]){
      const ctx=target.getContext('2d');ctx.fillStyle='#000';ctx.fillRect(0,0,target.width,target.height);
      ctx.drawImage(image,left,top,side,side,0,0,target.width,target.height);
    }
  }
  function reset(){zoom.value=1;x.value=50;y.value=50;draw();}
  [zoom,x,y].forEach(control=>control.addEventListener('input',draw));
  document.querySelector('#picture-reset').onclick=reset;
  file.addEventListener('change',async()=>{
    const version=++generation,chosen=file.files[0];image=null;panel.hidden=true;error.hidden=true;
    if(!chosen){save.disabled=false;return;}
    save.disabled=true;
    if(chosen.size>2*1024*1024){error.textContent='Choose an image smaller than 2 MB.';error.hidden=false;return;}
    const url=URL.createObjectURL(chosen), next=new Image();
    try {
      next.src=url;await next.decode();
      if(version!==generation)return;
      if(next.naturalWidth*next.naturalHeight>16000000)throw Error('Choose an image up to 16 megapixels.');
      image=next;reset();panel.hidden=false;save.disabled=false;
    } catch(e){if(version===generation){error.textContent=e.message.startsWith('Choose')?e.message:'This picture could not be opened. Try a JPG, PNG, WebP or GIF.';error.hidden=false;}}
    finally{URL.revokeObjectURL(url);}
  });
  canvas.addEventListener('pointerdown',event=>{
    if(!image)return;canvas.setPointerCapture(event.pointerId);
    drag={id:event.pointerId,startX:event.clientX,startY:event.clientY,x:Number(x.value),y:Number(y.value)};
  });
  canvas.addEventListener('pointermove',event=>{
    if(!drag||drag.id!==event.pointerId)return;
    const side=Math.min(image.naturalWidth,image.naturalHeight)/Number(zoom.value), scale=side/canvas.getBoundingClientRect().width;
    const horizontal=image.naturalWidth-side, vertical=image.naturalHeight-side;
    x.value=horizontal?Math.max(0,Math.min(100,drag.x-(event.clientX-drag.startX)*scale/horizontal*100)):50;
    y.value=vertical?Math.max(0,Math.min(100,drag.y-(event.clientY-drag.startY)*scale/vertical*100)):50;draw();
  });
  for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{drag=null;});
})();
