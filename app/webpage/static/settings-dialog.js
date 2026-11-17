
(()=>{
 const dialog=document.getElementById('settingsDialog'),frame=document.getElementById('settingsFrame');
 const closeButton=document.getElementById('closeSettings'),logoutButton=dialog.querySelector('.logout-button');
 let ready=false;
 function requestClose(){if(ready)frame.contentWindow.postMessage({type:'dca-settings-request-close'},window.location.origin);else dialog.close()}
 function openSettings(hash=''){
  ready=false;frame.style.visibility='hidden';frame.src='/settings?embedded=1'+hash;dialog.showModal();
 }
 document.getElementById('openSettings').addEventListener('click',()=>openSettings());
 const withdrawalsLink=document.querySelector('#withdrawalDisabledHint a');
 withdrawalsLink.addEventListener('click',event=>{
  if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  event.preventDefault();openSettings(withdrawalsLink.hash);
 });
 closeButton.addEventListener('click',requestClose);
 dialog.addEventListener('cancel',event=>{event.preventDefault();requestClose()});
 dialog.addEventListener('close',()=>{frame.style.visibility='hidden';frame.src='about:blank';fetch('/api/ui-events',{method:'POST',headers:{'Content-Type':'application/json','X-DCA-Action':'ui-event'},body:JSON.stringify({event:'settings_closed'}),keepalive:true}).catch(()=>{});});
 window.addEventListener('message',event=>{
  if(event.origin!==window.location.origin||event.source!==frame.contentWindow)return;
  if(event.data?.type==='dca-settings-action'&&dialog.open&&['withdraw','export'].includes(event.data.action))window.DCA_DASHBOARD_ACTIONS?.[event.data.action]?.();
  if(event.data?.type==='dca-settings-ready'&&dialog.open){
   ready=true;frame.style.visibility='visible';
   if(event.data.focusWithdrawals)frame.contentDocument.getElementById('withdrawals_enabled').focus();
  }
  if(event.data?.type==='dca-settings-busy'&&dialog.open)closeButton.disabled=logoutButton.disabled=event.data.active===true;
  if(event.data?.type==='dca-settings-close')dialog.close();
  if(event.data?.type==='dca-transactions-updated')window.DCA_DASHBOARD_ACTIONS?.refreshSchedule?.();
  if(event.data?.type==='dca-settings-saved')window.location.reload();
  if(event.data?.type==='dca-settings-auth-required')window.location.href='/';
 });
})();
