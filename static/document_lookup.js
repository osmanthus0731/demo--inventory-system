/* Cancellable, keyboard-accessible item suggestions shared by all document editors. */
(() => {
  const cache=new Map();
  let sequence=0;
  window.bindDocumentLookup=(input,list,endpoint,select,options={})=>{
    let timer,blurTimer,controller,generation=0,active=-1,choices=[],suppressFocus=false;
    const id='document-lookup-'+(++sequence);
    list.id=id;list.setAttribute('role','listbox');list.hidden=true;
    input.autocomplete='off';input.setAttribute('role','combobox');
    input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-controls',id);
    input.setAttribute('aria-expanded','false');
    const close=()=>{
      clearTimeout(timer);clearTimeout(blurTimer);controller?.abort();generation++;active=-1;choices=[];
      list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
    };
    const showMessage=text=>{
      const message=document.createElement('span');
      message.className='document-lookup-status';message.setAttribute('role','status');message.textContent=text;
      list.replaceChildren(message);list.hidden=false;input.setAttribute('aria-expanded','true');
    };
    const choose=choice=>{
      close();suppressFocus=true;select(choice);input.focus({preventScroll:true});suppressFocus=false;
      input.dispatchEvent(new Event('change',{bubbles:true}));
    };
    const render=data=>{
      choices=data;active=-1;
      if(!choices.length){showMessage(options.emptyMessage||'No matching items. Try another name or code, or enter a manual description.');return;}
      list.replaceChildren(...choices.map((choice,index)=>{
        const button=document.createElement('button');button.type='button';button.id=id+'-'+index;
        button.setAttribute('role','option');button.setAttribute('aria-selected','false');
        button.textContent=options.label?options.label(choice):(choice.description||choice.name||'Unnamed item')+' · '+(choice.uid||choice.product_id||'');
        button.onpointerdown=event=>{clearTimeout(blurTimer);event.preventDefault();};
        button.onclick=()=>choose(choice);
        return button;
      }));
      list.hidden=false;input.setAttribute('aria-expanded','true');
    };
    const search=(immediate=false)=>{
      close();
      const query=input.value.trim(),current=generation,key=endpoint+query.toLowerCase();
      const run=async()=>{
        if(!input.isConnected)return;
        const cached=options.load?null:cache.get(key);
        if(cached&&Date.now()-cached.at<30000){render(cached.data);return;}
        controller=new AbortController();showMessage(options.loadingMessage||'Searching items…');
        try{
          let data;
          if(options.load)data=await options.load(query);
          else{
            const response=await fetch(endpoint+encodeURIComponent(query),{signal:controller.signal});
            if(!response.ok)throw Error('Search unavailable');
            data=await response.json();
          }
          if(current!==generation||!input.isConnected)return;
          if(!Array.isArray(data))throw Error('Invalid search response');
          if(cache.size>=80)cache.delete(cache.keys().next().value);
          if(!options.load)cache.set(key,{at:Date.now(),data});render(data);
        }catch(error){
          if(current===generation&&error.name!=='AbortError'){
            choices=[];showMessage(options.errorMessage||'Item search is unavailable. Try again, or enter a manual description.');
          }
        }
      };
      if(immediate)run();else timer=setTimeout(run,180);
    };
    input.addEventListener('input',()=>search());
    input.addEventListener('focus',()=>{
      if(!suppressFocus){document.querySelectorAll('.document-results').forEach(other=>{if(other!==list)other.dispatchEvent(new Event('dismiss'));});search(true);}
    });
    input.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();close();return;}
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();
        if(list.hidden){search(true);return;}
        if(!choices.length)return;
        active=active<0?(event.key==='ArrowDown'?0:choices.length-1):(active+(event.key==='ArrowDown'?1:-1)+choices.length)%choices.length;
        [...list.querySelectorAll('[role="option"]')].forEach((button,index)=>button.setAttribute('aria-selected',String(index===active)));
        const option=list.querySelectorAll('[role="option"]')[active];
        input.setAttribute('aria-activedescendant',option.id);option.scrollIntoView({block:'nearest'});
      }else if(event.key==='Enter'&&!list.hidden){
        event.preventDefault();
        if(choices.length)choose(choices[active<0?0:active]);
      }
    });
    input.addEventListener('blur',()=>{blurTimer=setTimeout(close,180);});
    list.addEventListener('dismiss',close);
    if(options.browse){
      const button=document.createElement('button');button.type='button';button.className='btn platform-secondary document-browse';
      button.textContent='Browse items';button.setAttribute('aria-controls',id);
      button.onclick=()=>{suppressFocus=true;input.focus({preventScroll:true});suppressFocus=false;search(true);};
      input.after(button);
    }
    return {close,search};
  };
})();
