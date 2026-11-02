// Run with node tests/test_dashboard.cjs; stdlib only, no browser or exchange IO.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
const html=JSON.parse(execFileSync(process.env.PYTHON||'python3',['-c',`import json
import sys;sys.path.insert(0,'.');from app.webpage.scroll_ui import SCROLL_CSS,SCROLL_SCRIPT;from app.webpage.design_system import DESIGN_CSS
from app.webpage.templates import dashboard_page;print(json.dumps(dashboard_page()))`],{encoding:'utf8'}));
const script=html.split('<script>')[1].split('</script>')[0];
class Element{
 constructor(){this.attributes={};this.value='';this.children=[];this.handlers={};this.textContent='';this.disabled=false;this.classList={toggle(){},add(){},remove(){}}}
 setAttribute(name,value){this.attributes[name]=String(value);this[name]=value;if(name==='hidden')this.hidden=true}
 getAttribute(name){return this.attributes[name]??null}
 removeAttribute(name){delete this.attributes[name];delete this[name];if(name==='hidden')this.hidden=false}
 appendChild(e){this.children.push(e)} append(...e){this.children.push(...e)} replaceChildren(...e){this.children=e}
 click(){this.clicked=true}
 showModal(){this.open=true} close(value=''){this.returnValue=value;this.open=false;this.handlers.close?.()}
 set innerHTML(v){this.children=[]} addEventListener(event,handler){this.handlers[event]=handler}
}
const actionFeedbacks=[];
const elements={},get=id=>{assert(!["balance","balanceValue"].includes(id),"Removed portfolio element must not be accessed");return elements[id]??=new Element()};get('pageSize').value=html.match(/<option selected>(\d+)<\/option>/)[1];
get('settingsFrame').contentWindow={postMessage:message=>actionFeedbacks.push(message)};
get('reportFrom').value='2020-10-01T12:34:56Z';
const records=Array.from({length:45},(_,i)=>({activityId:String(i),datetime:'2026-10-22T12:00:00Z',type:'Buy',identifier:'BTC',shares:'.001',currency:i<22?'EUR':'USD',price:i<22?'80000':'100000',amount:i<22?'80':'100',fee:i<22?'.2':'.25'}));
const stored=new Map([['bitcoinDcaMonthlyDeposit','999']]);let expiryCallback;let configuredMonthlyDeposit='',forecastSaveFails=false;const forecastSaves=[];
let forecastAt='2027-01-10T12:00:00Z',automaticWithdrawals=true;
let reportMarketAt=null,scheduleMarket=null,configuredOrder="0",effectiveOrder="0.00006";const dashboardPollTimers=[];let dashboardRefreshSeconds=30;
const requests=[];let waitingStartup=false,waitingDeposit=false,reportFails=false,scheduleFails=false,checks=0,eurOnly=false,priceUnavailable=false,invalidUsdRate=false,withdrawalUnavailable=false,configuredDisplayCurrency="EUR",withdrawalExchange="KRAKEN",withdrawalTarget="Example wallet",withdrawalNetwork="BTC",withdrawalHistoryEmpty=false;
const response=data=>({ok:true,json:async()=>data});
const context={document:{getElementById:get,createElement:()=>new Element()},localStorage:{getItem:key=>stored.get(key)??null,setItem:(key,value)=>stored.set(key,value)},Intl,Date,URL,console,alert(){throw Error('Withdrawal must not use a browser alert')},confirm:()=>false,setInterval(){},setTimeout(fn,ms){if(fn.name==='refreshPurchaseSchedule'){dashboardPollTimers.push(ms);return dashboardPollTimers.length}if(ms===120000){expiryCallback=fn;return 1}queueMicrotask(fn)},clearTimeout(){},window:{location:{reload(){throw Error('Unexpected reload')}}},fetch:async(url,options)=>{
 requests.push(url);const parsed=new URL(url,'http://example.test');
 if(parsed.pathname==='/api/schedule'&&scheduleFails)throw Error('Schedule offline');
 if(parsed.pathname==='/api/settings/report-period')return response({from:JSON.parse(options.body).from});
 if(parsed.pathname==='/api/settings/forecast'){const data=JSON.parse(options.body);forecastSaves.push(data);if(forecastSaveFails)return {ok:false,json:async()=>({error:'Forecast save failed'})};configuredMonthlyDeposit=data.monthlyDeposit;return response({monthlyDeposit:configuredMonthlyDeposit})}
 if(parsed.pathname==='/api/schedule')return response({accountMarketPrice:scheduleMarket,configuredBuyAmount:configuredOrder,effectiveBuyAmount:effectiveOrder,dashboardRefreshSeconds,estimatedWithdrawalAt:forecastAt,expectedMonthlyDeposit:configuredMonthlyDeposit,quote:'EUR',exchange:'KRAKEN',quoteBalance:'72.7719',nextDepositAt:'2026-11-01T00:00:00+01:00',purchaseCurrencyPrice:'84000',withdrawalsEnabled:automaticWithdrawals,withdrawalThreshold:'1000',btcBalance:'.00379',balanceUpdatedAt:'2026-10-29T12:00:00Z',nextPurchaseAt:waitingDeposit||waitingStartup?null:new Date(Date.now()+3600000).toISOString(),startupDelayActive:waitingStartup,nextPurchaseStatus:waitingStartup?'Waiting for startup delay':waitingDeposit?'Waiting for deposit':'Scheduled',serverTime:new Date().toISOString(),timezone:'Europe/Berlin'});
 if(parsed.pathname==='/api/export.csv')return {ok:true,blob:async()=>new Blob(['fixture CSV'])};
 if(parsed.pathname==='/api/withdrawals')return response(withdrawalHistoryEmpty?[]:[{timestamp:Date.parse('2026-10-20T12:00:00Z')},{timestamp:Date.parse('2026-10-23T12:00:00Z')}]);
 if(parsed.pathname==='/api/withdrawal/config')return response({enabled:!withdrawalUnavailable,exchange:withdrawalExchange,target:withdrawalTarget,network:withdrawalNetwork,destination:'fictional wallet',reason:withdrawalUnavailable?'Manual withdrawal is unavailable: set KRAKEN_WITHDRAW_KEY to your saved Bitcoin withdrawal method in .env.':''});
 if(parsed.pathname==='/api/market-price'&&parsed.searchParams.get('currency')==='USD')return response({price:'88000',conversionRate:'1.1',conversionRates:{EUR:'1.1',USD:'1'},updatedAt:reportMarketAt??Date.now()/1000});
 if(parsed.pathname==='/api/market-price')return priceUnavailable?{ok:false,json:async()=>({error:'offline'})}:response({price:'80000',conversionRate:'1',conversionRates:{EUR:'1',USD:invalidUsdRate?'invalid':'0.9'},updatedAt:reportMarketAt??Date.now()/1000});
 if(parsed.pathname==='/api/analytics'){
  if(reportFails)throw Error('Report offline');
  const limit=Number(parsed.searchParams.get('limit'))||10,pages=Math.ceil(records.length/limit);
  const page=Math.max(1,Math.min(pages,Number(parsed.searchParams.get('page'))||1));
  return response({quote:'EUR',exchange:'KRAKEN',configuration:{displayCurrency:configuredDisplayCurrency,liveTrading:true,buyAmount:0,depositDay:1,withdrawalsEnabled:false,withdrawalThreshold:1000},snapshot:{price:80000,balance:'.045',updatedAt:new Date().toISOString()},depositsByCurrency:{EUR:{count:1,amount:'200'}},summary:{depositCount:1,buyCount:45,boughtBtc:'.045',withdrawnBtc:0,withdrawalCount:0,pendingWithdrawalCount:0,netBtc:'.045'},summaryByCurrency:eurOnly?{EUR:{buyVolume:3600,tradeFees:9,withdrawalFees:0}}:{EUR:{buyVolume:1760,tradeFees:4.4,withdrawalFees:0},USD:{buyVolume:2300,tradeFees:5.75,withdrawalFees:0}},activities:records.slice((page-1)*limit,page*limit),pagination:{page,pageSize:limit,total:45,pages}});
 }
 if(parsed.pathname==='/api/withdrawal/preview')return response({jobId:'fictional-job'});
 if(parsed.pathname==='/api/withdrawal/jobs/fictional-job')return response(++checks===1?{state:'queued'}:{state:'completed',result:{token:'single-use'}});
 throw Error('Unexpected URL '+url);
}};
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(setImmediate)};
(async()=>{
 vm.createContext(context);vm.runInContext(script,context);await settle();
 assert.equal(get('investedTotal').textContent,'€3,839.58');
 assert(html.includes('<details open class="activities-section period-activities"'));assert(html.includes('>Period activities</summary>'));
 withdrawalHistoryEmpty=true;await context.window.DCA_DASHBOARD_ACTIONS.export();assert.equal(get('exportDialog').open,true);assert.equal(get('exportDialogMessage').textContent,'');assert.equal(get('confirmExport').disabled,false);await get('confirmExport').handlers.click();assert.match(get('exportDialogMessage').textContent,/No confirmed withdrawal/);get('cancelExport').handlers.click();
 withdrawalHistoryEmpty=false;await context.window.DCA_DASHBOARD_ACTIONS.export();assert.equal(get('exportInterval').children.length,2);assert(get('exportInterval').children[0].textContent.includes('First recorded purchase'));assert.equal(get('exportDialogMessage').textContent,'');const chosenExport=get('exportInterval').children[0].value;get('exportInterval').value=chosenExport;await get('confirmExport').handlers.click();const [exportStart,exportEnd]=chosenExport.split(',');assert(requests.includes('/api/export.csv?start='+exportStart+'&end='+exportEnd));assert.equal(get('exportDialog').open,false);
 const backgroundRefresh=vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(get('scheduleFeedback').textContent,'','Background polling must not insert a layout-shifting status paragraph');assert(!html.includes('id="scheduleFeedback"'));await backgroundRefresh;
 assert.equal(dashboardPollTimers.at(-1),30000);dashboardRefreshSeconds=75;await vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(dashboardPollTimers.at(-1),75000);dashboardRefreshSeconds=30;
 const previousForecast=get('estimatedWithdrawalAt').textContent;forecastAt='2027-02-15T09:00:00Z';await vm.runInContext('refreshPurchaseSchedule()',context);assert.notEqual(get('estimatedWithdrawalAt').textContent,previousForecast);assert.equal(vm.runInContext('estimatedWithdrawalTimestamp',context),Date.parse(forecastAt));assert(html.indexOf('id="forecastAssumptions"')>html.indexOf('id="notesHeading"'),'Forecast assumptions belong in calculation notes');assert(!html.includes('Bot details'));assert(!html.includes('id="thresholdNote"'));automaticWithdrawals=false;await vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(get('withdrawalHeading').textContent,'Automatic withdrawal disabled');automaticWithdrawals=true;await vm.runInContext('refreshPurchaseSchedule()',context);assert.notEqual(get('withdrawalHeading').textContent,'Automatic withdrawal disabled');const savedForecast=forecastAt;forecastAt=null;await vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(get('estimatedWithdrawalAt').textContent,'Not estimated');assert.equal(get('withdrawalCountdown').hidden,true);assert.equal(get('withdrawalCountdown').textContent,'');forecastAt=savedForecast;await vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(get('withdrawalCountdown').hidden,false);
 const pageBeforePrice=vm.runInContext('currentPage',context);
 scheduleMarket={price:'100000',currency:'EUR',quoteCurrency:'EUR',conversionRate:'1',conversionRates:{EUR:'1',USD:'.9'},updatedAt:Date.now()/1000};
 configuredOrder='0.00001';await vm.runInContext('refreshPurchaseSchedule()',context);
 assert.equal(get('periodValue').textContent,'€4,500.00','Account price refresh must update the current period valuation');
 assert.equal(get('orderSummary').textContent,'0.00006 BTC','Show effective quantity when configured below the minimum');
 assert.equal(vm.runInContext('currentPage',context),pageBeforePrice,'Price updates retain the selected activity page');
 scheduleMarket.updatedAt=Date.now()/1000+60;reportMarketAt=Date.now()/1000+120;configuredOrder='0';await vm.runInContext('loadAnalytics()',context);
 assert.equal(get('periodValue').textContent,'€3,600.00','A newer report market response must beat an older cached schedule quote');
 scheduleMarket=null;reportMarketAt=null;vm.runInContext('lastAccountMarket=null',context);
 assert.equal(get('depositVolume').textContent,'€200.00');assert(!html.includes('id="depositCount"'));assert(!html.includes('id="withdrawCount"'));
 assert(html.includes('class="report-primary"'));assert(html.includes('Amount of BTC purchases</div><div class="value" id="buyCount"'));assert.equal(get('buyCount').textContent,45);assert(html.indexOf('id="investedTotal"')<html.indexOf('id="depositVolume"'));
 assert(!html.includes('id="nextPurchaseStatus"'));waitingDeposit=true;await vm.runInContext('refreshPurchaseSchedule()',context);
 assert.equal(get('nextPurchaseAt').textContent,'Waiting for deposit');assert.equal(get('nextPurchaseCountdown').textContent,'');assert.equal(get('nextPurchaseCountdown').hidden,true);
 vm.runInContext('renderPurchaseCountdown()',context);assert.equal(get('nextPurchaseCountdown').textContent,'');assert.equal(get('nextPurchaseCountdown').hidden,true);waitingDeposit=false;await vm.runInContext('refreshPurchaseSchedule()',context);
 waitingStartup=true;await vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(get('nextPurchaseAt').textContent,'Waiting for startup delay');assert.equal(get('purchaseOrderDetails').hidden,true);assert.equal(get('nextPurchaseCountdown').hidden,true);assert.equal(get('nextPurchaseCountdown').textContent,'');waitingStartup=false;await vm.runInContext('refreshPurchaseSchedule()',context);assert.equal(get('nextPurchaseCountdown').hidden,false);
 assert(!html.includes('id="monthlyDeposit"'),'Forecast amount is edited in Settings only');
 assert(!html.includes('id="forecastDepositSummary"'));assert(!html.includes('id="planWithdrawalTarget"'));
 configuredMonthlyDeposit='350';await vm.runInContext('refreshPurchaseSchedule()',context);
 assert(get('start').value&&get('end').value,'Both dates must initialize for the selected interval');
 assert.equal(get('end').value,vm.runInContext('localInput(Date.now())',context),'Each page load uses the current end time');
 assert.equal(get('interval').value,'','A range ending now must not claim to be a closed withdrawal interval');
 assert.equal(get('quoteBalance').textContent,'€72.77');assert.match(get('nextDepositAt').textContent,/Next deposit:/);assert(Math.abs(get('withdrawalProgress').value-31.836)<1e-9);
 assert.equal(get('quoteBalanceLabel').textContent,'Available EUR balance');
 assert(html.indexOf('id="quoteBalance"')<html.indexOf('id="nextPurchaseAt"'),'Fiat balance precedes next purchase');
 vm.runInContext('displayCurrency="USD"',context);await vm.runInContext('refreshPurchaseSchedule()',context);
 assert.equal(get('quoteBalance').textContent,'€72.77','Balance stays in the exchange trading currency');
 vm.runInContext('displayCurrency="EUR"',context);
 assert.equal(get('pageSize').value,'10');
 assert(html.includes('<option>5</option>'),'5 entries must be selectable');
 assert(get('pageInfo').textContent.includes('1–10 of 45'));
 assert.equal(get('activities').children.length,10);
 assert.equal(get('buyVolume').textContent,'€3,830.00');
 get('pageNumber').value='3';get('pageJump').handlers.submit({preventDefault(){}});await settle();
 assert(get('pageInfo').textContent.includes('21–30 of 45'));
 assert(get('activities').children[2].children[4].textContent.includes('90.00'),'USD rows use their own conversion rate');
 assert.equal(get('pageNumber').max,5);
 const count=requests.length;
 for(const value of ['0','6','1.5','invalid']){get('pageNumber').value=value;get('pageJump').handlers.submit({preventDefault(){}})}
 await settle();assert.equal(requests.length,count,'Invalid jumps must not send requests');
 get('pageNumber').value='5';get('pageJump').handlers.submit({preventDefault(){}});await settle();
 assert(get('pageInfo').textContent.includes('41–45 of 45'));assert.equal(get('activities').children.length,5);assert.equal(get('activities').children.filter(row=>row.className==='activity-placeholder').length,0);assert(get('nextPage').disabled);
 get('pageSize').value='100';get('pageSize').handlers.change();await settle();assert.equal(get('activities').children.length,45,'A page size above the total must not add blank rows');
 get('pageSize').value='5';get('pageSize').handlers.change();await settle();
 assert(get('pageInfo').textContent.includes('1–5 of 45'));assert.equal(get('pageNumber').value,1);assert.equal(get('pageNumber').max,9);
 get('nextPage').handlers.click();await settle();assert(get('pageInfo').textContent.includes('6–10 of 45'));
 get('previousPage').handlers.click();await settle();assert(get('pageInfo').textContent.includes('1–5 of 45'));
 assert.equal(requests.filter(u=>u.startsWith('/api/analytics')).length,8,'Each navigation must load exactly once, plus the explicit report reload in the price regression');
 const preview=await vm.runInContext("withdrawalPost('/api/withdrawal/preview',{})",context);
 assert.equal(preview.token,'single-use');assert.equal(checks,2);
 assert.equal(requests.filter(u=>u==='/api/withdrawal/preview').length,1);
 eurOnly=true;await vm.runInContext('loadAnalytics()',context);
 assert.equal(get('buyVolume').textContent,'€3,600.00','EUR string rate must retain monetary totals');
 assert.equal(get('error').textContent,'','EUR-only history must not report mixed currencies');
 priceUnavailable=true;await vm.runInContext('loadAnalytics()',context);
 assert(!html.includes('exchangeCheckTooltip'));assert(get('exchangeCheckedAt').textContent.startsWith('Exchange last checked '));assert(html.indexOf('id="exchangeCheckedAt"')>html.indexOf('id="spot"'));
 assert(!html.includes('id="priceFeedback"'));
 assert.equal(get('buyVolume').textContent,'€3,600.00','EUR totals need no external conversion rate');
 assert(!get('error').textContent.includes('multiple currencies'));
 eurOnly=false;priceUnavailable=false;invalidUsdRate=true;await vm.runInContext('loadAnalytics()',context);
 assert.equal(get('buyVolume').textContent,'—','Invalid foreign rates must not produce incorrect totals');
 assert.equal(get('error').textContent,'A required currency conversion is unavailable; monetary totals are hidden.');
 assert(!html.includes('<sup'),'Superscript references are no longer displayed');
 withdrawalUnavailable=true;
 const submissions=requests.filter(u=>u==='/api/withdrawal/preview'||u==='/api/withdrawal/confirm').length;
 await context.window.DCA_DASHBOARD_ACTIONS.withdraw();
 assert(actionFeedbacks.some(item=>item.action==='withdraw'&&item.error&&item.message.includes('KRAKEN_WITHDRAW_KEY')),'Missing configuration reaches Settings');
 assert(!html.includes('id="manualWithdraw"'),'Manual action is available in Settings only');
 assert(html.includes('<dialog'),'Financial confirmation uses a styled dialog');
 assert(!/\b(confirm|alert|prompt)\(/.test(script),'No browser dialogs remain');
 assert.equal(actionFeedbacks.at(-1).busy,false,'Settings action is reenabled after feedback');
 assert.equal(requests.filter(u=>u==='/api/withdrawal/preview'||u==='/api/withdrawal/confirm').length,submissions,'Missing configuration cannot submit financial actions');

 const lastBalance=get('quoteBalance').textContent;
 scheduleFails=true;await vm.runInContext('refreshPurchaseSchedule()',context);
 assert.equal(get('quoteBalance').textContent,lastBalance);
 assert.equal(get('scheduleFeedback').textContent,'');assert.equal(get('botStatusLabel').textContent,'Connection unavailable; showing previous values');
 scheduleFails=false;
 const lastRows=get('activities').children;
 reportFails=true;await vm.runInContext('loadAnalytics()',context);
 assert.equal(get('activities').children,lastRows,'Failed refresh preserves existing rows');
 assert.equal(get('error').textContent,'Report offline');reportFails=false;
 vm.runInContext('activityRows=[];activityTotal=0;activityPages=1;currentPage=1;renderActivities()',context);
 assert.equal(get('activities').children.length,1,'Empty periods show only the no-activity message');assert.equal(get('activities').children[0].children[0].textContent,'No activity in this period.');assert.equal(get('activities').children[0].children[0].colSpan,7);
 assert.equal(get('activities').children.filter(row=>row.className==='activity-placeholder').length,0);
 assert(get('previousPage').disabled&&get('nextPage').disabled);
 assert.equal(vm.runInContext('activityMoney(null,1,"EUR")',context),'—');
 assert.equal(vm.runInContext('activityMoney("",1,"EUR")',context),'—');
 assert.equal(vm.runInContext('activityMoney("0",1,"EUR")',context),'€0.00');
 assert.equal(vm.runInContext('activityBtc(undefined)',context),'—');
 get('pageSize').value='20';get('start').value='2026-10-01T00:00';get('end').value='2026-10-29T12:00';get('interval').value='';
 vm.runInContext('saveReportView()',context);
 get('pageSize').value='10';get('start').value='';get('end').value='';vm.runInContext('restoreReportView()',context);
 assert.equal(get('pageSize').value,'20');assert.equal(get('start').value,vm.runInContext('localInput(Date.parse($("reportFrom").value))',context));
 assert.equal(get('end').value,vm.runInContext('localInput(Date.now())',context),'Saved end dates must not override the current time');
 stored.set('bitcoinDcaReportView',JSON.stringify({interval:'1,2',start:'2026-10-01T00:00',end:'2026-10-02T00:00',pageSize:'20'}));
 vm.runInContext('restoreReportView()',context);
 assert.equal(get('interval').value,'');assert.equal(get('end').value,vm.runInContext('localInput(Date.now())',context));

 for(const [id,days] of [['days30Range',30],['days90Range',90]]){await get(id).handlers.click();await settle();const expected=new Date(get('end').value);expected.setDate(expected.getDate()-days);assert.equal(Date.parse(get('start').value),expected.getTime());assert.equal(get(id)['aria-pressed'],'true')}
 for(const id of ['days30Range','days90Range']){const original=new Date(2026,10,2,15,0,52),result=vm.runInContext("rollingRangeStart('"+id+"',new Date(2026,10,2,15,0,52))",context);assert.equal(result.getHours(),original.getHours());assert.equal(result.getMinutes(),original.getMinutes());assert.equal(result.getSeconds(),original.getSeconds())}
 await get('oneYearRange').handlers.click();await settle();assert.equal(new Date(get('start').value).getFullYear(),new Date(get('end').value).getFullYear()-1);assert.equal(vm.runInContext("rollingRangeStart('oneYearRange',new Date(2024,1,29,12,34,56)).getDate()",context),28);
 await get('customRange').handlers.click();await settle();
 const beforeCancel=get('start').value,savedCount=requests.filter(url=>url==='/api/settings/report-period').length;
 await get('editCustomRange').handlers.click();assert.equal(get('rangeDialog').open,true);get('start').value='2026-10-03T10:00:00';get('start').handlers.change();get('cancelRange').handlers.click();assert.equal(get('start').value,beforeCancel);assert.equal(requests.filter(url=>url==='/api/settings/report-period').length,savedCount);
 await get('editCustomRange').handlers.click();get('interval').value=get('interval').children[1].value;get('interval').handlers.change();assert.equal(Date.parse(get('start').value),Number(get('interval').value.split(',')[0]));
 get('start').value='2026-10-04T11:12:13';get('start').handlers.change();get('rangeForm').handlers.submit({preventDefault(){}});await settle();
 assert.equal(get('rangeDialog').open,false);assert.equal(requests.filter(url=>url==='/api/settings/report-period').length,savedCount+1);
 const customStart=get('start').value,customEnd=get('end').value;await get('monthRange').handlers.click();await settle();await get('customRange').handlers.click();await settle();assert.equal(get('start').value,customStart);assert.equal(get('end').value,customEnd);assert.equal(get('rangeDialog').open,false);await get('yearRange').handlers.click();await settle();await get('editCustomRange').handlers.click();assert.equal(get('start').value,customStart);get('cancelRange').handlers.click();assert.equal(vm.runInContext('selectedQuickRange',context),'yearRange');await get('customRange').handlers.click();await settle();
 assert(!html.includes('id="refresh"'));assert(html.indexOf('id="start"')>html.indexOf('id="rangeDialog"'),'Date controls belong only in the period dialog');
 const persistedFrom=get('reportFrom').value;get('start').value='';vm.runInContext('restoreReportView()',context);
 assert.equal(get('start').value,vm.runInContext('localInput(Date.parse($("reportFrom").value))',context));
 assert.equal(Date.parse(persistedFrom),Date.parse('2026-10-04T11:12:13'));
 let decision=vm.runInContext('confirmWithdrawal({destination:"Example wallet",availableBtc:".01",feeBtc:".0001",netBtc:".0099"})',context);
 assert(get('confirmationDialog').open);assert.equal(get('confirmGross').textContent,'0.01 BTC');assert.equal(get('confirmFee').textContent,'0.0001 BTC');assert.equal(get('confirmNet').textContent,'0.0099 BTC');
 get('confirmationDialog').close('cancel');assert.equal(await decision,false);
 decision=vm.runInContext('confirmWithdrawal({destination:"Example wallet",availableBtc:".01",feeBtc:null,netBtc:null})',context);
 assert.equal(get('confirmFee').textContent,'Determined by the exchange');
 expiryCallback();assert.equal(await decision,false,'Expired previews cannot confirm');
 decision=vm.runInContext('confirmWithdrawal({destination:"Example wallet",availableBtc:".01"})',context);
 get('confirmationDialog').close('confirm');assert.equal(await decision,true);
 assert.equal(requests.filter(u=>u==='/api/withdrawal/confirm').length,0,'Dialog tests never submit a withdrawal');

 const originalFetch=context.fetch;let release;
 let hold=true;context.fetch=(url,options)=>{
  if(hold&&url.startsWith('/api/analytics')){hold=false;return new Promise(resolve=>{release=()=>originalFetch(url,options).then(resolve)})}
  return originalFetch(url,options);
 };
 invalidUsdRate=false;
 const rowsBefore=get('activities').children;
 const earlier=vm.runInContext('currentPage=1;loadAnalytics()',context);
 assert.equal(get('activities').children,rowsBefore,'Loading keeps current rows');
 assert.equal(get('reportFeedback').textContent,'');
 assert.equal(get('periodReport').ariaBusy,'true');
 await vm.runInContext('currentPage=2;loadAnalytics()',context);
 const latestRows=get('activities').children;release();await earlier;
 assert.equal(get('periodReport').ariaBusy,'false');
 assert.equal(get('activities').children,latestRows,'A late response cannot overwrite the newer report');
 context.fetch=originalFetch;
 withdrawalUnavailable=false;
 const cancelAction=context.window.DCA_DASHBOARD_ACTIONS.withdraw();await settle();
 assert(get('confirmationDialog').open,'Enabled manual withdrawal opens its confirmation dialog');
 get('confirmationDialog').close('cancel');await cancelAction;
 assert(!html.includes('id="withdrawMessage"'),'Runtime availability must never be cached in calculation notes');
 assert(actionFeedbacks.some(item=>item.action==='withdraw'&&item.message===''));assert.equal(actionFeedbacks.at(-1).busy,false);
 assert.equal(requests.filter(u=>u==='/api/withdrawal/confirm').length,0,'Cancel never submits a withdrawal');
 // Main panel state is restored and saved independently from report data.
 const panel={open:true,getAttribute:()=>"configurationHeading",addEventListener(event,fn){this.toggle=fn}};
 stored.set('bitcoinDcaPanels',JSON.stringify({configurationHeading:false}));
 const savedDocument=context.document;context.document={querySelectorAll:()=>[panel]};
 vm.runInContext(html.split('<script data-ui-view>')[1].split('</script>')[0],context);
 assert.equal(panel.open,false);panel.open=true;panel.toggle();
 assert.equal(JSON.parse(stored.get('bitcoinDcaPanels')).configurationHeading,true);
 context.document=savedDocument;

 const scrollClasses=new Set(),scrollEvents={};let resizeScroll;
 const scrollArea={clientWidth:300,scrollWidth:900,scrollLeft:0,firstElementChild:{},
  classList:{toggle(name,on){on?scrollClasses.add(name):scrollClasses.delete(name)},add(name){scrollClasses.add(name)},remove(name){scrollClasses.delete(name)}},
  addEventListener(name,fn){scrollEvents[name]=fn}};
 const previousDocument=context.document;
 context.document={querySelectorAll:selector=>selector==='.horizontal-scroll'?[scrollArea]:[]};
 context.ResizeObserver=class{constructor(fn){resizeScroll=fn}observe(){}};
 vm.runInContext(html.split('<script data-ui-scroll-areas>')[1].split('</script>')[0],context);
 assert(scrollClasses.has('has-more-right'),'Overflow shows the right edge hint');
 scrollArea.scrollLeft=600;scrollEvents.scroll();
 assert(!scrollClasses.has('has-more-right'),'Reaching the end removes the hint');
 scrollArea.scrollLeft=100;scrollEvents.scroll();assert(scrollClasses.has('has-more-right'));
 scrollArea.clientWidth=1000;resizeScroll();
 assert(!scrollClasses.has('has-more-right'));assert(!scrollClasses.has('has-overflow'));
 context.document=previousDocument;

 // Display currency comes from saved Settings, never a stale browser preference.
 assert(!html.includes('id="displayCurrency"'),'Currency selector moved out of the dashboard header');
 stored.set('bitcoinDcaDisplayCurrency','EUR');configuredDisplayCurrency='USD';invalidUsdRate=false;
 await vm.runInContext('loadAnalytics()',context);
 assert.equal(vm.runInContext('displayCurrency',context),'USD');
 assert(requests.some(u=>u.startsWith('/api/market-price?currency=USD')));
 assert(get('spot').textContent.includes('$'));
 assert.equal(vm.runInContext('activityStatus({type:"Buy"}).label',context),'Confirmed ✓');
 assert.equal(vm.runInContext('activityStatus({type:"Buy",simulated:true}).label',context),'Simulation');
 assert.equal(vm.runInContext('activityStatus({type:"TransferOut",withdrawalStatus:"completed"}).label',context),'Confirmed ✓');
 assert.equal(vm.runInContext('activityStatus({type:"TransferOut",withdrawalStatus:"submitted"}).label',context),'Pending');
 assert.equal(vm.runInContext('activityStatus({type:"TransferOut",withdrawalStatus:"failed"}).label',context),'Failed');
 assert.equal(vm.runInContext('activityStatus({type:"TransferOut"}).label',context),'Unverified');
 assert.equal(get('activities').children[0].children.length,7);
 assert.equal(get('activities').children[0].children[6].textContent,'Confirmed ✓');

 await vm.runInContext('loadWithdrawalConfiguration()',context);
 assert.equal(get('automaticWithdrawalDestination').textContent,get('withdrawalDestination').textContent);
 assert.match(get('automaticWithdrawalDestination').textContent,/Kraken under “Example wallet”/);
 withdrawalExchange='BITVAVO';withdrawalTarget='bc1-fictional-target';withdrawalNetwork='BTC';await vm.runInContext('loadWithdrawalConfiguration()',context);
 assert.match(get('automaticWithdrawalDestination').textContent,/bc1-fictional-target via BTC on Bitvavo/);
 withdrawalTarget='';await vm.runInContext('loadWithdrawalConfiguration()',context);
 assert.match(get('automaticWithdrawalDestination').textContent,/No withdrawal target is configured/);
 console.log('Dashboard regressions passed: interval dates, server pages, mixed-currency rows/totals and queued preview polling');
})().catch(e=>{console.error(e);process.exit(1)});

// Render a German report without translating exchange codes or changing arithmetic.
const germanElements={},germanGet=id=>germanElements[id]??=new Element();
germanGet('pageSize').value='10';
const germanContext=vm.createContext({DCA_I18N:{language:'de',catalog:JSON.parse(fs.readFileSync('app/webpage/locales/de.json','utf8'))},document:{getElementById:germanGet,createElement:()=>new Element()},localStorage:{getItem:()=>null,setItem(){}},Intl,Date,URL,console,setInterval(){},setTimeout(){},clearTimeout(){},window:{location:{reload(){}}},fetch:()=>new Promise(()=>{})});
vm.runInContext(fs.readFileSync('app/webpage/static/i18n.js','utf8'),germanContext);
vm.runInContext(script,germanContext);
vm.runInContext(`displayCurrency='EUR';activityRows=[{datetime:'2026-10-22T12:00:00Z',type:'Buy',purchaseStatus:'confirmed',shares:'.001',price:'80000',amount:'80',fee:'.2',currency:'EUR'}];activityTotal=1;activityPages=1;renderActivities()`,germanContext);
assert.equal(germanElements.activities.children[0].children[1].textContent,'Kauf');
assert.equal(germanElements.activities.children[0].children[6].textContent,'Bestätigt ✓');
assert.match(germanElements.pageInfo.textContent,/Einträge 1–1 von 1/);
assert.match(vm.runInContext("money(1234.5,'EUR')",germanContext),/1\.234,50/);
assert.equal(vm.runInContext("btc('.00006')",germanContext),'0,00006 BTC');
assert.equal(vm.runInContext('activityRows[0].type',germanContext),'Buy');
assert.equal(vm.runInContext('activityRows[0].currency',germanContext),'EUR');
console.log('German dashboard passed: labels, pagination, numbers and stable ledger values');


assert(!html.includes('id="accountFreshness"'));assert(html.indexOf('class="bot-status"')<html.indexOf('id="openSettings"'));assert(html.includes('Status:</span>'));

for(const tone of ['active','waiting','error']){vm.runInContext(`updateStatusLight('${tone}')`,germanContext);assert.equal(germanElements.botStatusLight.className,'status-light status-'+tone)}
vm.runInContext("updateStatusLight('unexpected')",germanContext);assert.equal(germanElements.botStatusLight.className,'status-light status-waiting');

assert.equal(vm.runInContext('activityStatus({type:"Deposit"}).label',context),"—");

assert.equal(vm.runInContext('activityStatus({type:"Deposit",depositStatus:"confirmed"}).label',context),"Confirmed ✓");
