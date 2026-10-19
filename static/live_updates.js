(() => {
  "use strict";
  if (!document.querySelector(".app-shell")) return;
  let retry, timer, cursor=null, polling=false, delay=15000, stopped=false;
  const pending = new Set();
  const badge = document.createElement("span");
  badge.className = "live-status";
  badge.setAttribute("role", "status");
  document.querySelector(".topbar")?.append(badge);
  function clock() {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-GB", {
        timeZone: "Asia/Kuala_Lumpur",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(new Date())
        .map((part) => [part.type, part.value]),
    );
    badge.textContent = `${parts.day}/${parts.month}/${parts.year} ${parts.hour}:${parts.minute}`;
  }
  clock();
  setInterval(()=>{if(!document.hidden)clock();}, 30000);
  function publish(channels) {
    channels.forEach((channel) => pending.add(channel));
    clearTimeout(timer);
    timer = setTimeout(() => {
      const detail = { channels: [...pending] };
      pending.clear();
      window.dispatchEvent(new CustomEvent("meadow:update", { detail }));
      if (
        detail.channels.includes("inventory") &&
        ["/admin_dashboard", "/index"].includes(location.pathname) &&
        !document.querySelector("#stock-dialog")?.open
      )
        location.reload();
    }, 500);
  }
  async function connect(){
    clearTimeout(retry);
    if(stopped||polling||document.hidden||!navigator.onLine)return;
    polling=true;
    try{
      const response=await fetch('/platform/api/events?poll=1'+(cursor?'&since='+encodeURIComponent(JSON.stringify(cursor)):''),{signal:AbortSignal.timeout(12000)});
      if(response.status===401||response.status===403){stopped=true;return;}
      if(!response.ok)throw Error('Updates unavailable');
      const data=await response.json();cursor=data.state;delay=15000;
      if(data.channels.length)publish(data.channels);
    }catch{delay=Math.min(60000,delay*2);}
    finally{polling=false;if(!stopped&&!document.hidden)retry=setTimeout(connect,delay);}
  }
  connect();
  document.addEventListener('visibilitychange',()=>{clearTimeout(retry);if(!document.hidden)connect();});
  window.addEventListener('online',connect);
  window.addEventListener('beforeunload',()=>clearTimeout(retry));
})();
