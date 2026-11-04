/* Setup/settings UI behavior using a small DOM fixture; no browser or exchange access. */
const assert=require('node:assert/strict'),vm=require('node:vm'),{execFileSync}=require('node:child_process'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const page=execFileSync('python3',['-c',`import sys,json;sys.path.insert(0,'.');from app.webpage.settings_ui import PAGE;from app.core.configuration import DEFAULTS;print(PAGE.replace('__INITIAL__',json.dumps(dict(settings={**DEFAULTS,'kraken_api_key_configured':True,'kraken_api_secret_configured':True},username='operator',complete=True,createAccount=False))))`],{cwd:root,encoding:'utf8'});
const script=page.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element{
 constructor(tag='div'){this.style={};this.tag=tag;this.value='';this.type='';this.dataset={};this.children=[];this.listeners={};this.hidden=false;this.disabled=false;this.checked=false;this.textContent='';this.options=[{},{}];this.classList={toggle(){},add(){}}}
 append(...children){for(const c of children){c.parentElement=this;this.children.push(c);if(c.id)elements[c.id]=c}}
 replaceChildren(){this.children=[]}
 addEventListener(name,fn){this.listeners[name]=fn}
 setAttribute(name,value){this[name]=value}
 focus(){this.focused=true}
 contains(target){return this===target||this.children.some(child=>child.contains(target))}
 showModal(){this.open=true}
 close(){this.open=false}
}
const elements={};for(const match of page.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){const el=new Element(match[1]);el.id=match[3];el.type=(match[2].match(/type="([^"]+)"/)||[])[1]||'';if(match[2].includes('data-setting'))el.dataset.setting='';elements[el.id]=el}
const requests=[],location={href:''};let reject=false,rejectField=null;
const context={document:{documentElement:{dataset:{}},getElementById:id=>elements[id],createElement:tag=>new Element(tag),querySelectorAll:()=>Object.values(elements).filter(el=>'setting'in el.dataset)},setTimeout:fn=>{fn()},location,
 fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:!reject,json:async()=>reject?{error:'Connection failed',field:rejectField}:{message:'Connected',saved:true}}}};
vm.runInNewContext(script,context);
function allText(el){return el.textContent+' '+el.children.map(allText).join(' ')}
async function event(id,name='click'){if(id==='confirm'&&!elements.passwordConfirmation.hidden&&!elements.sensitivePassword.value)elements.sensitivePassword.value='current-long-password';return elements[id].listeners[name]({preventDefault(){},submitter:elements[id]})}
(async()=>{
 assert.equal(elements.dashboard_refresh_seconds.value,30);elements.dashboard_refresh_seconds.value='75';assert.equal(vm.runInContext('values().dashboard_refresh_seconds',context),75);
 assert.equal(elements.check_interval_seconds.value,5);assert.equal(vm.runInContext('values().check_interval_seconds',context),300);elements.check_interval_seconds.value='2.5';assert.equal(vm.runInContext('values().check_interval_seconds',context),150);elements.check_interval_seconds.value='5';
 assert.equal(elements.settingsTabs.children.length,4);assert.deepEqual(elements.settingsTabs.children.map(x=>x.textContent),['Bot Configuration','Exchange','Dashboard','Backup']);assert.equal(elements.liveTradingCard.parentElement,elements.purchaseGroupFields);assert.equal(elements.automaticWithdrawalsCard.parentElement,elements.withdrawalGroupFields);assert.equal(elements.botConfiguration.hidden,false);assert.equal(elements.dashboardOptions.hidden,true);
 const rememberedTabs=new Map();context.localStorage={getItem:key=>rememberedTabs.get(key),setItem:(key,value)=>rememberedTabs.set(key,value)};
 elements.buy_amount.value='.001';await event('dashboardOptionsTab');assert.equal(rememberedTabs.get('bitcoinDcaSettingsTab'),'dashboardOptions');assert.equal(elements.botConfiguration.hidden,true);assert.equal(elements.dashboardOptions.hidden,false);assert.equal(elements.buy_amount.value,'.001');
 elements.botConfigurationTab.listeners.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(elements.exchangeConnection.hidden,false);assert.equal(elements.exchangeConnectionTab.focused,true);
 elements.exchangeConnectionTab.listeners.keydown({key:'End',preventDefault(){}});assert.equal(elements.backupOptions.hidden,false);
 elements.dashboardOptionsTab.listeners.keydown({key:'Home',preventDefault(){}});assert.equal(elements.botConfiguration.hidden,false);
 elements.botConfiguration.contains=target=>target===elements.deposit_time;await event('dashboardOptionsTab');elements.settingsForm.listeners.invalid({target:elements.deposit_time});assert.equal(elements.botConfiguration.hidden,false);
 elements.buy_amount.value='0';assert.equal(elements.deposit_time.type,'time');assert.equal(elements.deposit_time.value,'00:00');elements.deposit_time.value='09:30';
 assert.equal(elements.expected_monthly_deposit.required,false);assert.equal(elements.expected_monthly_deposit.value,'');elements.expected_monthly_deposit.value='175.50';assert.equal(vm.runInContext('values().expected_monthly_deposit',context),'175.50');elements.expected_monthly_deposit.value='';assert.equal(elements.expected_monthly_depositLabel.textContent,'Expected monthly deposit (EUR)');
 assert.equal(elements.withdraw_thresholdLabel.textContent,'Automatic withdrawal threshold (EUR)');elements.quote.value='USD';await event('quote','change');assert.equal(elements.withdraw_thresholdLabel.textContent,'Automatic withdrawal threshold (USD)');assert.equal(elements.expected_monthly_depositLabel.textContent,'Expected monthly deposit (USD)');
 assert(page.includes('<small id="displayCurrencyHint" class="hint">Reporting only; purchases use the purchase currency.</small>'));assert(page.includes('aria-describedby="displayCurrencyHint"'));
 assert.equal(elements.kraken_api_key.value,'');assert.equal(elements.kraken_api_keyHint.textContent,'Saved · leave empty to keep');assert.equal(elements.kraken_api_key.placeholder,'••••••••');assert(!page.includes('id="exchangeCredentialHint"'));
 assert.equal(elements.appearance.value,'system');const originalAppearance=context.document.documentElement.dataset.appearance;for(const theme of ['dark','light','system','dark']){elements.appearance.value=theme;await elements.appearance.listeners.change?.({target:elements.appearance});assert.equal(context.document.documentElement.dataset.appearance,originalAppearance,'Appearance remains unchanged until successful save')};
 assert.equal(elements.timezone.value,'Europe/Berlin');assert.equal(elements.timezone.tag,'select');assert.equal(elements.timezone.children.length,6);
 assert(elements.timezone.children.some(group=>group.children.some(option=>option.value==='Asia/Tokyo')));
 assert.equal(elements.dashboardEditor.hidden,false);assert.equal(elements.dashboardEditor.disabled,false);assert.equal(elements.exchangeEditor.hidden,false);assert.equal(elements.exchangeEditor.disabled,false);
 assert.equal(elements.buy_amountHint.textContent.length>0,true);assert.equal(elements.withdraw_thresholdHint.textContent.length>0,true);assert.equal(elements.withdraw_threshold.parentElement.parentElement,elements.withdrawalGroupFields);
 for(const key of ['buy_amount','deposit_day','startup_delay_seconds','check_interval_seconds','order_status_check_seconds','withdraw_threshold'])assert.equal(elements[key]['aria-describedby'],key+'Hint');
 assert(!page.includes('<h2>Purchases</h2>'));assert(!page.includes('<h2>Bot Configuration</h2>'));assert(!page.includes('<h2>Withdrawal settings</h2>'));
 assert(!page.includes('id="dashboardCredentialsTab"'));assert(page.indexOf('id="dashboardCredentials"')>page.indexOf('id="dashboardOptions"'));assert(page.includes('id="loginSettingsTitle">Login</h3>'));
 assert.equal(elements.settingsForm.hidden,false);assert.equal(elements.accountPanel.hidden,true);
 elements.exchange.value='BITVAVO';await event('exchange','change');assert.equal(elements.exchangeEditor.hidden,false);assert.equal(elements.exchangeSwitchHint.hidden,false);assert.match(elements.exchangeSwitchHint.textContent,/Bitvavo/);assert.equal(elements.bitvavo_api_key.required,true);assert.equal(elements.bitvavo_api_key.placeholder,'');const beforeMissingKeys=requests.length;await event('testConnection');await event('settingsForm','submit');assert.equal(requests.length,beforeMissingKeys);assert.match(elements.connectionStatus.textContent,/API key and API secret/);assert.equal(elements.quote.value,'EUR');assert.equal(elements.expected_monthly_deposit.required,false);assert.equal(elements.expected_monthly_deposit.value,'');elements.expected_monthly_deposit.value='175.50';assert.equal(vm.runInContext('values().expected_monthly_deposit',context),'175.50');elements.expected_monthly_deposit.value='';assert.equal(elements.expected_monthly_depositLabel.textContent,'Expected monthly deposit (EUR)');
 assert.equal(elements.withdraw_thresholdLabel.textContent,'Automatic withdrawal threshold (EUR)');assert.equal(elements.quote.options[1].disabled,true);assert.equal(elements.kraken_api_key.parentElement.hidden,true);
 elements.bitvavo_api_key.value='fictional-key';elements.bitvavo_api_secret.value='fictional-secret';
 const testing=event('testConnection');assert.equal(elements.connectionStatus.textContent,'Testing connection…');assert.equal(elements.testConnection.disabled,true);await testing;assert.equal(requests.at(-1).url,'/api/settings/test');assert.equal(requests.at(-1).body.bitvavo_api_key,'fictional-key');assert.equal(elements.connectionStatus.textContent,'Connected');
 const count=requests.length;elements.display_currency.value='USD';elements.timezone.value='Asia/Tokyo';elements.live.checked=true;elements.withdrawals_enabled.checked=true;vm.runInContext('updateDependencies()',context);elements.withdraw_threshold.value='1200';
 await event('settingsForm','submit');assert.equal(elements.review.open,true);assert.equal(requests.length,count,'Review must not save yet');
 const text=allText(elements.reviewValues);assert.match(text+allText(elements.unchangedReviewValues),/Live|Simulation/);assert.match(text,/1200 EUR/);assert.match(text,/1000 EUR/);assert.match(text,/Before/);assert.match(text,/After/);assert.equal(elements.unchangedReview.hidden,false);assert.match(allText(elements.unchangedReviewValues),/BTC per purchase/);assert(!text.includes('fictional-key'));assert(!text.includes('fictional-secret'));assert.match(text,/Will be updated \(hidden\)/);
 await event('cancel');assert.equal(elements.review.open,false);await event('confirm');assert.equal(requests.filter(r=>r.url==='/api/settings').length,0,'Cancelled review must not submit');assert.equal(requests.at(-1).body.event,'settings_save_cancelled');
 await event('settingsForm','submit');await event('confirm');assert.equal(requests.at(-1).url,'/api/settings');assert.equal(requests.at(-1).body.settings.withdrawals_enabled,true);assert.equal(requests.at(-1).body.settings.display_currency,'USD');assert.equal(requests.at(-1).body.settings.timezone,'Asia/Tokyo');assert.equal(requests.at(-1).body.settings.appearance,'dark');assert.equal(requests.at(-1).body.settings.deposit_time,'09:30');assert.equal(requests.at(-1).body.settings.dashboard_refresh_seconds,75);
 elements.passwordConfirm.parentElement=new Element();elements.password.value='new-long-password';elements.passwordConfirm.value='different';const before=requests.length;await event('settingsForm','submit');assert.equal(requests.length,before);assert.equal(elements.status.textContent,'');assert.equal(elements.settingsErrors.hidden,true);assert.equal(elements.passwordConfirm['aria-invalid'],'true');assert.match(elements.passwordConfirmError.textContent,/do not match/);assert.equal(elements.dashboardOptions.hidden,false);assert.equal(elements.passwordConfirm.focused,true);elements.passwordConfirm.listeners.input();assert.equal(elements.passwordConfirm['aria-invalid'],'false');assert.equal(elements.passwordConfirmError.hidden,true);
 elements.password.value='';elements.passwordConfirm.value='';elements.exchange.value='KRAKEN';await event('exchange','change');reject=true;await event('testConnection');assert.equal(elements.testConnection.disabled,false);assert.equal(elements.connectionStatus.textContent,'Connection failed');
 vm.runInContext('pending={settings:{buy_amount:"0.000"}};renderReview()',context);assert.equal(elements.reviewValues.children.length,0);assert.match(elements.reviewDescription.textContent,/No changes/);
 vm.runInContext('pending={settings:{},username:"renamed",password:"PRIVATE-DASHBOARD-PASSWORD"};renderReview()',context);const credentialReview=allText(elements.reviewValues);assert.match(credentialReview,/operator/);assert.match(credentialReview,/renamed/);assert.match(credentialReview,/Will be changed \(hidden\)/);assert(!credentialReview.includes('PRIVATE-DASHBOARD-PASSWORD'));
 assert(!page.includes('daylight saving changes are automatic'));
 vm.runInContext("pending={settings:{live:true}};initial.settings.live=false;renderReview()",context);elements.sensitivePassword.value='';const beforePassword=requests.length;await elements.confirm.listeners.click();assert.equal(requests.length,beforePassword,'Sensitive settings cannot be submitted without a password');assert.match(elements.passwordConfirmationError.textContent,/current login password/);elements.sensitivePassword.value='private-confirmation-password';await elements.confirm.listeners.click();assert.equal(requests.at(-1).body.current_password,'private-confirmation-password');assert.equal(elements.sensitivePassword.value,'');
 elements.password.value='new-long-password';elements.passwordConfirm.value='new-long-password';elements.current_password.value='current-long-password';reject=false;await event('settingsForm','submit');await event('confirm');assert.equal(requests.at(-1).body.password,'new-long-password');assert.equal(requests.at(-1).body.settings.exchange,'KRAKEN');
 reject=true;rejectField='deposit_time';const unchangedDeposit=elements.deposit_time.value;await event('settingsForm','submit');await event('confirm');assert.equal(elements.deposit_time['aria-invalid'],'true');assert.equal(elements.botConfiguration.hidden,false);assert.equal(elements.deposit_time.value,unchangedDeposit);assert.equal(elements.deposit_time.focused,true);elements.deposit_time.listeners.input();assert.equal(elements.deposit_time['aria-invalid'],'false');reject=false;rejectField=null;
 console.log('Settings UI passed: credentials, exchange fields, read-only test, review/cancel/save and validation');
})().catch(error=>{console.error(error);process.exitCode=1});

// Step two uses the actual server-rendered page without Login Credentials.
const setupPage=execFileSync('python3',['-c',`import sys;from types import SimpleNamespace;sys.path.insert(0,'.');from app.core.configuration import DEFAULTS;from app.webpage.settings_ui import settings_page;print(settings_page(SimpleNamespace(public=lambda:dict(settings={**DEFAULTS,'timezone':'Pacific/Chatham'},username='operator',complete=False))))`],{cwd:root,encoding:'utf8'});
const setupElements={};
class SetupElement extends Element{append(...children){for(const child of children){child.parentElement=this;this.children.push(child);if(child.id)setupElements[child.id]=child}}}
for(const match of setupPage.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){const el=new SetupElement(match[1]);el.id=match[3];el.type=(match[2].match(/type="([^"]+)"/)||[])[1]||'';if(match[2].includes('data-setting'))el.dataset.setting='';setupElements[el.id]=el}
const setupRequests=[];vm.runInNewContext(setupPage.match(/<script>([\s\S]*?)<\/script>/)[1],{document:{getElementById:id=>setupElements[id],createElement:tag=>new SetupElement(tag),querySelectorAll:()=>Object.values(setupElements).filter(el=>'setting'in el.dataset)},location:{href:''},fetch:async(url,options)=>{setupRequests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({})}}});
assert.equal(setupElements.timezone.value,'Pacific/Chatham');assert.equal(setupElements.timezone.children.at(-1).value,'Pacific/Chatham');
assert.equal(setupElements.settingsTabs.children.length,4);assert.equal(setupElements.exchangeConnection.hidden,false);assert.equal(setupElements.botConfiguration.hidden,true);assert.equal(setupElements.dashboardCredentials,undefined);assert.equal(setupElements.username,undefined);
setupElements.settingsForm.listeners.submit({preventDefault(){}});assert.equal(setupElements.review.open,true);assert.match(setupElements.reviewDescription.textContent,/New configuration/);assert(!allText(setupElements.reviewValues).includes('Before'));
assert.equal(setupRequests.length,0,'Step two reviews settings without editing account credentials');
console.log('First-run step two passed without credential fields');

// The dashboard owns a native modal and accepts messages only from its settings frame.
const dashboard=execFileSync('python3',['-c',`import sys;sys.path.insert(0,'.');from app.webpage.scroll_ui import SCROLL_CSS,SCROLL_SCRIPT;from app.webpage.design_system import DESIGN_CSS;from app.webpage.templates import dashboard_page;print(dashboard_page())`],{cwd:root,encoding:'utf8'});
const modalScript=dashboard.match(/<script data-ui-settings>([\s\S]*?)<\/script>/)[1];
const modalElements=Object.fromEntries(['settingsDialog','settingsFrame','openSettings','closeSettings'].map(id=>[id,new Element()]));
const frameWindow={},events={};let footerActions=0;modalElements.settingsFrame.contentWindow=frameWindow;let reloads=0;
const modalWindow={location:{origin:'http://dashboard.test',href:'',reload(){reloads++}},addEventListener(name,fn){events[name]=fn}};
let scheduleRefreshes=0;modalWindow.DCA_DASHBOARD_ACTIONS={refreshSchedule(){scheduleRefreshes++},withdraw(){footerActions++},export(){footerActions++}};
vm.runInNewContext(modalScript,{fetch:async()=>({ok:true}),document:{getElementById:id=>modalElements[id]},window:modalWindow});
modalElements.openSettings.listeners.click();assert.equal(modalElements.settingsDialog.open,true);assert.equal(modalElements.settingsFrame.src,'/settings?embedded=1');
events.message({origin:'http://untrusted.test',source:frameWindow,data:{type:'dca-settings-action',action:'withdraw'}});assert.equal(footerActions,0);events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-settings-action',action:'withdraw'}});assert.equal(footerActions,1);
events.message({origin:'http://untrusted.test',source:frameWindow,data:{type:'dca-transactions-updated'}});assert.equal(scheduleRefreshes,0);events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-transactions-updated'}});assert.equal(scheduleRefreshes,1);assert.equal(reloads,0,'Pause refresh must retain the settings draft');
assert.equal(modalElements.settingsFrame.style.visibility,'hidden');
events.message({origin:'http://untrusted.test',source:frameWindow,data:{type:'dca-settings-ready'}});assert.equal(modalElements.settingsFrame.style.visibility,'hidden');
events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-settings-ready'}});assert.equal(modalElements.settingsFrame.style.visibility,'visible');
modalElements.closeSettings.listeners.click();assert.equal(modalElements.settingsDialog.open,false);
modalElements.settingsDialog.listeners.close();assert.equal(modalElements.settingsFrame.src,'about:blank','Closing must clear sensitive form fields');
events.message({origin:'http://untrusted.test',source:frameWindow,data:{type:'dca-settings-saved'}});assert.equal(reloads,0);
events.message({origin:'http://dashboard.test',source:{},data:{type:'dca-settings-saved'}});assert.equal(reloads,0);
events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-settings-saved'}});assert.equal(reloads,1);
events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-settings-auth-required'}});assert.equal(modalWindow.location.href,'/');
const closeRequests=[];frameWindow.postMessage=(data,origin)=>closeRequests.push({data,origin});
modalElements.openSettings.listeners.click();events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-settings-dirty',dirty:true}});
modalElements.closeSettings.listeners.click();assert.equal(modalElements.settingsDialog.open,true);assert.equal(closeRequests.at(-1).data.type,'dca-settings-request-close');
let prevented=false;modalElements.settingsDialog.listeners.cancel({preventDefault(){prevented=true}});assert(prevented);assert.equal(modalElements.settingsDialog.open,true);
events.message({origin:'http://dashboard.test',source:frameWindow,data:{type:'dca-settings-close'}});assert.equal(modalElements.settingsDialog.open,false);
console.log('Settings modal passed: open/close, secret cleanup, origin/source checks and save/auth handling');

// Settings share dashboard scroll behavior, including resize and disappearing edge hints.
const scrollSnippet=page.match(/<script data-ui-scroll-areas>([\s\S]*?)<\/script>/)[1];
const scrollClasses=new Set(),scrollEvents={};let resizeScroll,finishScroll;
const area={clientWidth:280,scrollWidth:760,scrollLeft:0,firstElementChild:{},classList:{toggle(name,on){on?scrollClasses.add(name):scrollClasses.delete(name)},add(name){scrollClasses.add(name)},remove(name){scrollClasses.delete(name)}},addEventListener(name,fn){scrollEvents[name]=fn}};
vm.runInNewContext(scrollSnippet,{document:{querySelectorAll:selector=>selector==='.horizontal-scroll'?[area]:[]},ResizeObserver:class{constructor(fn){resizeScroll=fn}observe(){}},WeakMap,setTimeout:fn=>{finishScroll=fn;return 1},clearTimeout(){}});
assert(scrollClasses.has('has-overflow'));assert(scrollClasses.has('has-more-right'));
area.scrollLeft=480;scrollEvents.scroll();assert(!scrollClasses.has('has-more-right'));assert(scrollClasses.has('is-scrolling'));finishScroll();assert(!scrollClasses.has('is-scrolling'));
area.clientWidth=900;resizeScroll();assert(!scrollClasses.has('has-overflow'));
assert(!page.includes('grid-auto-flow:column'));assert(page.includes('grid-auto-flow:row'));assert(page.includes('overflow-x:hidden;overflow-y:auto'));assert(page.includes('class="settings-fields"'));
assert(page.includes('id="settingsTabs" class="settings-tabs horizontal-scroll"'));assert(page.includes('white-space:nowrap;overflow-wrap:normal'));
console.log('Settings reflow passed: vertical-only fields, single-line tabs and shared dashboard scroll behavior');

// All native dialogs lock their own page and restore its exact scroll position.
const lockScript=page.match(/<script data-ui-dialog-lock>([\s\S]*?)<\/script>/)[1];
class InlineStyle{
 constructor(text){this.cssText=text}
 get cssText(){return this._text}
 set cssText(text){for(const key of Object.keys(this))delete this[key];this._text=text;for(const item of text.split(';')){const [key,value]=item.split(':');if(key&&value)this[key.trim().replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=value.trim()}}
}
const background={style:new InlineStyle('color:red')},rootElement={clientWidth:980,style:new InlineStyle('scroll-behavior:smooth')};
const modalA={open:false},modalB={open:false},restored=[];let updateModal;
vm.runInNewContext(lockScript,{document:{body:background,documentElement:rootElement,querySelectorAll:()=>[modalA,modalB]},window:{innerWidth:1000,scrollX:30,scrollY:420,getComputedStyle:()=>({paddingRight:'5px'}),scrollTo:(x,y)=>restored.push([x,y])},MutationObserver:class{constructor(fn){updateModal=fn}observe(){}}});
modalA.open=true;updateModal();assert.equal(background.style.position,'fixed');assert.equal(background.style.top,'-420px');assert.equal(background.style.paddingRight,'25px');assert.equal(rootElement.style.overflow,'hidden');
modalB.open=true;updateModal();modalA.open=false;updateModal();assert.equal(restored.length,0,'Another open dialog keeps the page locked');
modalB.open=false;updateModal();assert.deepEqual(restored,[[30,420]]);assert.equal(background.style.cssText,'color:red');assert.equal(background.style.position,undefined);assert.equal(rootElement.style.scrollBehavior,'smooth');
console.log('Dialog scroll lock passed: nested dialogs, scrollbar compensation and position/style restoration');

// German presentation uses the same operational values and preserves user-entered names.
const germanCatalog=JSON.parse(execFileSync('python3',['-c',"from pathlib import Path;print(Path('app/webpage/locales/de.json').read_text())"],{cwd:root,encoding:'utf8'}));
const germanElements={};
class GermanElement extends Element{append(...children){for(const child of children){child.parentElement=this;this.children.push(child);if(child.id)germanElements[child.id]=child}}}
for(const match of page.matchAll(/<(\w+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){const el=new GermanElement(match[1]);el.id=match[3];el.type=(match[2].match(/type="([^"]+)"/)||[])[1]||'';if(match[2].includes('data-setting'))el.dataset.setting='';germanElements[el.id]=el}
const germanContext=vm.createContext({DCA_I18N:{language:'de',catalog:germanCatalog},document:{documentElement:{dataset:{}},getElementById:id=>germanElements[id],createElement:tag=>new GermanElement(tag),querySelectorAll:()=>Object.values(germanElements).filter(el=>'setting'in el.dataset)},location:{href:''},setTimeout:fn=>fn(),fetch:async()=>({ok:true,json:async()=>({saved:true})})});
const i18nCode=execFileSync('python3',['-c',"from pathlib import Path;print(Path('app/webpage/static/i18n.js').read_text())"],{cwd:root,encoding:'utf8'});
vm.runInContext(i18nCode,germanContext);
assert.equal(germanContext.DCA_I18N.t('Available EUR balance on exchange'),'Verfügbares EUR-Guthaben auf der Börse');
assert.equal(germanContext.DCA_I18N.t('BTC is sent to the address saved in Kraken under “Before”.'),'BTC werden an die bei Kraken unter „Before“ gespeicherte Adresse gesendet.');
assert.equal(germanContext.DCA_I18N.t(123.45),123.45);
vm.runInContext(script.replace('"language": "en"','"language": "de"'),germanContext);
assert.deepEqual(germanElements.settingsTabs.children.map(x=>x.textContent),['Bot-Konfiguration','Börse','Dashboard','Backup']);
assert.equal(germanElements.withdraw_thresholdLabel.textContent,'Automatische Auszahlungsschwelle (EUR)');
assert.equal(germanElements.language.value,'de');assert.equal(germanElements.quote.value,'EUR');
germanElements.username.value='Before';germanElements.settingsForm.listeners.submit({preventDefault(){}});
assert.match(allText(germanElements.reviewValues),/Before/);assert.match(allText(germanElements.reviewValues),/Bisher/);
assert(!allText(germanElements.reviewValues).includes('Vorher'));
assert.equal(germanElements.settingsContent.scrollTop,0);
console.log('German settings passed: translated labels, locale, stable exchange values and unchanged user input');

// Closing with drafts requires the in-page discard dialog; no secrets are sent to the parent.
germanElements.username.value='Unsaved name';vm.runInContext('updateDirty();requestSettingsClose()',germanContext);
assert.equal(germanElements.unsavedChanges.hidden,false);assert.equal(germanElements.discardDialog.open,true);
germanElements.keepEditing.listeners.click();assert.equal(germanElements.discardDialog.open,false);
vm.runInContext('requestSettingsClose()',germanContext);germanElements.discardChanges.listeners.click();
assert.equal(germanElements.unsavedChanges.hidden,true);assert.equal(germanElements.discardDialog.open,false);
germanElements.live.checked=false;germanElements.withdrawals_enabled.checked=true;vm.runInContext('updateDependencies()',germanContext);
assert.equal(germanElements.withdraw_threshold.disabled,false);assert.equal(germanElements.withdrawals_enabled.disabled,false);
germanElements.withdrawals_enabled.checked=false;vm.runInContext('updateDependencies()',germanContext);assert.equal(germanElements.withdraw_threshold.disabled,true);
assert.match(germanElements.withdraw_thresholdHint.textContent,/Aktiviere automatische/);
console.log('Settings drafts passed: keep/discard guard and dependent values retained');

// Settings footer actions forward only to the authenticated parent and consume its feedback.
const footerElements={},footerGet=id=>footerElements[id]??=new Element(),footerMessages=[],footerEvents={};
const footerParent={postMessage:(data,origin)=>footerMessages.push({data,origin})};
vm.runInNewContext(script.slice(script.indexOf('// Account actions use'),script.indexOf('let restorePayload=null;')),{initial:{complete:true,embedded:true,settings:{manual_withdrawal_enabled:true,parqet_enabled:true}},$:footerGet,t:value=>value,location:{origin:'https://dashboard.test'},window:{parent:footerParent,addEventListener:(name,fn)=>footerEvents[name]=fn}});
assert.equal(footerGet('settingsQuickActions').hidden,false);footerGet('settingsWithdraw').listeners.click();assert.equal(footerMessages[0].data.action,'withdraw');assert.equal(footerGet('settingsExport').disabled,true);
footerEvents.message({origin:'https://untrusted.test',source:footerParent,data:{type:'dca-dashboard-action-feedback',message:'bad',busy:false}});assert.equal(footerGet('settingsExport').disabled,true);
footerEvents.message({origin:'https://dashboard.test',source:footerParent,data:{type:'dca-dashboard-action-feedback',message:'Exchange unavailable',error:true,busy:false}});assert.equal(footerGet('settingsActionMessage').textContent,'Exchange unavailable');assert.equal(footerGet('settingsExport').disabled,false);footerGet('dismissSettingsAction').listeners.click();assert.equal(footerGet('settingsActionFeedback').hidden,true);
console.log('Settings footer passed: saved-config actions, trusted parent feedback and dismissal');
