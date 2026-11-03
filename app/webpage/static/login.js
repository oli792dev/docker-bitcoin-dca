(()=>{
 try{
  const key='bitcoinDcaRestoredBackup',filename=sessionStorage.getItem(key);
  sessionStorage.removeItem(key);
  if(!filename)return;
  document.getElementById('restoredBackupName').textContent=filename;
  document.getElementById('restoreSuccess').hidden=false;
 }catch{}
})();
