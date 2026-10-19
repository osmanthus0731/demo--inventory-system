(() => {
  const svg=document.querySelector('#store-map');if(!svg)return;
  const isDemo=svg.dataset.demo==='1';
  const search=document.querySelector('#map-search'),results=document.querySelector('#map-results'),message=document.querySelector('#map-message');
  const ns='http://www.w3.org/2000/svg';
  let mapRoute=[],routeRack='';
  const routeDone=document.querySelector('#map-route-done');
  function clearRoute(){mapRoute=[];routeRack='';render();}
  routeDone.onclick=clearRoute;
  svg.addEventListener('walk-route-done',clearRoute);
  let layout,products=[],selected='',angle=-.45,zoom=1,top=false,floorView='all',tilt=.56;
  const unitsPerBox=1000;
  const levelOf=code=>code==='G8'?2:1;
  const levelControl=document.createElement('label');levelControl.textContent='Floor';
  const floorSelect=document.createElement('select');floorSelect.id='map-floor';floorSelect.setAttribute('aria-label','Floor');
  for(const [value,label] of [['all','All floors'],['1','Ground floor'],['2','Level 2 — G8 mezzanine']])floorSelect.append(new Option(label,value));
  levelControl.append(floorSelect);document.querySelector('.map-toolbar').insertBefore(levelControl,document.querySelector('#map-reset'));
  if(isDemo)levelControl.style.display='none';
  floorSelect.onchange=()=>{floorView=floorSelect.value;selected=floorView==='2'?'G8':'';render();};
  const norm=value=>String(value||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
  const rackCode=value=>{const m=String(value||'').trim().toUpperCase().match(/^([A-Z]+)\s*0*(\d+)(?=$|[^0-9])/);return m?m[1]+Number(m[2]):norm(value);};
  const tokenMatch=p=>{const text=norm([p.uid,p.name,...p.locations.map(l=>l.area)].join(' '));return search.value.trim().split(/\s+/).every(t=>text.includes(norm(t)));};
  const node=(tag,attrs={},text)=>{const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text!=null)el.textContent=text;return el;};
  const matches=()=>products.filter(tokenMatch);
  const pastelGroups=isDemo?{DEMO:['#b9dbc9','#406c58']}:{A:['#cbbde5','#594477'],B:['#afd6ea','#325c73'],C:['#f0c6ae','#79543e'],D:['#b5dfce','#386b58'],G:['#eddda9','#75632c']};
  const groupFor=code=>pastelGroups[(code.match(/^[A-Z]+/)||[])[0]]||['#cbd2dc','#465569'];
  const legend=document.querySelector('#map-legend');legend.replaceChildren();
  for(const [letter,[fill]] of Object.entries(pastelGroups)){const item=document.createElement('span'),swatch=document.createElement('i');swatch.style.setProperty('--legend',fill);item.append(swatch,document.createTextNode(`${letter} locations`));legend.append(item);}
  legend.append(document.createTextNode('Turquoise outline: search match · Purple outline: selected'));
  function project(x,y,z=0){x-=layout.width/2;y-=layout.depth/2;const a=x*Math.cos(angle)-y*Math.sin(angle),b=x*Math.sin(angle)+y*Math.cos(angle);return [550+a*.75*zoom,410+b*(top?.75:.75*Math.sin(tilt))*zoom-z*(top?0:Math.cos(tilt)/Math.cos(.56))*zoom];}
  function draw(){
    if(!layout)return;svg.replaceChildren();
    const found=matches(),highlight=new Set(found.flatMap(p=>p.locations.map(l=>rackCode(l.area)))),query=norm(search.value);
    // Use every product, not just the search result, so searching never changes fullness.
    const stockByRack=new Map(),unknownRacks=new Set();
    for(const product of products)for(const location of product.locations){
      const code=rackCode(location.area),quantity=location.quantity;
      if(quantity===null||quantity===undefined||quantity===''||!Number.isFinite(Number(quantity))){unknownRacks.add(code);continue;}
      stockByRack.set(code,(stockByRack.get(code)||0)+Math.max(0,Number(quantity)));
    }
    const boxAllocations=new Map();
    for(const region of layout.regions){
      const siblings=layout.regions.filter(other=>other.code===region.code);
      const total=Math.ceil((stockByRack.get(region.code)||0)/unitsPerBox);
      boxAllocations.set(region,Math.floor(total/siblings.length)+(siblings.indexOf(region)<total%siblings.length?1:0));
    }
    const polygon=(parent,points,fill,extra={})=>parent.append(node('polygon',{points:points.map(p=>p.join(',')).join(' '),fill,...extra}));
    const line=(parent,a,b,color,width=2)=>parent.append(node('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:color,'stroke-width':width,'stroke-linecap':'round'}));
    const box=(parent,x,y,w,d,z,h,colors)=>{
      const corners=[[x,y],[x+w,y],[x+w,y+d],[x,y+d]],base=corners.map(([a,b])=>project(a,b,z)),roof=corners.map(([a,b])=>project(a,b,z+h));
      const faces=[0,1,2,3].sort((a,b)=>(base[a][1]+base[(a+1)%4][1])-(base[b][1]+base[(b+1)%4][1]));
      for(const i of faces)polygon(parent,[base[i],base[(i+1)%4],roof[(i+1)%4],roof[i]],colors[i%2]);
      polygon(parent,roof,colors[2]);
    };
    const floor=[[0,0],[layout.width,0],[layout.width,layout.depth],[0,layout.depth]].map(([x,y])=>project(x,y));
    const defs=node('defs');const shadow=node('filter',{id:'rack-shadow',x:'-30%',y:'-30%',width:'170%',height:'180%'});shadow.append(node('feDropShadow',{dx:0,dy:5,stdDeviation:4,'flood-opacity':'.15'}));defs.append(shadow);svg.append(defs);
    polygon(svg,floor.map(([x,y])=>[x+8,y+14]),'#9aa5ad',{'class':'warehouse-foundation'});
    polygon(svg,floor,'#e0e2df',{'class':'warehouse-floor'});
    for(let x=0;x<=layout.width;x+=70)line(svg,project(x,0),project(x,layout.depth),'#cbd0cd',.7);
    for(let y=0;y<=layout.depth;y+=70)line(svg,project(0,y),project(layout.width,y),'#cbd0cd',.7);
    // Low perimeter walls keep the floor plan visible from every angle.
    if(!top){box(svg,0,0,layout.width,8,0,28,['#a5b0b7','#c2cbd0','#e4e9ec']);box(svg,0,0,8,layout.depth,0,28,['#a5b0b7','#c2cbd0','#e4e9ec']);}
    for(const wall of layout.walls||[]){const group=node('g',{'class':'warehouse-divider','aria-label':wall.label});box(group,wall.x,wall.y,wall.width,wall.depth,0,top?0:wall.height,['#7d8992','#65737e','#aab4bd']);svg.append(group);}
    for(const door of layout.doorways||[]){
      const group=node('g',{'class':'warehouse-doorway','aria-label':door.label});group.append(node('title',{},door.label+' ? open passage beneath the lintel'));
      if(!top){
        const post=door.post_width||4,clearance=door.clearance||84,height=door.height||105,colors=['#7d8992','#65737e','#aab4bd'];
        box(group,door.x,door.y-post,door.width,post,0,height,colors);
        box(group,door.x,door.y+door.depth,door.width,post,0,height,colors);
        box(group,door.x,door.y,door.width,door.depth,clearance,height-clearance,colors);
      }else{
        polygon(group,[[door.x,door.y],[door.x+door.width,door.y],[door.x+door.width,door.y+door.depth],[door.x,door.y+door.depth]].map(([x,y])=>project(x,y)),'none',{stroke:'#65737e','stroke-dasharray':'4 4','stroke-width':1.5});
      }
      svg.append(group);
    }
    let platformDrawn=false;
    function drawPlatforms(){
      if(platformDrawn||floorView==='1')return;platformDrawn=true;
      for(const platform of layout.platforms||[]){
        const group=node('g',{'class':'warehouse-platform','aria-label':platform.label,'data-floor':2,opacity:top?.4:1});
        box(group,platform.x,platform.y,platform.width,platform.depth,top?0:platform.elevation,top?0:platform.thickness,['#6889a2','#85a6bb','#c0d8e7']);
        if(!top)for(const [x,y] of [[platform.x,platform.y],[platform.x+platform.width-4,platform.y],[platform.x,platform.y+platform.depth-4],[platform.x+platform.width-4,platform.y+platform.depth-4]])box(group,x,y,4,4,0,platform.elevation,['#677d8e','#8296a5','#b8c6d1']);
        svg.append(group);
      }
    }
    const regions=layout.regions.filter(r=>floorView==='all'||String(levelOf(r.code))===floorView).sort((a,b)=>levelOf(a.code)-levelOf(b.code)||project(a.x,a.y)[1]-project(b.x,b.y)[1]);
    const pinRacks=new Map();
    for(const r of regions){const current=pinRacks.get(r.code);if(!current||r.width*r.depth>current.width*current.depth)pinRacks.set(r.code,r);}
    const pins=[];
    for(const r of regions){
      const active=r.code===selected,isMatch=query&&(highlight.has(r.code)||norm(r.label).includes(query));
      const [color,labelColor]=groupFor(r.code),accent=active?'#8464c5':isMatch?'#148c88':labelColor;
      const h=top?0:r.kind==='room'?28:66;
      if(levelOf(r.code)===2)drawPlatforms();
      const elevation=r.code==='G8'&&!top?120:0;
      const g=node('g',{'class':'map-rack',tabindex:0,role:'button','aria-label':r.label,'data-floor':levelOf(r.code)});
      const stock=stockByRack.get(r.code)||0;
      const requestedBoxes=boxAllocations.get(r)||0;
      g.setAttribute('data-stock-quantity',stock);
      g.setAttribute('data-box-count',requestedBoxes);
      g.append(node('title',{},r.label+(r.code==='G8'?' — Level 2 mezzanine':'')+` · ${stock} known units${unknownRacks.has(r.code)?' · Some quantities unknown':''}. ${requestedBoxes} illustrated boxes (up to 1,000 units each).`));
      if(elevation&&!(layout.platforms||[]).length){
        // G8's footprint is the upper platform. Its structural height is illustrative.
        for(let x=r.x;x<=r.x+r.width;x+=Math.max(30,r.width/4)){
          for(const y of [r.y-8,r.y+r.depth+8])box(g,x-3,y-3,6,6,0,elevation,['#556677','#697c8b','#b0bac0']);
        }
        box(g,r.x-8,r.y-12,r.width+16,r.depth+24,elevation-8,8,['#697d92','#8297aa','#cbd5df']);
        for(const y of [r.y-12,r.y+r.depth+12]){
          line(g,project(r.x-8,y,elevation+22),project(r.x+r.width+8,y,elevation+22),'#ddb14d',2.5);
          for(let x=r.x;x<=r.x+r.width;x+=Math.max(25,r.width/8))line(g,project(x,y,elevation),project(x,y,elevation+22),'#b78931',2);
        }
      }
      const parcel=(x,y,w,d,z,height=14)=>{
        const carton=node('g',{'class':'stock-parcel','aria-hidden':'true',opacity:'.2',style:'pointer-events:none;transform-box:fill-box;transform-origin:center'});
        box(carton,x,y,w,d,z,height,['#aa8751','#c3a367','#e6d6a1']);
        line(carton,project(x+w*.5,y,z+height),project(x+w*.5,y+d,z+height),'#f7e8bb',2);g.append(carton);
      };
      if(top||r.kind==='room'){
        box(g,r.x,r.y,r.width,r.depth,elevation,h,[color,'#8b9ca9',r.kind==='room'?'#c4cdd2':'#dfc99a']);
        const visible=Math.min(requestedBoxes,48);
        for(let i=0;i<visible;i++)parcel(r.x+(i%3)*r.width/3+3,r.y+Math.floor((i%12)/3)*r.depth/4+3,Math.max(3,r.width/3-6),Math.max(3,r.depth/4-6),elevation+h+Math.floor(i/12)*15,top?0:12);
      }
      else{
        const shadowPoints=[[r.x+6,r.y+8],[r.x+r.width+6,r.y+8],[r.x+r.width+6,r.y+r.depth+8],[r.x+6,r.y+r.depth+8]].map(([x,y])=>project(x,y));
        polygon(g,shadowPoints,'#64717b',{'fill-opacity':'.15',stroke:'none'});
        const alongX=r.width>=r.depth,length=alongX?r.width:r.depth,count=Math.max(1,Math.min(9,Math.floor(length/28)));
        const visible=Math.min(requestedBoxes,count*6);
        for(let level=0;level<3;level++){
          const z=elevation+level*22+3;
          box(g,r.x,r.y,r.width,r.depth,z,3,[labelColor,color,color]);
          for(let index=0;index<count;index++){
            if(level*count+index>=visible)continue;
            const x=r.x+(alongX?index*r.width/count+3:3),y=r.y+(alongX?3:index*r.depth/count+3),w=alongX?Math.max(5,r.width/count-6):Math.max(5,r.width-6),d=alongX?Math.max(5,r.depth-6):Math.max(5,r.depth/count-6);
            parcel(x,y,w,d,z+3);
          }
          for(const y of [r.y,r.y+r.depth])line(g,project(r.x,y,z+2),project(r.x+r.width,y,z+2),accent,2.5);
        }
        // Filled shelves spill into a few playful layers above the rack.
        for(let i=count*3;i<visible;i++){
          const slot=i%count,layer=Math.floor((i-count*3)/count);
          const x=r.x+(alongX?slot*r.width/count+3:3),y=r.y+(alongX?3:slot*r.depth/count+3);
          const w=alongX?Math.max(5,r.width/count-6):Math.max(5,r.width-6),d=alongX?Math.max(5,r.depth-6):Math.max(5,r.depth/count-6);
          parcel(x,y,w,d,elevation+69+layer*15);
        }
        for(const [x,y] of [[r.x,r.y],[r.x+r.width,r.y],[r.x+r.width,r.y+r.depth],[r.x,r.y+r.depth]])line(g,project(x,y,elevation),project(x,y,elevation+h),'#485b68',2.5);
      }
      const center=project(r.x+r.width/2,r.y+r.depth/2,elevation+h);
      const drawnBoxes=g.querySelectorAll('.stock-parcel').length;
      if(requestedBoxes>drawnBoxes)g.append(node('text',{x:center[0],y:center[1]+18,'text-anchor':'middle',fill:labelColor,'font-size':13,'font-weight':700,'class':'box-overflow'},`+${requestedBoxes-drawnBoxes} boxes`));
      if(pinRacks.get(r.code)===r){
        const pin=node('g',{'class':`rack-pin${active?' selected':''}${isMatch?' matching':''}`,style:`--pin-fill:${color}`,transform:`translate(${center[0]},${center[1]-9})`,role:'button',tabindex:0,'aria-label':`Locate ${r.code}`});
        line(pin,[0,0],[0,-19],accent,2);
        pin.append(node('path',{d:'M0,-12 L-8,-23 H-23 Q-28,-23 -28,-29 V-47 Q-28,-53 -22,-53 H22 Q28,-53 28,-47 V-29 Q28,-23 22,-23 H8 Z',fill:color,stroke:accent,'stroke-width':active||isMatch?4:2,filter:'url(#rack-shadow)'}));
        pin.append(node('text',{x:0,y:-35,'text-anchor':'middle','class':'pin-label',style:`fill:${labelColor}`},r.code==='G8'?'G8 · L2':r.code));
        pin.onclick=()=>{if(!dragged){selected=r.code;render();}};pin.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selected=r.code;render();}};
        pins.push(pin);
      }
      const choose=()=>{selected=r.code;render();};
      g.onclick=()=>{if(!dragged)choose();};g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose();}};
      svg.append(g);
    }
    if(mapRoute.length){
      const points=mapRoute.map(p=>project(p.x,p.y,2));
      svg.append(node('polyline',{class:'warehouse-route',points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#7652b5','stroke-width':5,'stroke-linejoin':'round','stroke-linecap':'round','pointer-events':'none','aria-label':'Route from entrance to '+routeRack}));
      const start=points[0],end=points[points.length-1];
      for(const [p,label] of [[start,'Entrance'],[end,routeRack]]){svg.append(node('circle',{cx:p[0],cy:p[1],r:6,fill:'#7652b5',stroke:'white','stroke-width':2}));svg.append(node('text',{x:p[0]+9,y:p[1]-8,fill:'#56348e','font-size':14,'font-weight':700},label));}
    }
    for(const pin of pins)svg.append(pin);
  }
  function render(){
    draw();results.replaceChildren();
    routeDone.disabled=!mapRoute.length;
    const found=matches().filter(p=>floorView==='all'||p.locations.some(l=>String(levelOf(rackCode(l.area)))===floorView)),rows=selected?found.filter(p=>p.locations.some(l=>rackCode(l.area)===selected)):found;
    document.querySelector('#map-title').textContent=selected==='G8'?'G8 · Level 2 mezzanine':selected?`Location ${selected}`:search.value?'Search results':'Select a rack';
    document.querySelector('#map-summary').textContent=`${rows.length} products${selected?' in this location':''}. Quantities are shown per location.`;
    for(const p of rows.slice(0,100)){
      const block=document.createElement('div');block.className='map-product';
      const link=document.createElement('a');link.href='/item/'+encodeURIComponent(p.uid)+'?return_to='+encodeURIComponent('/store-map');link.textContent=p.name||p.uid;block.append(link);
      const uid=document.createElement('small');uid.textContent=p.uid;block.append(uid);
      const locs=document.createElement('div');locs.className='map-locations';
      for(const l of p.locations){const b=document.createElement('button');b.textContent=`${l.area}${rackCode(l.area)==='G8'?' (Level 2)':''}: ${l.quantity??'Unknown'}`;b.onclick=()=>{selected=rackCode(l.area);if(floorView!=='all'){floorView=String(levelOf(selected));floorSelect.value=floorView;}render();};locs.append(b);const guide=document.createElement('button');guide.textContent='Guide me';guide.onclick=()=>{routeRack=rackCode(l.area);selected=routeRack;const start=layout.entrance||{x:45,y:layout.depth-45};mapRoute=WarehouseNavigation.find(layout,start,routeRack);render();if(!mapRoute.length)message.textContent='No clear aisle route found for '+routeRack+'.';};locs.append(guide);}block.append(locs);results.append(block);
    }
    if(rows.length>100)results.append(document.createTextNode('Showing 100 results. Refine your search.'));
    if(!rows.length)results.textContent='No matching stock locations. Try another rack or product.';
    const mapped=new Set(layout.regions.map(r=>r.code));
    const unmapped=[...new Set(found.flatMap(p=>p.locations.map(l=>l.area)).filter(area=>!mapped.has(rackCode(area))))];
    message.textContent=unmapped.length?`Locations outside this plan: ${unmapped.join(', ')}. Stock remains searchable in the results.`:'';
  }
  let initialProduct=new URLSearchParams(location.search).get('uid');
  async function load(){try{message.textContent='Loading stock locations...';const response=await fetch('/api/store-map');if(!response.ok)throw Error('Unable to load stock locations.');const data=await response.json();layout=data.layout;products=data.products;
    if(initialProduct){search.value=initialProduct;const product=products.find(p=>p.uid===initialProduct),mapped=new Set(layout.regions.map(r=>r.code));selected=product?.locations.map(l=>rackCode(l.area)).find(code=>mapped.has(code))||'';initialProduct=null;}
    render();}catch(e){message.textContent=e.message;}}
  let startX=null,startY=null,originX=0,originY=0,dragged=false,pointerId=null;
  svg.onpointerdown=e=>{
    if(e.button!==0)return;
    e.preventDefault();startX=originX=e.clientX;startY=originY=e.clientY;dragged=false;pointerId=e.pointerId;
  };
  svg.onpointermove=e=>{
    if(startX==null||e.pointerId!==pointerId)return;
    e.preventDefault();
    if(!dragged&&Math.hypot(e.clientX-originX,e.clientY-originY)<5)return;
    if(!dragged){dragged=true;svg.setPointerCapture(e.pointerId);window.getSelection()?.removeAllRanges();}
    angle+=(e.clientX-startX)*.006;
    // An above-floor camera: tilt cannot cross the horizon or look underneath.
    tilt=Math.max(.25,Math.min(1.35,tilt-(e.clientY-startY)*.006));
    top=false;startX=e.clientX;startY=e.clientY;draw();
  };
  const stopDrag=e=>{if(pointerId!==e.pointerId)return;startX=startY=null;pointerId=null;if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);};
  svg.onpointerup=stopDrag;svg.onpointercancel=stopDrag;
  svg.onlostpointercapture=()=>{startX=startY=null;pointerId=null;};
  svg.addEventListener('click',e=>{if(dragged){e.preventDefault();e.stopImmediatePropagation();dragged=false;}},true);
  svg.addEventListener('dragstart',e=>e.preventDefault());
  svg.addEventListener('selectstart',e=>e.preventDefault());
  svg.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.45,Math.min(2.5,zoom-e.deltaY*.001));draw();},{passive:false});
  search.oninput=()=>{selected='';render();};
  svg.addEventListener('walk-select',event=>{selected=event.detail.code;render();});
  document.querySelector('#map-reset').onclick=()=>{angle=-.45;zoom=1;tilt=.56;top=false;selected='';mapRoute=[];routeRack='';floorView='all';floorSelect.value='all';search.value='';render();};
  document.querySelector('#map-top').onclick=()=>{top=!top;draw();};document.querySelector('#map-refresh').onclick=load;
  document.querySelector('#map-zoom-in').onclick=()=>{zoom=Math.min(2.5,zoom+.2);draw();};
  document.querySelector('#map-zoom-out').onclick=()=>{zoom=Math.max(.45,zoom-.2);draw();};
  window.addEventListener('meadow:update',e=>{if(e.detail.channels.includes('inventory'))load();});load();
})();
