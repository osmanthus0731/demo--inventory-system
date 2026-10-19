(() => {
  const key='app_language',textState=new WeakMap(),attributeState=new WeakMap();let language=localStorage.getItem(key)==='zh-CN'?'zh-CN':'en',dictionary=null,loading=null,scheduled=false;
  const excluded='script,style,svg,canvas,textarea,[data-no-translate],.language-control,.product-name,.user-name,.person-name,#stock-product,.map-product a,.performance-title strong,.mover-name strong,.account-card strong,.walk-popup-item strong,#walk-popup-title,.po-preview,.document-a4';
  function translate(value){
    if(language!=='zh-CN'||!dictionary)return value;
    const trimmed=value.trim();if(dictionary[trimmed])return value.replace(trimmed,dictionary[trimmed]);
    const patterns=[[/^Rack (.+) - Click for items$/,rack=>'\u8d27\u67b6 '+rack+' - \u70b9\u51fb\u67e5\u770b\u4ea7\u54c1'],[/^Rack (.+)$/,rack=>'\u8d27\u67b6 '+rack],[/^Auto-guide to (.+)$/,rack=>'\u81ea\u52a8\u6307\u5f15\u5230 '+rack],[/^Auto direct to (.+)$/,rack=>'\u81ea\u52a8\u6307\u5f15\u5230 '+rack],[/^Location (.+)$/,rack=>'\u4f4d\u7f6e '+rack],[/^Page (\d+)$/,number=>'\u7b2c '+number+' \u9875'],[/^Welcome, (.+)\. Make yourself at home\.$/,name=>'\u6b22\u8fce\uff0c'+name+'\u3002']];
    for(const [pattern,format] of patterns){const match=trimmed.match(pattern);if(match)return value.replace(trimmed,format(...match.slice(1)));}
    return value;
  }
  function apply(root=document.body){
    if(!root||root.nodeType!==1||root.closest(excluded))return;
    // Option labels may be translated; submitted values must stay unchanged.
    for(const option of root.querySelectorAll('option'))if(!option.hasAttribute('value'))option.setAttribute('value',option.value);
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
    while(node=walker.nextNode()){
      if(!node.textContent.trim()||node.parentElement?.closest(excluded))continue;
      let state=textState.get(node);if(!state||node.textContent!==state.rendered)state={source:node.textContent};
      const rendered=translate(state.source);if(node.textContent!==rendered)node.textContent=rendered;state.rendered=rendered;textState.set(node,state);
    }
    for(const element of [root,...root.querySelectorAll('[placeholder],[title],[aria-label],[data-tip]')]){
      if(element.closest(excluded))continue;
      let states=attributeState.get(element)||{};
      for(const name of ['placeholder','title','aria-label','data-tip']){if(!element.hasAttribute(name))continue;const value=element.getAttribute(name);let state=states[name];if(!state||value!==state.rendered)state={source:value};state.rendered=translate(state.source);if(value!==state.rendered)element.setAttribute(name,state.rendered);states[name]=state;}
      attributeState.set(element,states);
    }
  }
  async function setLanguage(value){
    language=value==='zh-CN'?'zh-CN':'en';localStorage.setItem(key,language);document.documentElement.lang=language;
    document.querySelectorAll('[data-language-picker]').forEach(select=>select.value=language);
    if(language==='zh-CN'&&!dictionary){
      try{loading=loading||fetch('/static/zh-cn.json').then(response=>{if(!response.ok)throw Error('Language unavailable');return response.json();});dictionary=await loading;}
      catch{loading=null;language='en';localStorage.setItem(key,'en');document.documentElement.lang='en';document.querySelectorAll('[data-language-picker]').forEach(select=>select.value='en');}
    }
    apply();window.dispatchEvent(new CustomEvent('app:language',{detail:{language}}));
  }
  function picker(parent){
    const label=document.createElement('label');label.className='language-control';const select=document.createElement('select');select.dataset.languagePicker='';select.setAttribute('aria-label','Language / \u8bed\u8a00');select.append(new Option('English','en'),new Option('\u7b80\u4f53\u4e2d\u6587','zh-CN'));select.value=language;select.onchange=()=>setLanguage(select.value);label.append(select);parent.append(label);
  }
  const footer=document.querySelector('.sb-footer'),topbar=document.querySelector('.topbar');
  const userMenu=footer&&footer.querySelector('.user-menu');
  if(userMenu)picker(userMenu);else if(footer)picker(footer);if(topbar)picker(topbar);
  if(!footer&&!topbar)picker(document.querySelector('.account-panel,.right-panel')||document.body);
  const dirty=new Set();new MutationObserver(records=>{for(const record of records){const root=record.target.nodeType===1?record.target:record.target.parentElement;if(root&&!root.closest(excluded))dirty.add(root);}if(!scheduled&&dirty.size){scheduled=true;setTimeout(()=>{scheduled=false;for(const root of dirty)if(root.isConnected)apply(root);dirty.clear();},100);}}).observe(document.body,{childList:true,characterData:true,subtree:true});
  window.addEventListener('storage',event=>{if(event.key===key)setLanguage(event.newValue);});
  window.AppI18n={setLanguage,translate,get language(){return language;}};setLanguage(language);
})();
