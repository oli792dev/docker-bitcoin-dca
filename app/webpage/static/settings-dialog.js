
(()=>{
 const dialog=document.getElementById('settingsDialog'),frame=document.getElementById('settingsFrame');
 document.getElementById('openSettings').addEventListener('click',()=>{
  frame.src='/settings?embedded=1';dialog.showModal();
 });
 document.getElementById('closeSettings').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{frame.src='about:blank';fetch('/api/ui-events',{method:'POST',headers:{'Content-Type':'application/json','X-DCA-Action':'ui-event'},body:JSON.stringify({event:'settings_closed'}),keepalive:true}).catch(()=>{});});
 window.addEventListener('message',event=>{
  if(event.origin!==window.location.origin||event.source!==frame.contentWindow)return;
  if(event.data?.type==='dca-settings-close')dialog.close();
  if(event.data?.type==='dca-settings-saved')window.location.reload();
  if(event.data?.type==='dca-settings-auth-required')window.location.href='/';
 });
})();
