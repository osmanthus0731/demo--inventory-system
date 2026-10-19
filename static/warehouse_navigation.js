/* Shared aisle routing for the map and simulator. Coordinates stay in warehouse units. */
window.WarehouseNavigation={
  obstacles(layout){
    const solids=[...(layout.walls||[]),...layout.regions.filter(r=>r.code!=='G8')];
    for(const p of layout.platforms||[])for(const [x,y] of [[p.x,p.y],[p.x+p.width-4,p.y],[p.x,p.y+p.depth-4],[p.x+p.width-4,p.y+p.depth-4]])solids.push({x,y,width:4,depth:4});
    for(const r of layout.regions.filter(r=>r.code==='G8'))for(const [x,y] of [[r.x,r.y],[r.x+r.width-3,r.y],[r.x,r.y+r.depth-3],[r.x+r.width-3,r.y+r.depth-3]])solids.push({x,y,width:3,depth:3});
    return solids;
  },
  find(layout,start,code,customClear){
    const obstacles=this.obstacles(layout),padding=9,targets=layout.regions.filter(r=>r.code===code);
    if(!targets.length)return [];
    const clear=customClear||((x,y)=>x>padding&&y>padding&&x<layout.width-padding&&y<layout.depth-padding&&!obstacles.some(r=>x>r.x-padding&&x<r.x+r.width+padding&&y>r.y-padding&&y<r.y+r.depth+padding));
    const segment=(a,b,test=clear)=>{const steps=Math.max(1,Math.ceil(Math.hypot(a.x-b.x,a.y-b.y)/3));for(let i=0;i<=steps;i++)if(!test(a.x+(b.x-a.x)*i/steps,a.y+(b.y-a.y)*i/steps))return false;return true;};
    const wallsClear=(x,y)=>!(layout.walls||[]).some(w=>x>=w.x&&x<=w.x+w.width&&y>=w.y&&y<=w.y+w.depth);
    const step=12,cols=Math.ceil(layout.width/step),rows=Math.ceil(layout.depth/step),point=(x,y)=>({x:x*step+step/2,y:y*step+step/2}),id=(x,y)=>y*cols+x;
    const sx=Math.floor(start.x/step),sy=Math.floor(start.y/step),queue=[],seen=new Map();
    for(let radius=0;radius<=3&&!queue.length;radius++)for(let y=sy-radius;y<=sy+radius;y++)for(let x=sx-radius;x<=sx+radius;x++)if(x>=0&&y>=0&&x<cols&&y<rows&&clear(point(x,y).x,point(x,y).y)&&segment(start,point(x,y))){queue.push([x,y]);seen.set(id(x,y),null);}
    let goal=null;
    for(let head=0;head<queue.length;head++){
      const [x,y]=queue[head],p=point(x,y);
      if(targets.some(r=>{const near={x:Math.max(r.x,Math.min(p.x,r.x+r.width)),y:Math.max(r.y,Math.min(p.y,r.y+r.depth))},distance=Math.hypot(p.x-near.x,p.y-near.y);return distance>=48&&distance<=80&&segment(p,near,wallsClear);})){goal=[x,y];break;}
      for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]]){
        const nx=x+dx,ny=y+dy,next=point(nx,ny);
        if(nx<0||ny<0||nx>=cols||ny>=rows||seen.has(id(nx,ny))||!clear(next.x,next.y)||!segment(p,next))continue;
        seen.set(id(nx,ny),[x,y]);queue.push([nx,ny]);
      }
    }
    if(!goal)return [];
    const path=[];for(let current=goal;current;current=seen.get(id(...current)))path.push(point(...current));path.reverse();path.unshift({...start});
    const smooth=[path[0]];let index=0;
    while(index<path.length-1){let far=path.length-1;while(far>index+1&&!segment(path[index],path[far]))far--;smooth.push(path[far]);index=far;}
    return smooth;
  }
};
