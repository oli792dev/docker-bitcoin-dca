
(()=>{
 const dialog=document.getElementById('settingsDialog'),frame=document.getElementById('settingsFrame');
 let dirty=false;
 function requestClose(){if(dirty)frame.contentWindow.postMessage({type:'dca-settings-request-close'},window.location.origin);else dialog.close()}
 document.getElementById('openSettings').addEventListener('click',()=>{
  dirty=false;frame.style.visibility='hidden';frame.src='/settings?embedded=1';dialog.showModal();
 });
 document.getElementById('closeSettings').addEventListener('click',requestClose);
 dialog.addEventListener('cancel',event=>{event.preventDefault();requestClose()});
 dialog.addEventListener('close',()=>{frame.style.visibility='hidden';frame.src='about:blank';fetch('/api/ui-events',{method:'POST',headers:{'Content-Type':'application/json','X-DCA-Action':'ui-event'},body:JSON.stringify({event:'settings_closed'}),keepalive:true}).catch(()=>{});});
 window.addEventListener('message',event=>{
  if(event.origin!==window.location.origin||event.source!==frame.contentWindow)return;
  if(event.data?.type==='dca-settings-action'&&dialog.open&&['withdraw','export'].includes(event.data.action))window.DCA_DASHBOARD_ACTIONS?.[event.data.action]?.();
  if(event.data?.type==='dca-settings-ready'&&dialog.open)frame.style.visibility='visible';
  if(event.data?.type==='dca-settings-dirty')dirty=event.data.dirty===true;
  if(event.data?.type==='dca-settings-close')dialog.close();
  if(event.data?.type==='dca-settings-saved')window.location.reload();
  if(event.data?.type==='dca-settings-auth-required')window.location.href='/';
 });
})();
