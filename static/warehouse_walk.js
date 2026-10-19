(() => {
  const dialog=document.querySelector('#warehouse-walk');if(!dialog)return;
  const canvas=document.querySelector('#walk-canvas'),ctx=canvas.getContext('2d');
  let depthRenderer=null;try{depthRenderer=new window.WarehouseDepthRenderer();}catch(error){console.warn('Depth rendering unavailable:',error.message);}
  const menu=document.querySelector('#walk-destination'),hud=document.querySelector('#walk-hud'),selection=document.querySelector('#walk-selection');
  const search=document.querySelector('#walk-search'),cameraMenu=document.querySelector('#walk-camera');
  const settings=document.querySelector('#walk-settings'),hoverLabel=document.querySelector('#walk-hover-rack');
  let hoveredRack=null,pointerAim=null,lastHoverPick=0;
  function showHoveredRack(rack){if(hoveredRack===rack)return;hoveredRack=rack;dialog.dataset.hoveredRack=rack||'';hoverLabel.hidden=!rack;hoverLabel.textContent=rack?'Rack '+rack+' - Click for items':'';}
  const popup=document.querySelector('#walk-popup'),popupContent=document.querySelector('#walk-popup-content'),quickSearch=document.querySelector('#walk-quick-search');
  function stopGuide(){route=[];thirdPerson=false;cameraMenu.value='first';}
  function releaseMouse(){keys.clear();momentum.x=momentum.y=0;if(document.pointerLockElement===canvas)document.exitPointerLock();}
  function openPopup(title,searching=false){showHoveredRack(null);controlMode='popup';dialog.dataset.mode='popup';releaseMouse();document.querySelector('#walk-popup-title').textContent=title;document.querySelector('#walk-quick-label').hidden=!searching;popupContent.replaceChildren();popup.showModal();if(searching){quickSearch.value='';fillQuickResults();quickSearch.focus();}}
  function closePopup(){popup.close();controlMode='explore';canvas.focus({preventScroll:true});if(!phone())captureMouse();}
  document.querySelector('#walk-popup-close').onclick=closePopup;
  popup.addEventListener('cancel',event=>{event.preventDefault();event.stopPropagation();closePopup();});
  popup.addEventListener('keydown',event=>event.stopPropagation());
  let backdropPress=false;
  const outsidePopup=event=>{const bounds=popup.getBoundingClientRect();return event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom;};
  popup.addEventListener('pointerdown',event=>{backdropPress=event.target===popup&&outsidePopup(event);});
  popup.addEventListener('click',event=>{if(backdropPress&&event.target===popup&&outsidePopup(event)){event.preventDefault();event.stopPropagation();closePopup();}backdropPress=false;});
  function rackPopup(rack){choose(rack);openPopup('Rack '+rack);const products=data.products.filter(p=>p.locations.some(l=>code(l.area)===rack));
    for(const product of products){const item=document.createElement('div');item.className='walk-popup-item';const title=document.createElement('strong');title.textContent=product.name||product.uid;title.tabIndex=0;title.setAttribute('role','button');title.style.cursor='pointer';title.onclick=()=>productCard(product);title.onkeydown=e=>{if(e.key==='Enter')productCard(product);};const details=document.createElement('p');details.textContent=product.uid+' · '+product.locations.filter(l=>code(l.area)===rack).map(l=>l.area+': '+(l.quantity??'Unknown')+' units').join(' · ');item.append(title,details);popupContent.append(item);}
    if(!products.length)popupContent.textContent='No products assigned to this rack.';
  }
  function productCard(product){
    popupContent.replaceChildren();document.querySelector('#walk-quick-label').hidden=true;document.querySelector('#walk-popup-title').textContent=product.name||product.uid;
    const racks=[...new Set(product.locations.map(location=>code(location.area)))].filter(rack=>data.layout.regions.some(region=>region.code===rack));
    for(const rack of racks){
      const guide=document.createElement('button');guide.type='button';guide.className='btn';guide.textContent=racks.length===1?'Auto direct':'Auto direct to '+rack;
      guide.onclick=()=>{choose(rack);closePopup();plan();};popupContent.append(guide);
    }
    if(!racks.length){const message=document.createElement('p');message.textContent='No mapped rack location available for auto direct.';popupContent.append(message);}
    const frame=document.createElement('iframe');frame.src='/item/'+encodeURIComponent(product.uid)+'?embedded=1';frame.title='Product details';frame.style.cssText='width:100%;height:55dvh;border:0;margin-top:12px';popupContent.append(frame);
  }
  function openQuickSearch(){if(!data||popup.open)return;openPopup('Find stock',true);}
  function fillQuickResults(){
    const words=quickSearch.value.trim().toLowerCase().split(/\s+/);popupContent.replaceChildren();
    const matches=[];
    for(const product of data.products){
      const label=[product.name,product.uid,...product.locations.map(l=>l.area)].join(' ');
      if(words.every(word=>label.toLowerCase().includes(word))){
        const racks=[...new Set(product.locations.map(l=>code(l.area)))].filter(rack=>data.layout.regions.some(r=>r.code===rack));
        matches.push({label:(product.name||product.uid)+' ? '+product.uid,product,racks});
      }
    }
    for(const r of data.layout.regions)if(!matches.some(m=>!m.product&&m.racks[0]===r.code)&&words.every(word=>(r.label+' '+r.code).toLowerCase().includes(word)))matches.push({label:r.label,racks:[r.code]});
    for(const result of matches.slice(0,30)){
      const row=document.createElement('div');row.className='walk-popup-item';const label=document.createElement('strong');label.textContent=result.label;row.append(label,document.createElement('br'));
      if(result.product){const details=document.createElement('button');details.type='button';details.className='btn btn-secondary';details.textContent='Product details';details.onclick=()=>productCard(result.product);row.append(details);}
      for(const rack of result.racks){const button=document.createElement('button');button.type='button';button.className='btn';button.textContent='Auto-guide to '+rack;button.onclick=()=>{choose(rack);closePopup();plan();};row.append(button);}
      if(!result.racks.length)row.append(document.createTextNode('No mapped rack location.'));
      popupContent.append(row);
    }
    if(!matches.length)popupContent.textContent='No matching products or racks.';
  }
  quickSearch.oninput=fillQuickResults;document.querySelector('#walk-quick-open').onclick=openQuickSearch;
  const phone=()=>matchMedia('(pointer:coarse), (max-width:950px)').matches;

  let touchLook=null,ignoreMouseUntil=0,ownFullscreen=false;
  let followDistance=105;
  let thirdPerson=false,controlMode='cursor',targetYaw=Math.PI,targetPitch=0,worldFaces=[],solids=[],frameWorld=[],building=false,cameraOrigin={x:0,y:0,z:42},options=[];
  const momentum={x:0,y:0};let grounded=true,hops=0;
  const keys=new Set();let data,position={x:0,y:0,z:0},yaw=Math.PI,pitch=0,velocity=0,last=0,frame=0,route=[],destination='',faces=[],hits=[],generation=0;
  const code=value=>{const match=String(value||'').trim().toUpperCase().match(/^([A-Z]+)\s*0*(\d+)(?=$|[^0-9])/);return match?match[1]+Number(match[2]):String(value||'').toUpperCase().replace(/[^A-Z0-9]/g,'');};
  const totals=()=>{const sums=new Map();for(const p of data.products)for(const l of p.locations){const n=Number(l.quantity);if(Number.isFinite(n)&&n>0)sums.set(code(l.area),(sums.get(code(l.area))||0)+n);}return sums;};
  function clear(x,y,padding=9){return x>padding&&y>padding&&x<data.layout.width-padding&&y<data.layout.depth-padding&&!(data.layout.walls||[]).some(r=>x>r.x-padding&&x<r.x+r.width+padding&&y>r.y-padding&&y<r.y+r.depth+padding)&&!solids.some(s=>s.z<44&&s.z+s.height>0&&x>s.x-padding&&x<s.x+s.width+padding&&y>s.y-padding&&y<s.y+s.depth+padding)&&!data.layout.regions.some(r=>r.code!=='G8'&&x>r.x-padding&&x<r.x+r.width+padding&&y>r.y-padding&&y<r.y+r.depth+padding);}
  function reset(){route=[];keys.clear();velocity=0;momentum.x=momentum.y=0;grounded=true;hops=0;position={x:data.layout.entrance?.x||45,y:data.layout.entrance?.y||data.layout.depth-45,z:0};yaw=targetYaw=Math.atan2(data.layout.width/2-position.x,data.layout.depth/2-position.y);pitch=targetPitch=0;stopGuide();
    if(!clear(position.x,position.y))for(let y=data.layout.depth-20;y>10;y-=20){let found=false;for(let x=20;x<data.layout.width;x+=20)if(clear(x,y)){position.x=x;position.y=y;found=true;break;}if(found)break;}
    canvas.focus({preventScroll:true});}
  function camera(point){const dx=point[0]-cameraOrigin.x,dy=point[1]-cameraOrigin.y,vertical=point[2]-cameraOrigin.z,forward=dx*Math.sin(yaw)+dy*Math.cos(yaw);return {x:-dx*Math.cos(yaw)+dy*Math.sin(yaw),y:vertical*Math.cos(pitch)-forward*Math.sin(pitch),z:vertical*Math.sin(pitch)+forward*Math.cos(pitch)};}
  function screen(p){const scale=canvas.width*(thirdPerson?.5:.62);return [canvas.width/2+p.x/p.z*scale,canvas.height*(thirdPerson?.35:.53)-p.y/p.z*scale];}
  function clipped(points){const result=[];for(let i=0;i<points.length;i++){const a=points[i],b=points[(i+1)%points.length];if(a.z>=3)result.push(a);if((a.z>=3)!==(b.z>=3)){const t=(3-a.z)/(b.z-a.z);result.push({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z:3});}}return result;}
  function face(points,color,rack,parcel=false){if(building){worldFaces.push({points,color,rack,parcel});return;}if(depthRenderer){frameWorld.push({points,color,rack,parcel});return;}const transformed=clipped(points.map(camera));if(transformed.length<3)return;const projected=transformed.map(screen);if(projected.every(p=>p[0]<0)||projected.every(p=>p[0]>canvas.width)||projected.every(p=>p[1]<0)||projected.every(p=>p[1]>canvas.height))return;faces.push({points:projected,depth:transformed.reduce((s,p)=>s+p.z,0)/transformed.length,color,rack,parcel});}
  function box(x,y,w,d,z,h,color,rack,parcel=false){if(building)solids.push({x,y,width:w,depth:d,z,height:h});const p=[[x,y,z],[x+w,y,z],[x+w,y+d,z],[x,y+d,z],[x,y,z+h],[x+w,y,z+h],[x+w,y+d,z+h],[x,y+d,z+h]];
    for(const [indices,fill] of [[[0,3,2,1],color[1]],[[0,1,5,4],color[0]],[[1,2,6,5],color[1]],[[2,3,7,6],color[0]],[[3,0,4,7],color[1]],[[4,5,6,7],color[2]]])face(indices.map(i=>p[i]),fill,rack,parcel);}
  function line3(a,b,color,width=1){const aa=camera(a),bb=camera(b);if(aa.z<3||bb.z<3)return;const p=screen(aa),q=screen(bb);ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
  function updateCamera(){
    let distance=thirdPerson?105:0;
    // Test the follow camera at eye height, rather than against whole rack footprints.
    if(thirdPerson)for(let d=10;d<=105;d+=5){const x=position.x-Math.sin(yaw)*d,y=position.y-Math.cos(yaw)*d,z=position.z+65;
      if(x<3||y<3||x>data.layout.width-3||y>data.layout.depth-3||solids.some(s=>x>s.x-3&&x<s.x+s.width+3&&y>s.y-3&&y<s.y+s.depth+3&&z>s.z-3&&z<s.z+s.height+3)){distance=Math.max(8,d-5);break;}}
    followDistance=distance<followDistance?distance:followDistance+(distance-followDistance)*.12;
    if(thirdPerson)distance=followDistance;
    cameraOrigin={x:position.x-Math.sin(yaw)*distance,y:position.y-Math.cos(yaw)*distance,z:position.z+(thirdPerson?65:42)};
  }
  function minimap(){
    const w=Math.min(190,canvas.width*.24),h=w*data.layout.depth/data.layout.width,ox=canvas.width-w-14,oy=14,scale=w/data.layout.width;
    ctx.fillStyle='#f5faf0ee';ctx.fillRect(ox,oy,w,h);ctx.strokeStyle='#82998c';ctx.strokeRect(ox,oy,w,h);
    for(const p of data.layout.platforms||[]){ctx.fillStyle='#bdd9ed88';ctx.fillRect(ox+p.x*scale,oy+p.y*scale,p.width*scale,p.depth*scale);}
    for(const wall of data.layout.walls||[]){ctx.fillStyle='#687485';ctx.fillRect(ox+wall.x*scale,oy+wall.y*scale,Math.max(2,wall.width*scale),wall.depth*scale);}
    for(const r of data.layout.regions){ctx.fillStyle=r.code===destination?'#bc9750':'#92b2a0';ctx.fillRect(ox+r.x*scale,oy+r.y*scale,r.width*scale,r.depth*scale);}
    if(route.length){ctx.beginPath();ctx.moveTo(ox+position.x*scale,oy+position.y*scale);for(const p of route)ctx.lineTo(ox+p.x*scale,oy+p.y*scale);ctx.strokeStyle='#7e63be';ctx.lineWidth=3;ctx.stroke();}
    const px=ox+position.x*scale,py=oy+position.y*scale,fx=Math.sin(yaw),fy=Math.cos(yaw),rx=-Math.cos(yaw),ry=Math.sin(yaw);
    ctx.fillStyle='#365f9030';ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px+fx*25+rx*14,py+fy*25+ry*14);ctx.lineTo(px+fx*25-rx*14,py+fy*25-ry*14);ctx.closePath();ctx.fill();
    ctx.fillStyle='#365f90';ctx.beginPath();ctx.moveTo(px+fx*12,py+fy*12);ctx.lineTo(px-fx*3+rx*5,py-fy*3+ry*5);ctx.lineTo(px-fx*3-rx*5,py-fy*3-ry*5);ctx.closePath();ctx.fill();
    ctx.fillStyle='#365f90';ctx.beginPath();ctx.arc(ox+position.x*scale,oy+position.y*scale,4,0,Math.PI*2);ctx.fill();ctx.font='bold 10px Arial';ctx.textAlign='left';ctx.fillText('YOU',ox+position.x*scale+6,oy+position.y*scale-5);
  }
  function buildGeometry(){worldFaces=[];solids=[];building=true;
    const stock=totals();
    for(const p of data.layout.platforms||[]){box(p.x,p.y,p.width,p.depth,p.elevation,p.thickness,['#587a94','#7197ad','#bed5df'],null);for(const [x,y] of [[p.x,p.y],[p.x+p.width-4,p.y],[p.x,p.y+p.depth-4],[p.x+p.width-4,p.y+p.depth-4]])box(x,y,4,4,0,p.elevation,['#657b8b','#8195a4','#b8c6d1'],null);}
    for(const w of data.layout.walls||[])box(w.x,w.y,w.width,w.depth,0,w.height,['#77848e','#65737d','#a8b4bd'],null);
    for(const door of data.layout.doorways||[]){
      const post=door.post_width||4,clearance=door.clearance||84,height=door.height||105,colors=['#77848e','#65737d','#a8b4bd'];
      box(door.x,door.y-post,door.width,post,0,height,colors,null);
      box(door.x,door.y+door.depth,door.width,post,0,height,colors,null);
      box(door.x,door.y,door.width,door.depth,clearance,height-clearance,colors,null);
    }
    for(const r of data.layout.regions){const active=r.code===destination,colors=active?['#6689a5','#51738e','#bbd7df']:['#608777','#456b5d','#a2c1a7'];
      if(r.code==='G8'){if(!(data.layout.platforms||[]).length)box(r.x-20,r.y-20,r.width+40,r.depth+40,115,5,colors,r.code);for(const [x,y] of [[r.x,r.y],[r.x+r.width-3,r.y],[r.x,r.y+r.depth-3],[r.x+r.width-3,r.y+r.depth-3]])box(x,y,3,3,0,115,colors,r.code);}
      const elevation=r.code==='G8'?120:0;
      if(r.kind==='room'){box(r.x,r.y,r.width,r.depth,0,25,colors,r.code);continue;}
      for(let level=0;level<3;level++)box(r.x,r.y,r.width,r.depth,elevation+level*22+3,3,colors,r.code);
      for(const [x,y] of [[r.x,r.y],[r.x+r.width-3,r.y],[r.x,r.y+r.depth-3],[r.x+r.width-3,r.y+r.depth-3]])box(x,y,3,3,elevation,70,colors,r.code);
      const along=r.width>=r.depth,count=Math.max(1,Math.min(9,Math.floor((along?r.width:r.depth)/28)));
      const siblings=data.layout.regions.filter(other=>other.code===r.code),all=Math.ceil((stock.get(r.code)||0)/1000),allocated=Math.floor(all/siblings.length)+(siblings.indexOf(r)<all%siblings.length?1:0);
      for(let i=0;i<Math.min(allocated,count*6);i++){const slot=i%count,level=Math.floor(i/count),x=r.x+(along?slot*r.width/count+3:3),y=r.y+(along?3:slot*r.depth/count+3),w=along?r.width/count-6:r.width-6,d=along?r.depth-6:r.depth/count-6,z=level<3?level*22+6:64+(level-3)*14;box(x,y,Math.max(4,w),Math.max(4,d),elevation+z,14,['#b79461','#c9aa78','#eddbad'],r.code,true);}
    }
    building=false;
  }
  function render(){
    updateCamera();
    const width=Math.round(Math.min(canvas.clientWidth,1100)),height=Math.round(canvas.clientHeight*Math.min(1,1100/canvas.clientWidth));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
    const horizon=canvas.height*(thirdPerson?.35:.53)+Math.tan(pitch)*canvas.width*(thirdPerson?.5:.62),sky=ctx.createLinearGradient(0,0,0,canvas.height);sky.addColorStop(0,'#c2dce4');sky.addColorStop(.6,'#eef4e8');sky.addColorStop(1,'#a9baad');ctx.fillStyle=sky;ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#dbe2d9';ctx.fillRect(0,Math.max(0,horizon),canvas.width,canvas.height);
    for(let x=0;x<=data.layout.width;x+=40)line3([x,0,0],[x,data.layout.depth,0],'#b9c9bd');for(let y=0;y<=data.layout.depth;y+=40)line3([0,y,0],[data.layout.width,y,0],'#b9c9bd');
    faces=[];hits=[];frameWorld=[];for(const f of worldFaces)face(f.points,f.color,f.rack,f.parcel);
    if(thirdPerson){
      const z=position.z,c=['#527497','#416080','#91bad0'];
      box(position.x-7,position.y-5,14,10,z+15,18,c,'__player');
      box(position.x-5,position.y-5,10,10,z+34,10,['#d7b494','#c19c7d','#efd2b0'],'__player');
      box(position.x-6,position.y-4,4,8,z,15,c,'__player');box(position.x+2,position.y-4,4,8,z,15,c,'__player');
    }
    if(depthRenderer){try{
      const surface=depthRenderer.draw(frameWorld,camera,canvas.width,canvas.height,thirdPerson,0);
      if(controlMode==='popup'){showHoveredRack(null);depthRenderer.highlighted=null;}else if(performance.now()-lastHoverPick>120){
        lastHoverPick=performance.now();const aim=controlMode==='explore'?{x:canvas.width/2,y:canvas.height/2}:pointerAim;
        showHoveredRack(aim?depthRenderer.pick(aim.x,aim.y,true):null);
        if(!aim)depthRenderer.highlighted=null;
      }
      ctx.drawImage(surface,0,0);dialog.dataset.renderer='webgl-depth';}catch(error){depthRenderer=null;document.querySelector('#walk-mouse-help').textContent=error.message;}}
    faces.sort((a,b)=>b.depth-a.depth);
    for(const f of faces){ctx.beginPath();f.points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.globalAlpha=f.parcel?.2:1;ctx.fillStyle=f.color;ctx.fill();ctx.strokeStyle='#344c4350';ctx.lineWidth=.7;ctx.stroke();ctx.globalAlpha=1;if(f.rack&&f.rack!=='__player')hits.push(f);}
    if(!depthRenderer&&performance.now()-lastHoverPick>120){lastHoverPick=performance.now();const aim=controlMode==='explore'?{x:canvas.width/2,y:canvas.height/2}:pointerAim;showHoveredRack(controlMode!=='popup'&&aim?rackAt(aim.x,aim.y):null);}
    // Direction beacons stay readable even when the chosen rack is behind you.
    if(destination){const r=data.layout.regions.find(r=>r.code===destination),dx=r.x+r.width/2-position.x,dy=r.y+r.depth/2-position.y,distance=Math.hypot(dx,dy),relative=Math.atan2(Math.sin(Math.atan2(dx,dy)-yaw),Math.cos(Math.atan2(dx,dy)-yaw));
      const arrow=Math.abs(relative)<.18?'↑':relative<0?'→':'←';hud.textContent=`${arrow} ${destination} · ${Math.round(distance)} map units${route.length?' · Auto-guide active':''}${destination==='G8'?' · Level 2: guide stops at ground-floor approach':''}`;
      const beacon=camera([r.x+r.width/2,r.y+r.depth/2,88]);if(beacon.z>3){const [x,y]=screen(beacon);ctx.font='bold 17px Arial';ctx.textAlign='center';const textWidth=ctx.measureText(destination).width;ctx.fillStyle='#284b40ee';ctx.fillRect(x-textWidth/2-10,y-23,textWidth+20,30);ctx.fillStyle='#fff';ctx.fillText(destination,x,y-2);}
    }
    minimap();dialog.dataset.hops=String(hops);dialog.dataset.speed=Math.hypot(momentum.x,momentum.y).toFixed(2);dialog.dataset.grounded=String(grounded);dialog.dataset.sprinting=String(keys.has('shift'));dialog.dataset.mode=controlMode;dialog.dataset.yaw=yaw.toFixed(4);dialog.dataset.pitch=pitch.toFixed(4);dialog.dataset.camera=thirdPerson?'third':'first';
    dialog.dataset.x=position.x.toFixed(2);dialog.dataset.y=position.y.toFixed(2);dialog.dataset.height=position.z.toFixed(2);dialog.dataset.guiding=String(route.length>0);
  }
  function choose(value){stopGuide();destination=value;menu.value=value;buildGeometry();const stock=totals().get(value)||0;const products=data.products.filter(p=>p.locations.some(l=>code(l.area)===value));selection.textContent=`${value}: ${stock.toLocaleString()} known units · ${products.map(p=>p.name).join(', ')||'No product assigned'}. Click another parcel or choose a destination.`;document.querySelector('#store-map').dispatchEvent(new CustomEvent('walk-select',{detail:{code:value}}));}
  function plan(){
    if(!destination){hud.textContent='Choose a rack or product first.';return;}
    const path=WarehouseNavigation.find(data.layout,position,destination,(x,y)=>clear(x,y));
    if(!path.length){hud.textContent='No clear aisle route found. Try resetting position or exploring manually.';return;}
    route=path.slice(1);momentum.x=momentum.y=0;thirdPerson=true;cameraMenu.value='third';controlMode='explore';if(phone())settings.open=false;canvas.focus({preventScroll:true});
  }
  const bodyHeight=44,bodyRadius=7;
  function overlaps(solid,x=position.x,y=position.y){return x>solid.x-bodyRadius&&x<solid.x+solid.width+bodyRadius&&y>solid.y-bodyRadius&&y<solid.y+solid.depth+bodyRadius;}
  function canOccupy(x,y){return x>bodyRadius&&y>bodyRadius&&x<data.layout.width-bodyRadius&&y<data.layout.depth-bodyRadius&&!solids.some(solid=>overlaps(solid,x,y)&&position.z<solid.z+solid.height-.05&&position.z+bodyHeight>solid.z+.05);}
  function move(dx,dy){
    // Swept substeps keep sprinting and wheel movement from tunnelling through posts.
    const count=Math.max(1,Math.ceil(Math.max(Math.abs(dx),Math.abs(dy))/3));
    for(let i=0;i<count;i++){
      if(canOccupy(position.x+dx/count,position.y))position.x+=dx/count;else momentum.x=0;
      if(canOccupy(position.x,position.y+dy/count))position.y+=dy/count;else momentum.y=0;
    }
  }
  function jump(){
    if(!grounded)return;grounded=false;velocity=110;hops++;
    const speed=Math.hypot(momentum.x,momentum.y);
    if(speed>50){const boost=Math.min(260,speed*1.04)/speed;momentum.x*=boost;momentum.y*=boost;}
  }
  function physicsStep(dt,manual){
    if(manual){
      if(grounded&&keys.has(' '))jump();
      const forward=(keys.has('w')?1:0)-(keys.has('s')?1:0),side=(keys.has('d')?1:0)-(keys.has('a')?1:0),length=Math.hypot(forward,side),speed=keys.has('shift')?185:100;
      if(length){
        const wx=(Math.sin(yaw)*forward-Math.cos(yaw)*side)/length,wy=(Math.cos(yaw)*forward+Math.sin(yaw)*side)/length;
        if(grounded){const gain=1-Math.exp(-8*dt);momentum.x+=(wx*speed-momentum.x)*gain;momentum.y+=(wy*speed-momentum.y)*gain;}
        else{const along=momentum.x*wx+momentum.y*wy,addition=Math.max(0,Math.min(speed-along,190*dt));momentum.x+=wx*addition;momentum.y+=wy*addition;}
      }else if(grounded){const friction=Math.exp(-7*dt);momentum.x*=friction;momentum.y*=friction;}
      const current=Math.hypot(momentum.x,momentum.y);if(current>260){momentum.x*=260/current;momentum.y*=260/current;}
      move(momentum.x*dt,momentum.y*dt);
    }
    const before=position.z;velocity-=300*dt;let next=before+velocity*dt;grounded=false;
    if(velocity<=0){
      let floor=0;for(const solid of solids){const top=solid.z+solid.height;if(overlaps(solid)&&top<=before+.05&&top>=next&&top>floor)floor=top;}
      if(next<=floor){next=floor;velocity=0;grounded=true;}
    }else{
      for(const solid of solids)if(overlaps(solid)&&solid.z>=before+bodyHeight-.05&&solid.z<next+bodyHeight){next=solid.z-bodyHeight;velocity=0;}
    }
    position.z=Math.max(0,next);
  }
  function tick(time){if(!dialog.open)return;const dt=Math.min((time-last)/1000||0,.04);last=time;
    if(!document.hidden&&controlMode!=='popup'){if(route.length){
      let remaining=135*dt;
      while(route.length&&remaining>0){const next=route[0],dx=next.x-position.x,dy=next.y-position.y,distance=Math.hypot(dx,dy);if(distance<.1){route.shift();continue;}const travel=Math.min(distance,remaining);move(dx/distance*travel,dy/distance*travel);remaining-=travel;if(Math.hypot(next.x-position.x,next.y-position.y)<.1)route.shift();else if(travel>=distance-.01){route=[];hud.textContent='Route blocked. Choose Auto-guide to recalculate.';break;}}
      if(route.length){let look={x:position.x,y:position.y},ahead=55;for(const point of route){const distance=Math.hypot(point.x-look.x,point.y-look.y);if(distance>=ahead){const fraction=ahead/distance;look={x:look.x+(point.x-look.x)*fraction,y:look.y+(point.y-look.y)*fraction};break;}ahead-=distance;look=point;}targetYaw=Math.atan2(look.x-position.x,look.y-position.y);}
      else if(destination){const r=data.layout.regions.find(r=>r.code===destination);targetYaw=Math.atan2(r.x+r.width/2-position.x,r.y+r.depth/2-position.y);selection.textContent=`Arrived at ${destination}. Click a parcel to inspect its rack.`;}
    }
      if(keys.has('arrowleft'))targetYaw+=dt*1.15;if(keys.has('arrowright'))targetYaw-=dt*1.15;
      if(keys.has('arrowup'))targetPitch=Math.min(1.15,targetPitch+dt);if(keys.has('arrowdown'))targetPitch=Math.max(-1.15,targetPitch-dt);
      const cameraEase=1-Math.exp(-8*dt);yaw+=Math.atan2(Math.sin(targetYaw-yaw),Math.cos(targetYaw-yaw))*cameraEase;pitch+=(targetPitch-pitch)*cameraEase;
      const steps=Math.max(1,Math.ceil(dt/(1/120)));for(let step=0;step<steps;step++)physicsStep(dt/steps,controlMode==='explore'&&!route.length);
      render();}
    frame=requestAnimationFrame(tick);
  }
  dialog.addEventListener('keydown',event=>{if(event.target.matches('input,select,button'))return;const key=event.key.toLowerCase();if(key==='q'){event.preventDefault();openQuickSearch();return;}if(key==='escape'){event.preventDefault();controlMode='cursor';releaseMouse();return;}if(['w','a','s','d','arrowleft','arrowright','arrowup','arrowdown',' ','shift'].includes(key)){event.preventDefault();if(controlMode!=='explore'&&!phone())return;stopGuide();keys.add(key);if(key===' '&&!event.repeat)jump();}});
  window.addEventListener('keyup',e=>keys.delete(e.key.toLowerCase()));window.addEventListener('blur',()=>{keys.clear();momentum.x=momentum.y=0;route=[];});
  function rackAt(x,y){if(depthRenderer)return depthRenderer.pick(x,y);for(let i=hits.length-1;i>=0;i--){const face=hits[i],path=new Path2D();face.points.forEach((p,index)=>index?path.lineTo(...p):path.moveTo(...p));path.closePath();if(ctx.isPointInPath(path,x,y))return face.rack;}return null;}
  function inspect(x,y){const rack=rackAt(x,y);if(rack)rackPopup(rack);}
  let lockingMouse=false;
  function mouseStatus(locked){
    document.querySelector('#walk-mouse-help').textContent=locked?'Mouse locked. Move to look up/down, WASD to walk. Aim at a rack for its name; click for items. Q searches, Esc releases the cursor.':'Click inside the simulator or Play to lock the mouse. Esc releases it.';
    dialog.dataset.mouseLocked=String(locked);
  }
  async function captureMouse(){
    if(!dialog.open||popup.open||!data||lockingMouse)return;
    if(document.pointerLockElement===canvas){controlMode='explore';return;}
    if(!canvas.requestPointerLock){controlMode='cursor';mouseStatus(false);document.querySelector('#walk-mouse-help').textContent='Mouse lock is unavailable in this browser. Use the arrow keys or touch controls.';return;}
    lockingMouse=true;canvas.focus({preventScroll:true});
    try{await canvas.requestPointerLock();}catch(_){controlMode='cursor';mouseStatus(false);document.querySelector('#walk-mouse-help').textContent='Mouse lock was blocked. Click inside the simulator to try again; press Esc to release it.';}
    finally{lockingMouse=false;}
  }
  document.querySelector('#walk-mouselook').onclick=captureMouse;
  document.addEventListener('mousemove',event=>{if(!dialog.open||!data||route.length||controlMode!=='explore'||performance.now()<ignoreMouseUntil||event.sourceCapabilities?.firesTouchEvents)return;if(document.pointerLockElement===canvas){targetYaw-=Math.max(-120,Math.min(120,event.movementX))*.0015;targetPitch=Math.max(-1.15,Math.min(1.15,targetPitch-event.movementY*.0015));}});
  canvas.addEventListener('pointermove',event=>{if(event.pointerType==='mouse'){const rect=canvas.getBoundingClientRect();pointerAim={x:(event.clientX-rect.left)*canvas.width/rect.width,y:(event.clientY-rect.top)*canvas.height/rect.height};}});
  canvas.addEventListener('pointerleave',()=>{pointerAim=null;if(document.pointerLockElement!==canvas){showHoveredRack(null);if(depthRenderer)depthRenderer.highlighted=null;}});
  canvas.addEventListener('click',event=>{if(performance.now()<ignoreMouseUntil)return;canvas.focus({preventScroll:true});if(document.pointerLockElement===canvas)inspect(canvas.width/2,canvas.height*.5);else captureMouse();});
  canvas.addEventListener('pointerdown',event=>{if(event.pointerType==='mouse'||!data)return;event.preventDefault();canvas.setPointerCapture(event.pointerId);touchLook={id:event.pointerId,x:event.clientX,y:event.clientY,startX:event.clientX,startY:event.clientY,moved:false};ignoreMouseUntil=performance.now()+800;});
  canvas.addEventListener('pointermove',event=>{if(!touchLook||touchLook.id!==event.pointerId)return;event.preventDefault();const dx=event.clientX-touchLook.x,dy=event.clientY-touchLook.y;if(Math.hypot(event.clientX-touchLook.startX,event.clientY-touchLook.startY)>7)touchLook.moved=true;if(touchLook.moved){stopGuide();targetYaw-=dx*.003;targetPitch=Math.max(-1.15,Math.min(1.15,targetPitch-dy*.003));}touchLook.x=event.clientX;touchLook.y=event.clientY;ignoreMouseUntil=performance.now()+800;});
  canvas.addEventListener('pointerup',event=>{if(!touchLook||touchLook.id!==event.pointerId)return;if(!touchLook.moved){const rect=canvas.getBoundingClientRect();inspect((event.clientX-rect.left)*canvas.width/rect.width,(event.clientY-rect.top)*canvas.height/rect.height);}touchLook=null;ignoreMouseUntil=performance.now()+800;});
  // Suppress compatibility taps after a look gesture; controls handle their own touches.
  for(const name of ['touchstart','touchmove','touchend'])canvas.addEventListener(name,event=>event.preventDefault(),{passive:false});
  document.querySelector('#walk-close').addEventListener('pointerup',event=>{if(event.pointerType!=='mouse')dialog.close();});
  for(const name of ['pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{touchLook=null;});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){keys.clear();route=[];touchLook=null;}});
  document.querySelector('#walk-fullscreen').onclick=async()=>{try{if(!document.fullscreenElement){await document.documentElement.requestFullscreen();ownFullscreen=true;try{await screen.orientation.lock('landscape');}catch(_){}}else{await document.exitFullscreen();ownFullscreen=false;}}catch(_){document.querySelector('.walk-phone-hint span').textContent='Rotate your phone sideways for a wider view. Fullscreen is unavailable in this browser.';}};
  document.addEventListener('pointerlockchange',()=>{
    const locked=document.pointerLockElement===canvas;mouseStatus(locked);
    if(locked){if(!dialog.open||popup.open){releaseMouse();return;}controlMode='explore';canvas.focus({preventScroll:true});}
    else{keys.clear();momentum.x=momentum.y=0;targetYaw=yaw;targetPitch=pitch;if(controlMode!=='popup')controlMode='cursor';}
  });
  canvas.addEventListener('pointerlockerror',()=>{lockingMouse=false;controlMode=popup.open?'popup':'cursor';mouseStatus(false);});
  dialog.addEventListener('cancel',event=>{event.preventDefault();if(popup.open){closePopup();return;}controlMode='cursor';releaseMouse();stopGuide();});
  cameraMenu.value='first';
  function filterDirectory(){const words=search.value.trim().toLowerCase().split(/\s+/);menu.replaceChildren(new Option('Choose a destination',''));for(const option of options)if(words.every(word=>option.label.toLowerCase().includes(word)))menu.append(new Option(option.label,option.code));if(menu.options.length===2)menu.selectedIndex=1;}
  search.oninput=filterDirectory;
  function findAndGuide(){if(!menu.value&&menu.options.length>1)menu.selectedIndex=1;if(!menu.value){selection.textContent='No matching product or rack. Try another search.';return;}choose(menu.value);plan();}
  document.querySelector('#walk-find').onclick=findAndGuide;search.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();findAndGuide();}});
  menu.onchange=()=>{if(menu.value){choose(menu.value);plan();}};document.querySelector('#walk-guide').onclick=plan;document.querySelector('#walk-stop').onclick=()=>{stopGuide();canvas.focus({preventScroll:true});};document.querySelector('#walk-home').onclick=reset;
  for(const button of dialog.querySelectorAll('[data-walk-key]')){button.onpointerdown=e=>{e.preventDefault();button.setPointerCapture(e.pointerId);controlMode='explore';stopGuide();keys.add(button.dataset.walkKey);};for(const name of ['pointerup','pointercancel','lostpointercapture'])button.addEventListener(name,()=>keys.delete(button.dataset.walkKey));}
  document.querySelector('#walk-jump').onclick=()=>{canvas.focus({preventScroll:true});};
  document.querySelector('#walk-open').onclick=async()=>{const version=++generation;dialog.showModal();settings.open=!phone();hud.textContent='Loading warehouse…';try{const response=await fetch('/api/store-map');if(!response.ok)throw Error('Unable to load warehouse.');const loaded=await response.json();if(version!==generation||!dialog.open)return;data=loaded;options=[];search.value='';menu.replaceChildren(new Option('Choose a destination',''));for(const r of data.layout.regions){if([...menu.options].some(o=>o.value===r.code))continue;const names=data.products.filter(p=>p.locations.some(l=>code(l.area)===r.code)).map(p=>p.name);const uids=data.products.filter(p=>p.locations.some(l=>code(l.area)===r.code)).map(p=>p.uid);const label=r.label+(names.length?' — '+names.join(', '):'')+(uids.length?' · '+uids.join(', '):'');options.push({label,code:r.code});menu.append(new Option(label,r.code));}destination='';buildGeometry();reset();controlMode=phone()?'explore':'cursor';mouseStatus(false);hud.textContent='Choose a destination, or explore freely.';last=performance.now();frame=requestAnimationFrame(tick);}catch(e){hud.textContent=e.message;}};
  document.querySelector('#walk-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{generation++;if(popup.open)popup.close();cancelAnimationFrame(frame);keys.clear();route=[];touchLook=null;if(ownFullscreen){if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});try{screen.orientation.unlock();}catch(_){}ownFullscreen=false;}if(document.pointerLockElement===canvas)document.exitPointerLock();document.querySelector('#walk-open').focus();});
})();
