/* Depth-tested warehouse surfaces. The visible canvas keeps its accessible 2D HUD. */
window.WarehouseDepthRenderer=class {
  constructor(){
    this.canvas=document.createElement('canvas');
    const gl=this.gl=this.canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:false});
    if(!gl)throw Error('WebGL is unavailable');
    this.lost=false;
    this.canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();this.lost=true;});
    const shader=(type,source)=>{const value=gl.createShader(type);gl.shaderSource(value,source);gl.compileShader(value);if(!gl.getShaderParameter(value,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(value));return value;};
    const program=this.program=gl.createProgram();
    gl.attachShader(program,shader(gl.VERTEX_SHADER,`
      attribute vec3 position; attribute vec3 color; attribute vec3 pickColor; attribute float visibility;
      uniform vec3 projection; varying vec3 surface; varying vec3 identity; varying float distance; varying float alpha;
      void main(){float near=3.0;float far=4000.0;
        gl_Position=vec4(position.x*projection.x,position.y*projection.y+projection.z*position.z,((far+near)/(far-near))*position.z-2.0*far*near/(far-near),position.z);
        surface=color;identity=pickColor;distance=position.z;alpha=visibility;
      }`));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`
      precision mediump float; uniform bool picking; uniform vec3 hovered; varying vec3 surface;varying vec3 identity;varying float distance;varying float alpha;
      void main(){if(picking){gl_FragColor=vec4(identity,1.0);return;}
        vec3 tint=surface;if(dot(hovered,hovered)>0.0 && length(identity-hovered)<0.001)tint=mix(surface,vec3(1.0,0.79,0.31),0.38);
        float fog=clamp((distance-550.0)/1900.0,0.0,0.45);
        gl_FragColor=vec4(mix(tint,vec3(0.78,0.85,0.84),fog),alpha);
      }`));
    gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    this.buffer=gl.createBuffer();this.projection=gl.getUniformLocation(program,'projection');this.picking=gl.getUniformLocation(program,'picking');this.hoverUniform=gl.getUniformLocation(program,'hovered');this.highlighted=null;
    this.attributes=['position','color','pickColor','visibility'].map(name=>gl.getAttribLocation(program,name));
    this.colors=new Map();this.ids=new Map();this.racks=[null];
  }
  color(value){if(!this.colors.has(value)){const n=parseInt(value.slice(1),16);this.colors.set(value,[(n>>16&255)/255,(n>>8&255)/255,(n&255)/255]);}return this.colors.get(value);}
  draw(faces,camera,width,height,thirdPerson,pitch){
    if(this.lost)throw Error('WebGL context lost. Reload the page to restore depth rendering.');
    const gl=this.gl;if(this.canvas.width!==width||this.canvas.height!==height){this.canvas.width=width;this.canvas.height=height;}
    const vertices=[],edges=[];this.ids.clear();this.racks=[null];
    for(const face of faces){
      const points=face.points.map(camera);if(points.every(p=>p.z<3))continue;
      let id=0;if(face.rack&&face.rack!=='__player'){if(!this.ids.has(face.rack)){this.ids.set(face.rack,this.racks.length);this.racks.push(face.rack);}id=this.ids.get(face.rack);}
      const color=this.color(face.color),pick=[(id&255)/255,(id>>8&255)/255,(id>>16&255)/255];
      const visibility=face.parcel?.2:1,add=p=>vertices.push(p.x,p.y,p.z,...color,...pick,visibility);
      for(let i=1;i<points.length-1;i++){add(points[0]);add(points[i]);add(points[i+1]);}
      for(let i=0;i<points.length;i++)for(const point of [points[i],points[(i+1)%points.length]])edges.push(point.x,point.y,point.z,...color.map(channel=>channel*.78),...pick,visibility);
    }
    this.count=vertices.length/10;this.edgeCount=edges.length/10;
    gl.useProgram(this.program);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([...vertices,...edges]),gl.DYNAMIC_DRAW);
    this.attributes.forEach((location,index)=>{gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,index===3?1:3,gl.FLOAT,false,40,index*12);});
    const scale=width*(thirdPerson?.5:.62);
    gl.uniform3f(this.projection,2*scale/width,2*scale/height,1-2*((thirdPerson?.35:.53)+pitch));
    gl.viewport(0,0,width,height);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LESS);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.disable(gl.CULL_FACE);gl.disable(gl.DITHER);
    this.setHighlight();this.paint(false);
    return this.canvas;
  }
  paint(picking){const gl=this.gl;gl.uniform1i(this.picking,picking?1:0);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);gl.drawArrays(gl.TRIANGLES,0,this.count);gl.disable(gl.POLYGON_OFFSET_FILL);if(!picking)gl.drawArrays(gl.LINES,this.count,this.edgeCount);gl.flush();}
  setHighlight(){const id=this.ids.get(this.highlighted)||0;this.gl.uniform3f(this.hoverUniform,(id&255)/255,(id>>8&255)/255,(id>>16&255)/255);}
  pick(x,y,highlight=false){if(this.lost||!this.count)return null;const gl=this.gl;this.paint(true);const pixel=new Uint8Array(4);gl.readPixels(Math.max(0,Math.min(this.canvas.width-1,Math.floor(x))),Math.max(0,Math.min(this.canvas.height-1,this.canvas.height-1-Math.floor(y))),1,1,gl.RGBA,gl.UNSIGNED_BYTE,pixel);const rack=this.racks[pixel[0]+pixel[1]*256+pixel[2]*65536]||null;if(highlight){this.highlighted=rack;this.setHighlight();}this.paint(false);return rack;}
};
