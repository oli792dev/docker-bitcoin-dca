const {t,locale}=typeof DCA_I18N!=="undefined"?DCA_I18N:{t:value=>value,locale:"en-GB"};

const initial=__INITIAL__, $=id=>document.getElementById(id);let pending=null;
function connectionMessage(text,error=false){$('connectionStatus').textContent=t(text);$('connectionStatus').classList.toggle('is-error',error)}
const fieldErrors=new Map();
function clearFieldError(input){
 const error=fieldErrors.get(input.id);if(!error)return;
 input.removeAttribute?.('aria-invalid');input.setAttribute('aria-invalid','false');
 const described=(input.getAttribute?.('aria-describedby')||input['aria-describedby']||'').split(' ').filter(id=>id&&id!==error.id);
 input.setAttribute('aria-describedby',described.join(' '));error.hidden=true;error.textContent='';fieldErrors.delete(input.id);
 updateFieldSummary();
}
function updateFieldSummary(){
 const summary=$('settingsErrors');summary.replaceChildren();summary.hidden=fieldErrors.size<2;
 if(summary.hidden)return;
 const caption=document.createElement('span');caption.textContent=t('Please check the highlighted fields.');summary.append(caption);
 for(const [field] of fieldErrors){
  const input=$(field),owner=settingsTabs.find(tab=>tab.panel.contains(input)),link=document.createElement('a');
  link.href='#'+field;link.textContent=input.labels?.[0]?.textContent||$(field+'Label')?.textContent||field.replaceAll('_',' ');
  link.addEventListener('click',event=>{event.preventDefault();activateSettingsTab(owner?.id||(['username','current_password','password','passwordConfirm'].includes(field)?'dashboardOptions':'botConfiguration'));input.focus();input.scrollIntoView?.({block:'center'})});summary.append(link);
 }
}
function message(text,error=false,field=null){
 $('status').textContent=t(text);$('status').classList.toggle('error',error);
 if(!error||!field||!$(field))return;
 const input=$(field);let output=$(field+'Error');
 if(!output){output=document.createElement('small');output.id=field+'Error';output.className='field-error';output.setAttribute('role','alert');input.parentElement?.append(output)}
 output.hidden=false;output.textContent=t(text);fieldErrors.set(field,output);input.setAttribute('aria-invalid','true');
 const described=input.getAttribute?.('aria-describedby')||input['aria-describedby']||'';
 input.setAttribute('aria-describedby',[...new Set([...described.split(' ').filter(Boolean),output.id])].join(' '));
 const owner=settingsTabs.find(tab=>tab.panel.contains(input));
 // Login credentials are nested under Dashboard; the remaining owner is found in the DOM.
 activateSettingsTab(owner?.id||(['username','current_password','password','passwordConfirm'].includes(field)?'dashboardOptions':'botConfiguration'));
 $('status').textContent='';$('status').classList.toggle('error',false);updateFieldSummary();
 input.focus();input.scrollIntoView?.({block:'center'});
}

async function request(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-DCA-Action':'settings'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok){const error=Error(d.error||'Request failed');error.field=path==='/api/setup/account'?({username:'newUsername',password:'newPassword'}[d.field]||d.field):d.field;throw error;}return d}
function exchangeChanged(){return $('exchange').value!==(initial.settings.exchange||'KRAKEN')}
function exchangeName(){return $('exchange').value==='KRAKEN'?'Kraken':'Bitvavo'}
function updateExchangeGuidance(){
 const changed=exchangeChanged(),name=exchangeName();
 $('exchangePermissionsHint').textContent=t($('exchange').value==='KRAKEN'?
  'Required API permissions for Kraken: Query Funds, Query Open/Closed Orders & Trades and Query ledger entries. For live trading: Modify Orders. For withdrawals: Withdraw Funds.':
  'Required API permissions for Bitvavo: Read-only / View access and Trade digital assets. For withdrawals: Withdraw digital assets.');
 $('exchangeSwitchHint').hidden=!changed;
 $('exchangeSwitchHint').textContent=t(changed?'Switching to '+name+' requires entering its API key and API secret again. Enter the keys below and review the withdrawal target.':'');
 for(const prefix of ['kraken','bitvavo'])for(const part of ['key','secret']){const input=$(prefix+'_api_'+part),active=prefix===$('exchange').value.toLowerCase();input.required=changed&&active;input.placeholder=!changed&&initial.settings[input.id+'_configured']?'••••••••':'';$(input.id+'Hint').textContent=t(changed&&active?'Required for '+name:(initial.settings[input.id+'_configured']?'Saved · leave empty to keep':'Not configured'))}
}
function updatePurchaseCurrencyLabel(){$('withdraw_thresholdLabel').textContent=t('Automatic withdrawal threshold ('+($('quote').value||'EUR')+')');$('expected_monthly_depositLabel').textContent=t('Expected monthly deposit ('+($('quote').value||'EUR')+')')}
function selectedExchange(){const kraken=$('exchange').value==='KRAKEN';for(const prefix of ['kraken','bitvavo'])for(const part of ['key','secret'])$(prefix+'_api_'+part).parentElement.hidden=(prefix==='kraken')!==kraken;$('krakenTarget').hidden=!kraken;$('bitvavoTarget').hidden=kraken;$('bitvavoNetwork').hidden=kraken;$('quote').options[1].disabled=!kraken;if(!kraken)$('quote').value='EUR';updateExchangeGuidance();updatePurchaseCurrencyLabel()}
function exchangeCredentialsReady(){if(!exchangeChanged())return true;const prefix=$('exchange').value.toLowerCase();if(!$(prefix+'_api_key').value.trim()||!$(prefix+'_api_secret').value.trim()){activateSettingsTab('exchangeConnection');connectionMessage('Enter '+exchangeName()+' API key and API secret before testing or saving.',true);return false}return true}

for(const prefix of ['kraken','bitvavo'])for(const part of ['key','secret']){const key=prefix+'_api_'+part,field=document.createElement('div'),label=document.createElement('label'),input=document.createElement('input'),hint=document.createElement('small');label.htmlFor=key;label.textContent=t(prefix[0].toUpperCase()+prefix.slice(1)+' API '+part);input.id=key;input.type='password';input.autocomplete='off';input.autocapitalize='none';input.spellcheck=false;hint.id=key+'Hint';hint.className='hint';hint.textContent=t(initial.settings[key+'_configured']?'Saved · leave empty to keep':'Not configured');input.setAttribute('aria-describedby',hint.id+' exchangePermissionsHint');input.dataset.setting='';field.className='setting-row';field.append(label,input,hint);$('credentials').append(field)}
const fields=[
 ['buy_amount','BTC per purchase (0 = exchange minimum)','0','any',null,'Amounts below exchange minimum are not applied.'],
 ['startup_delay_seconds','Startup delay (seconds)','0','1','86400','Wait before the first account check after startup.'],
 ['deposit_day','Deposit day (day of month)','1','1','31','Short months use their last day. Does not transfer money.'],
 ['deposit_time','Deposit time','00:00','60','23:59','Expected local deposit time for purchase planning.'],
 ['expected_monthly_deposit','Expected monthly deposit (purchase currency)','0','0.01',null,'Forecast only; assumes deposits on this day and time.'],
 ['check_interval_seconds','Account check interval (minutes)','1','any','1440','Refresh balances, prices, purchase and withdrawal schedules.'],
 ['order_status_check_seconds','Open order check interval (seconds)','1','1','3600','Recheck pending orders; new purchases wait for confirmation.'],
 ['withdraw_threshold','Automatic withdrawal threshold (purchase currency)','0.01','any',null,'All available exchange BTC, valued in the purchase currency.']
];
const settingGroups={};
for(const [id,title] of [['purchase','Purchases'],['deposit','Deposits'],['withdrawal','Withdrawals'],['timing','Timing']]){
 const group=document.createElement('section'),heading=document.createElement('h3'),list=document.createElement('div');
 group.className='settings-group';heading.id=id+'GroupTitle';heading.textContent=t(title);group.setAttribute('aria-labelledby',heading.id);list.id=id+'GroupFields';list.className='setting-list';group.append(heading,list);$('purchaseFields').append(group);settingGroups[id]=list;
}
settingGroups.purchase.append($('liveTradingCard'));settingGroups.withdrawal.append($('automaticWithdrawalsCard'));
const depositDateFields=document.createElement('div');depositDateFields.id='depositDateFields';depositDateFields.className='setting-pair';settingGroups.deposit.append(depositDateFields);
const fieldGroup={buy_amount:'purchase',deposit_day:'deposit',deposit_time:'deposit',expected_monthly_deposit:'deposit',withdraw_threshold:'withdrawal',startup_delay_seconds:'timing',check_interval_seconds:'timing',order_status_check_seconds:'timing'};
for(const [key,title,min,step,max,description] of fields){const field=document.createElement('div'),label=document.createElement('label'),input=document.createElement('input'),hint=document.createElement('small');field.className='setting-row';label.htmlFor=key;label.id=key+'Label';label.textContent=t(title);input.id=key;input.type=key==='deposit_time'?'time':'number';if(input.type==='number')input.inputMode=['buy_amount','withdraw_threshold','expected_monthly_deposit'].includes(key)?'decimal':'numeric';input.required=key!=='expected_monthly_deposit';input.dataset.setting='';input.min=min;input.step=step;if(max)input.max=max;hint.id=key+'Hint';hint.className='hint field-description';hint.textContent=t(description);input.setAttribute('aria-describedby',hint.id);field.append(label,input,hint);(['deposit_day','deposit_time'].includes(key)?depositDateFields:settingGroups[fieldGroup[key]]).append(field)}
const timezoneGroups=[
 ['Universal',[['UTC','UTC']]],
 ['Europe',[['Europe/Berlin','Berlin'],['Europe/London','London'],['Europe/Paris','Paris'],['Europe/Zurich','Zurich'],['Europe/Helsinki','Helsinki'],['Europe/Istanbul','Istanbul'],['Europe/Moscow','Moscow']]],
 ['Americas',[['America/New_York','New York'],['America/Chicago','Chicago'],['America/Denver','Denver'],['America/Los_Angeles','Los Angeles'],['America/Anchorage','Anchorage'],['Pacific/Honolulu','Honolulu'],['America/Toronto','Toronto'],['America/Mexico_City','Mexico City'],['America/Sao_Paulo','São Paulo'],['America/Argentina/Buenos_Aires','Buenos Aires']]],
 ['Africa',[['Africa/Cairo','Cairo'],['Africa/Lagos','Lagos'],['Africa/Johannesburg','Johannesburg']]],
 ['Asia',[['Asia/Dubai','Dubai'],['Asia/Kolkata','Kolkata'],['Asia/Bangkok','Bangkok'],['Asia/Singapore','Singapore'],['Asia/Shanghai','Shanghai'],['Asia/Tokyo','Tokyo'],['Asia/Seoul','Seoul']]],
 ['Oceania',[['Australia/Perth','Perth'],['Australia/Sydney','Sydney'],['Pacific/Auckland','Auckland']]]
];
const timezoneValues=new Set();for(const [region,zones] of timezoneGroups){const group=document.createElement('optgroup');group.label=t(region);for(const [value,label] of zones){const option=document.createElement('option');option.value=value;option.textContent=t(label+' ('+value+')');group.append(option);timezoneValues.add(value)}$('timezone').append(group)}
const savedTimezone=initial.settings.timezone;if(typeof savedTimezone==='string'&&!timezoneValues.has(savedTimezone)){const option=document.createElement('option');option.value=savedTimezone;option.textContent=t(savedTimezone+' (saved timezone)');$('timezone').append(option)}
for(const input of document.querySelectorAll('[data-setting]')){const v=initial.settings[input.id];if(v===undefined)continue;if(input.type==='checkbox')input.checked=v;else input.value=input.id==='check_interval_seconds'?v/60:v}
$('accountPanel').hidden=!initial.createAccount;$('settingsForm').hidden=initial.createAccount;if(document.body)document.body.classList.toggle('settings-active',!initial.createAccount);
const showCredentials=Boolean($('dashboardCredentials'));if(showCredentials)$('username').value=initial.username||'';if(!initial.complete){$('pageHeading').textContent=t('2. Configure your bot');$('back').hidden=true}
if(showCredentials){$('passwordRequired').hidden=!initial.passwordChangeRequired;if(initial.passwordChangeRequired){$('password').required=true;$('current_password').required=true}}
if(initial.embedded){
 document.body.classList.add('embedded');$('settingsNavigationHeading').hidden=true;$('back').hidden=true;$('pageHeading').hidden=true;
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('review').open&&!$('discardDialog').open){event.preventDefault();requestSettingsClose()}});
}
const settingsTabDefinitions=[['botConfiguration','Bot Configuration'],['exchangeConnection','Exchange'],['dashboardOptions','Dashboard']];
const settingsTabs=[];
function activateSettingsTab(id,focus=false){
 if($('settingsContent'))$('settingsContent').scrollTop=0;
 if(initial.createAccount)return;
 if(initial.complete&&settingsTabs.some(item=>item.id===id)){try{localStorage.setItem('bitcoinDcaSettingsTab',id)}catch(e){}}
 for(const item of settingsTabs){const selected=item.id===id;item.panel.hidden=!selected;item.button.setAttribute('aria-selected',String(selected));item.button.tabIndex=selected?0:-1;if(selected){item.button.scrollIntoView?.({block:'nearest',inline:'nearest'});if(focus)item.button.focus()}}
}
$('settingsTabs').hidden=Boolean(initial.createAccount);
if(!initial.createAccount){
 for(const [id,label] of settingsTabDefinitions){
  const panel=$(id);if(!panel)continue;
  const button=document.createElement('button');button.type='button';button.id=id+'Tab';button.textContent=t(label);button.setAttribute('role','tab');button.setAttribute('aria-controls',id);
  panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);
  button.addEventListener('click',()=>activateSettingsTab(id));
  button.addEventListener('keydown',event=>{const index=settingsTabs.findIndex(item=>item.id===id);let next;if(event.key==='ArrowRight')next=(index+1)%settingsTabs.length;else if(event.key==='ArrowLeft')next=(index-1+settingsTabs.length)%settingsTabs.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=settingsTabs.length-1;else return;event.preventDefault();activateSettingsTab(settingsTabs[next].id,true)});
  settingsTabs.push({id,panel,button});$('settingsTabs').append(button);
 }
 let rememberedTab='botConfiguration';
 try{const storedTab=localStorage.getItem('bitcoinDcaSettingsTab'),saved=storedTab==='dashboardCredentials'?'dashboardOptions':storedTab;if(settingsTabs.some(item=>item.id===saved))rememberedTab=saved}catch(e){}
 activateSettingsTab(initial.complete?rememberedTab:'exchangeConnection');
 let invalidTabOpened=false;
 $('settingsForm').addEventListener('invalid',event=>{if(invalidTabOpened)return;const item=settingsTabs.find(item=>item.panel.contains(event.target));if(item){activateSettingsTab(item.id);invalidTabOpened=true;setTimeout(()=>{invalidTabOpened=false},0)}},true);
}
$('quote').addEventListener('change',updatePurchaseCurrencyLabel);selectedExchange();$('exchange').addEventListener('change',()=>{for(const prefix of ['kraken','bitvavo'])for(const part of ['key','secret'])$(prefix+'_api_'+part).value='';connectionMessage('');selectedExchange()});
function values(){const result={};for(const input of document.querySelectorAll('[data-setting]')){if(input.id==='withdraw_threshold'&&input.disabled){result[input.id]=initial.settings.withdraw_threshold;continue}result[input.id]=input.id==='check_interval_seconds'?Math.round(Number(input.value)*60):input.type==='checkbox'?input.checked:input.type==='number'&&['deposit_day','startup_delay_seconds','check_interval_seconds','order_status_check_seconds','dashboard_refresh_seconds'].includes(input.id)?Number(input.value):input.value}return result}
$('accountForm').addEventListener('submit',async e=>{e.preventDefault();if($('newPassword').value!==$('confirmPassword').value){message('Passwords do not match.',true,'confirmPassword');return}const b=e.submitter;b.disabled=true;try{await request('/api/setup/account',{username:$('newUsername').value,password:$('newPassword').value});location.href='/settings'}catch(err){message(err.message,true,err.field)}finally{b.disabled=false}});
$('testConnection').addEventListener('click',async()=>{if(!exchangeCredentialsReady())return;const b=$('testConnection');b.disabled=true;b.ariaBusy='true';b.textContent=t('Testing…');connectionMessage('Testing connection…');try{connectionMessage((await request('/api/settings/test',values())).message)}catch(err){connectionMessage(err.message,true)}finally{b.disabled=false;b.ariaBusy='false';b.textContent=t('Test connection')}});
function needsPassword(){
 if(!initial.complete||!pending)return false;
 if(pending.password||pending.username&&pending.username!==initial.username)return true;
 const before=initial.settings,after=pending.settings;
 const protectedFields=['exchange','quote','kraken_api_key','kraken_api_secret','bitvavo_api_key','bitvavo_api_secret','kraken_withdraw_key','withdraw_address','withdraw_network','withdraw_threshold'];
 return protectedFields.some(key=>key in after&&after[key]!==before[key]&&(!key.includes('_api_')||String(after[key]).trim()!==''))||['live','withdrawals_enabled'].some(key=>after[key]===true&&!before[key]);
}
function renderReview(){
 $('passwordConfirmation').hidden=!needsPassword()||Boolean(pending.current_password);
 $('sensitivePassword').value='';$('passwordConfirmationError').textContent=t('');
 const before=initial.settings,after={...before,...pending.settings},rows=[];
 const number=value=>Number.isFinite(Number(value))?(locale==='de-DE'?Number(value).toLocaleString(locale,{maximumFractionDigits:20}):String(Number(value))):String(value??'');
 const enabled=value=>value?'Enabled':'Disabled';
 function add(name,oldValue,newValue,changed=oldValue!==newValue){const display=value=>['Dashboard username','Withdrawal target'].includes(name)?String(value||t('Not configured')):t(String(value||'Not configured'));rows.push({name,before:display(oldValue),after:display(newValue),changed:!initial.complete||changed})}
 add('Exchange',before.exchange,after.exchange);
 add('Purchase currency',before.quote,after.quote);
 for(const prefix of ['kraken','bitvavo'])for(const part of ['key','secret']){
  const key=prefix+'_api_'+part,entered=typeof pending.settings[key]==='string'&&pending.settings[key].trim()!=='';
  if(prefix!==after.exchange.toLowerCase()&&!entered)continue;
  const configured=Boolean(before[key+'_configured']),oldValue=configured?'Configured (hidden)':'Not configured';
  add((prefix==='kraken'?'Kraken':'Bitvavo')+' API '+part,oldValue,entered?'Will be updated (hidden)':oldValue,entered);
 }
 const target=settings=>settings.exchange==='KRAKEN'?'Kraken · '+(settings.kraken_withdraw_key||t('Not configured')):'Bitvavo · '+(settings.withdraw_address||t('Not configured'))+' · '+(settings.withdraw_network||'BTC');
 add('Withdrawal target',target(before),target(after));
 for(const [key,label] of [['buy_amount','BTC per purchase'],['deposit_day','Deposit day'],['deposit_time','Deposit time'],['expected_monthly_deposit','Expected monthly deposit'],['dashboard_refresh_seconds','Dashboard refresh interval'],['startup_delay_seconds','Startup delay'],['check_interval_seconds','Account check interval'],['order_status_check_seconds','Open order check interval'],['withdraw_threshold','Automatic withdrawal threshold']]){
  const format=(settings)=>key==='buy_amount'?(Number(settings[key])===0?'Exchange minimum':number(settings[key])+' BTC'):['withdraw_threshold','expected_monthly_deposit'].includes(key)?(settings[key]===''?t('Not configured'):number(settings[key])+' '+settings.quote):key==='check_interval_seconds'?number(settings[key]/60)+t(' minutes'):number(settings[key])+(key.endsWith('_seconds')?t(' seconds'):'');
  add(label,format(before),format(after));
 }
 add('Live trading',before.live?'Live':'Simulation',after.live?'Live':'Simulation');
 for(const [key,label] of [['withdrawals_enabled','Automatic withdrawals'],['manual_withdrawal_enabled','Manual withdrawals'],['parqet_enabled','Parqet CSV']])add(label,enabled(before[key]),enabled(after[key]));
 const appearanceLabel=value=>({system:'Automatic / System',light:'Light',dark:'Dark'}[value]||'Automatic / System');
 add('Appearance',appearanceLabel(before.appearance),appearanceLabel(after.appearance));
 add('Display currency',before.display_currency,after.display_currency);
 add('Timezone',before.timezone,after.timezone);
 add('Language',before.language==='de'?'Deutsch':'English',after.language==='de'?'Deutsch':'English');
 if('username'in pending)add('Dashboard username',initial.username,pending.username.trim());
 if(pending.password)add('Dashboard password','Configured (hidden)','Will be changed (hidden)',true);
 $('reviewValues').replaceChildren();$('unchangedReviewValues').replaceChildren();$('unchangedReview').open=false;
 const changed=rows.filter(row=>row.changed).length;
 $('reviewDescription').textContent=t(!initial.complete?'New configuration — review the settings below.':changed?changed+' change'+(changed===1?'':'s')+' — compare Before and After.':'No changes. Your current settings will be retained.');
 $('unchangedReview').hidden=changed===rows.length;$('unchangedReviewTitle').textContent=t('Unchanged settings ('+(rows.length-changed)+')');
 for(const row of rows){
  const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=t(row.name);
  if(row.changed){
   dt.className='review-changed';dd.className='review-changed';const badge=document.createElement('span');badge.className='review-badge';badge.textContent=t(initial.complete?'Changed':'New');dt.append(badge);
   const comparison=document.createElement('div');comparison.className='review-comparison';
   function side(caption,value,className){const box=document.createElement('div'),label=document.createElement('span'),text=document.createElement('span');box.className='review-side';label.className='review-caption';label.textContent=t(caption);text.className=className;text.textContent=value;box.append(label,text);return box}
   if(initial.complete){const arrow=document.createElement('span');arrow.className='review-arrow';arrow.setAttribute('aria-hidden','true');arrow.textContent=t('→');comparison.append(side('Before',row.before,'review-old'),arrow)}
   else comparison.style.gridTemplateColumns='minmax(0,1fr)';
   comparison.append(side(initial.complete?'After':'New setting',row.after,'review-new'));dd.append(comparison);
  }else{dt.className='review-unchanged';dd.className='review-unchanged';dd.textContent=row.after}
  $(row.changed?'reviewValues':'unchangedReviewValues').append(dt,dd);
 }
}
$('settingsForm').addEventListener('submit',e=>{e.preventDefault();if(!exchangeCredentialsReady())return;const editingCredentials=showCredentials;if(editingCredentials&&$('password').value!==$('passwordConfirm').value){message('New passwords do not match.',true,'passwordConfirm');return}pending={settings:values()};if(editingCredentials)Object.assign(pending,{username:$('username').value.trim(),password:$('password').value,current_password:$('current_password').value});renderReview();$('review').showModal()});

function logSettingsCancellation(){fetch('/api/ui-events',{method:'POST',headers:{'Content-Type':'application/json','X-DCA-Action':'ui-event'},body:JSON.stringify({event:'settings_save_cancelled'}),keepalive:true}).catch(()=>{})}
$('cancel').addEventListener('click',()=>{$('review').close();pending=null;$('sensitivePassword').value='';logSettingsCancellation()});$('review').addEventListener('cancel',()=>{pending=null;$('sensitivePassword').value='';logSettingsCancellation()});
$('confirm').addEventListener('click',async()=>{if(!pending)return;if(needsPassword()&&!pending.current_password){if(!$('sensitivePassword').value){$('passwordConfirmationError').textContent=t('Enter your current login password to confirm these changes.');return}pending.current_password=$('sensitivePassword').value}const b=$('confirm');b.disabled=true;try{const d=await request('/api/settings',pending);pending=null;savedDraft=draftSignature();updateDirty();if(initial.embedded){window.parent.postMessage({type:'dca-settings-saved'},location.origin)}else{location.href='/'}}catch(err){if(pending)delete pending.current_password;$('review').close();message(err.message,true,err.field)}finally{$('sensitivePassword').value='';b.disabled=false}});

function updateDependencies(){
 const live=$('live').checked,automatic=$('withdrawals_enabled').checked;
 $('withdrawals_enabled').disabled=false;
 $('withdraw_threshold').disabled=!automatic;
 $('withdrawals_enabledHint').textContent=t(live?'Withdraw when the configured threshold is reached.':'Automatic withdrawals require live trading; you can configure them now.');
 $('withdraw_thresholdHint').textContent=t(!automatic?'Enable automatic withdrawals to edit this threshold.':fields.find(row=>row[0]==='withdraw_threshold')[5]);
 $('automaticWithdrawalsCard').classList.toggle('setting-inactive',false);
 $('withdraw_threshold').parentElement.classList.toggle('setting-inactive',!automatic);
}
updateDependencies();
for(const id of ['live','withdrawals_enabled'])$(id).addEventListener('change',updateDependencies);
function draftSignature(){
 const settings=[...document.querySelectorAll('[data-setting]')].map(input=>[input.id,input.type==='checkbox'?input.checked:input.value]);
 const account=showCredentials?['username','current_password','password','passwordConfirm'].map(id=>$(id).value):[];
 return JSON.stringify([settings,account]);
}
let savedDraft=draftSignature(),settingsDirty=false;
function updateDirty(){
 settingsDirty=draftSignature()!==savedDraft;
 $('unsavedChanges').hidden=!settingsDirty;
 if(initial.embedded)window.parent.postMessage({type:'dca-settings-dirty',dirty:settingsDirty},location.origin);
}
function requestSettingsClose(){
 updateDirty();
 if(settingsDirty){$('discardDialog').showModal();return}
 if(initial.embedded)window.parent.postMessage({type:'dca-settings-close'},location.origin);else location.href='/';
}
$('settingsForm').addEventListener('input',updateDirty);$('settingsForm').addEventListener('change',updateDirty);
$('keepEditing').addEventListener('click',()=>$('discardDialog').close());
$('discardChanges').addEventListener('click',()=>{savedDraft=draftSignature();updateDirty();$('discardDialog').close();requestSettingsClose()});
$('back').addEventListener('click',event=>{event.preventDefault();requestSettingsClose()});
if(typeof window!=='undefined'&&window.addEventListener){
 window.addEventListener('message',event=>{if(initial.embedded&&event.origin===location.origin&&event.source===window.parent&&event.data?.type==='dca-settings-request-close')requestSettingsClose()});
 window.addEventListener('beforeunload',event=>{if(settingsDirty){event.preventDefault();event.returnValue=''}});
}

if(initial.embedded)window.parent.postMessage({type:'dca-settings-ready'},location.origin);

for(const id of [...fields.map(field=>field[0]),'username','current_password','password','passwordConfirm','newUsername','newPassword','confirmPassword','exchange','quote','kraken_api_key','kraken_api_secret','bitvavo_api_key','bitvavo_api_secret','kraken_withdraw_key','withdraw_address','withdraw_network','timezone','language','appearance','display_currency','dashboard_refresh_seconds']){
 const input=$(id);if(input)input.addEventListener('input',()=>clearFieldError(input));
}

// Account actions use the saved dashboard configuration, never the Settings draft.
if(initial.complete&&initial.embedded){
 $('settingsQuickActions').hidden=false;
 $('settingsWithdraw').hidden=!initial.settings.manual_withdrawal_enabled;
 $('settingsExport').hidden=!initial.settings.parqet_enabled;
 for(const [id,action] of [['settingsWithdraw','withdraw'],['settingsExport','export']])$(id).addEventListener('click',()=>{
  $('settingsWithdraw').disabled=true;$('settingsExport').disabled=true;
  window.parent.postMessage({type:'dca-settings-action',action},location.origin);
 });
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==window.parent||event.data?.type!=='dca-dashboard-action-feedback')return;
  const {message:text,error,busy}=event.data;
  if(text!==null){$('settingsActionMessage').textContent=t(text);$('settingsActionMessage').classList.toggle('error',Boolean(error));$('settingsActionFeedback').hidden=!text}
  if(busy!==null){$('settingsWithdraw').disabled=busy;$('settingsExport').disabled=busy}
 });
 $('dismissSettingsAction').addEventListener('click',()=>{$('settingsActionFeedback').hidden=true;$('settingsActionMessage').textContent=''});
}

