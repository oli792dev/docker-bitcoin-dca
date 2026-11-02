const {t,locale}=typeof DCA_I18N!=="undefined"?DCA_I18N:{t:value=>value,locale:"en-GB"};

const $=id=>document.getElementById(id);
let quote="EUR", displayCurrency="", fxRate=1, activityRows=[], currentPage=1, activityTotal=0, activityPages=1, activityRates={};
function localInput(ms){const d=new Date(ms);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,19)}
function parseInput(el){return new Date(el.value).getTime()}
function money(v,c){try{return new Intl.NumberFormat(locale,{style:"currency",currency:c,maximumFractionDigits:2}).format(Number(v||0))}catch(e){return Number(v||0).toFixed(2)+" "+c}}
function btc(v){return Number(v||0).toLocaleString(locale,{minimumFractionDigits:0,maximumFractionDigits:8})+" BTC"}
function dateLabel(ms,timeZone){return new Date(ms).toLocaleString(locale,{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',...(timeZone?{timeZone}:{})})}
let exchangeBtcBalance=null, balanceDisplayPrice=null, balanceDisplayCurrency=null;
function renderExchangeBtcValue(){
 $("exchangeBtcValue").textContent=t(exchangeBtcBalance!==null&&balanceDisplayPrice>0&&balanceDisplayCurrency===displayCurrency?money(exchangeBtcBalance*balanceDisplayPrice,displayCurrency):"—");
}
let nextPurchaseTimestamp=null, estimatedWithdrawalTimestamp=null, scheduleClockOffset=0, nextPurchaseMessage="Not scheduled";
function renderCountdown(id, timestamp){
 const output=$(id);
 output.hidden=timestamp===null;
 if(timestamp===null){output.textContent="";return}
 let seconds=Math.max(0,Math.ceil((timestamp-Date.now()-scheduleClockOffset)/1000));
 if(!seconds){output.textContent=t("Due now");return}
 const days=Math.floor(seconds/86400);seconds%=86400;
 const hours=Math.floor(seconds/3600);seconds%=3600;
 const minutes=Math.floor(seconds/60),remaining=seconds%60;
 output.textContent=t((days?days+"d ":"")+String(hours).padStart(2,"0")+"h "+String(minutes).padStart(2,"0")+"m "+String(remaining).padStart(2,"0")+"s");
}
function renderPurchaseCountdown(){
 renderCountdown("nextPurchaseCountdown",nextPurchaseTimestamp);
 renderCountdown("withdrawalCountdown",estimatedWithdrawalTimestamp);
}
function renderWithdrawalProgress(balance,price,threshold,enabled){
 const known=enabled&&Number.isFinite(balance)&&price>0&&threshold>0;
 $('withdrawalProgress').hidden=!known;
 $('withdrawalProgress').value=known?Math.min(100,Math.max(0,balance*price/threshold*100)):0;
 $('withdrawalProgressLabel').textContent=known?t('{value} of {threshold}').replace('{value}',money(balance*price,quote)).replace('{threshold}',money(threshold,quote)):t(enabled?'Waiting for account check':'Automatic withdrawals disabled');
}
function updateStatusLight(tone){
 $('botStatusLight').className='status-light status-'+(['active','waiting','error'].includes(tone)?tone:'waiting');
}
async function refreshPurchaseSchedule(){
 const request=++scheduleRequest;
 try{
  const response=await fetch("/api/schedule");
  if(response.status===401){window.location.reload();return}
  if(!response.ok)throw new Error("Schedule unavailable");
  const schedule=await response.json();if(request!==scheduleRequest)return;const target=Date.parse(schedule.nextPurchaseAt),serverTime=Date.parse(schedule.serverTime);
  scheduleClockOffset=Number.isFinite(serverTime)?serverTime-Date.now():0;
  $('botStatusLabel').textContent=t(schedule.botStatusLabel||'Bot active');
  updateStatusLight(schedule.botStatusTone||(schedule.botStatusWarning?'error':'waiting'));
  if(schedule.accountMarketPrice){
   const market=schedule.accountMarketPrice;
   balanceDisplayPrice=Number(market.price);balanceDisplayCurrency=market.currency;
   $('spot').textContent=money(market.price,market.currency)+'/BTC';

   renderExchangeBtcValue();
  }
  const detail=schedule.forecastDetails;
  $('forecastProgress').textContent=detail?t('About {btc} BTC · {buys} purchases remaining'.replace('{btc}',Number(detail.remainingBtc).toLocaleString(locale,{maximumFractionDigits:8})).replace('{buys}',detail.remainingPurchases)):'';
  $('forecastAssumptions').hidden=!detail;
  if(detail)$('forecastAssumptionsText').textContent=t('BTC price: {price}. BTC per purchase: {quantity}. Threshold: {threshold}. Assumes unchanged price and fees. Monthly deposit: {amount}. Deposit: day {day}, {time} ({zone}).'.replace('{price}',money(detail.price,detail.quote)).replace('{quantity}',btc(detail.quantity)).replace('{threshold}',money(detail.threshold,detail.quote)).replace('{amount}',detail.monthlyDeposit?money(detail.monthlyDeposit,detail.quote):t('Not configured')).replace('{day}',detail.depositDay).replace('{time}',detail.depositTime).replace('{zone}',detail.timezone));
  const depositDate=Date.parse(schedule.nextDepositAt);
  $('nextDepositAt').textContent=Number.isFinite(depositDate)?t('Next deposit: {date}').replace('{date}',dateLabel(depositDate,schedule.timezone||'UTC')):'';
  if(schedule.configuredBuyAmount!==undefined){
   const minimumMode=Number(schedule.configuredBuyAmount)===0;
   const effective=Number(schedule.effectiveBuyAmount);
   $("orderSummary").textContent=t(schedule.finalPurchase&&effective>0?btc(effective):minimumMode?(effective>0?btc(effective):"—"):btc(schedule.configuredBuyAmount));
   $("orderSummaryNote").textContent=t(schedule.finalPurchase?"Final purchase · uses remaining fiat":minimumMode?"(exchange minimum)"+(effective>0?"":" · waiting for account check"):"");
  }
  $("quoteBalanceLabel").textContent=t("Available "+schedule.quote+" balance");
  const balanceKnown=schedule.quoteBalance!==null&&schedule.quoteBalance!==undefined&&Number.isFinite(Number(schedule.quoteBalance));
  $("quoteBalance").textContent=t(balanceKnown?money(schedule.quoteBalance,schedule.quote):"—");
  const checkedAt=Date.parse(schedule.balanceUpdatedAt);
  const exchangeChecked=t(Number.isFinite(checkedAt)?'Exchange last checked {date}':'Waiting for account check').replace('{date}',dateLabel(checkedAt,schedule.timezone||'UTC'));
  $('exchangeCheckedAt').textContent=exchangeChecked;
  nextPurchaseTimestamp=Number.isFinite(target)?target:null;

  nextPurchaseMessage=schedule.nextPurchaseStatus||"Not scheduled";
  $('purchaseOrderDetails').hidden=schedule.startupDelayActive===true||nextPurchaseMessage===t('Waiting for startup delay');
  $("nextPurchaseAt").textContent=t(nextPurchaseTimestamp===null?nextPurchaseMessage:new Date(nextPurchaseTimestamp).toLocaleString(locale,{timeZone:schedule.timezone||"UTC",timeZoneName:"short"}));
  exchangeBtcBalance=schedule.btcBalance!=null&&Number.isFinite(Number(schedule.btcBalance))?Number(schedule.btcBalance):null;
  $("exchangeBtcBalance").textContent=t(exchangeBtcBalance===null?"—":btc(exchangeBtcBalance));

  renderExchangeBtcValue();
  const withdrawalTarget=Date.parse(schedule.estimatedWithdrawalAt);
  estimatedWithdrawalTimestamp=Number.isFinite(withdrawalTarget)?withdrawalTarget:null;
  $("estimatedWithdrawalAt").textContent=t(estimatedWithdrawalTimestamp===null?"Not estimated":new Date(estimatedWithdrawalTimestamp).toLocaleString(locale,{timeZone:schedule.timezone||"UTC",timeZoneName:"short"}));
  $("estimatedWithdrawalStatus").textContent=t(estimatedWithdrawalTimestamp===null?(schedule.estimatedWithdrawalStatus||"Waiting for account check"):(schedule.estimatedWithdrawalStatus||"Estimate at the current BTC price, deposit and purchase interval"));
  $("withdrawalCountdownStatus").textContent=t(estimatedWithdrawalTimestamp===null?$("estimatedWithdrawalStatus").textContent:(schedule.estimatedWithdrawalStatus||"Estimate at the current BTC price, deposit and purchase interval"));
  renderWithdrawalProgress(exchangeBtcBalance,Number(schedule.purchaseCurrencyPrice),Number(schedule.withdrawalThreshold),schedule.withdrawalsEnabled);
  renderPurchaseCountdown();
  $('automaticWithdrawalCard').classList.toggle('withdrawal-disabled',!schedule.withdrawalsEnabled);
  $('withdrawalHeading').textContent=t(schedule.withdrawalsEnabled?'Automatic withdrawal':'Automatic withdrawal disabled');
 }catch(e){if(request===scheduleRequest){$("botStatusLabel").textContent=t("Connection unavailable; showing previous values");updateStatusLight("error")}}
}
setInterval(renderPurchaseCountdown,1000);
setInterval(refreshPurchaseSchedule,30000);

function showError(message){$("error").textContent=t(message||"");$("error").classList.toggle("hidden",!message)}
function logUiEvent(event){
 fetch("/api/ui-events",{method:"POST",headers:{"Content-Type":"application/json","X-DCA-Action":"ui-event"},body:JSON.stringify({event}),keepalive:true}).catch(()=>{});
}
function sectionFeedback(id,message,error=false){const el=$(id);el.textContent=t(message);el.classList.toggle("hidden",!message);el.classList.toggle("is-error",error)}
function readReportView(){try{return JSON.parse(localStorage.getItem("bitcoinDcaReportView")||"null")}catch(e){return null}}
function saveReportView(){try{localStorage.setItem("bitcoinDcaReportView",JSON.stringify({pageSize:$("pageSize").value}))}catch(e){}}
function restoreReportView(){
 const now=Date.now(),first=Date.parse($("reportFrom").value);
 $("start").value=localInput(Number.isFinite(first)?first:now-1000);
 $("end").value=localInput(now);$("interval").value="";
 const saved=readReportView();if(!saved||typeof saved!=="object")return;
 if(["5","10","20","50","100","500","1000"].includes(String(saved.pageSize)))$("pageSize").value=String(saved.pageSize);
}

let reportFromSave=Promise.resolve();
function saveReportFrom(){
 const timestamp=parseInput($('start'));
 if(!Number.isFinite(timestamp))return Promise.resolve();
 const value=new Date(timestamp).toISOString();
 reportFromSave=reportFromSave.catch(()=>{}).then(async()=>{
  const response=await fetch('/api/settings/report-period',{method:'POST',
   headers:{'Content-Type':'application/json','X-DCA-Action':'settings'},body:JSON.stringify({from:value}),keepalive:true});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Could not save report start date.');
  $('reportFrom').value=result.from;
 }).catch(error=>sectionFeedback('intervalFeedback','Could not save report start date.',true));
 return reportFromSave;
}
let reportRequest=0,scheduleRequest=0;
function knownNumber(value){return value!==null&&value!==undefined&&String(value).trim()!==""&&Number.isFinite(Number(value))}
function activityBtc(value){return knownNumber(value)?btc(value):"—"}
function activityMoney(value,rate,currency,suffix=""){return knownNumber(value)?money(Number(value)*rate,currency)+suffix:"—"}
function confirmWithdrawal(preview){
 const dialog=$("confirmationDialog");
 $("confirmDestination").textContent=preview.destination||"—";
 $("confirmGross").textContent=t(activityBtc(preview.availableBtc));
 $("confirmFee").textContent=t(knownNumber(preview.feeBtc)?btc(preview.feeBtc):"Determined by the exchange");
 $("confirmNet").textContent=t(knownNumber(preview.netBtc)?btc(preview.netBtc):"Available BTC minus the exchange fee");
 $("confirmationHint").textContent=t("Confirmation expires after two minutes. No transfer is submitted until you confirm.");
 dialog.returnValue="";$("acceptConfirmation").disabled=false;
 return new Promise(resolve=>{
  const timer=setTimeout(()=>{if(dialog.open)dialog.close("expired")},120000);
  dialog.addEventListener("close",()=>{clearTimeout(timer);logUiEvent(dialog.returnValue==="confirm"?"withdrawal_confirmed":dialog.returnValue==="expired"?"withdrawal_expired":"withdrawal_cancelled");resolve(dialog.returnValue==="confirm")},{once:true});
  dialog.showModal();
 });
}
function selectedPeriod(){const start=parseInput($("start")),end=parseInput($("end"));if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end)throw new Error("Please choose a valid date range.");return {start:start,end:end}}
function applySelectedInterval(){if(!$("interval").value)return;const p=$("interval").value.split(",").map(Number);$("start").value=localInput(p[0]);$("end").value=localInput(p[1])}
async function loadIntervals(){
 const response=await fetch("/api/withdrawals");if(!response.ok)throw new Error("Could not load withdrawal history.");
 const withdrawals=await response.json();const select=$("interval");select.innerHTML="";
 const custom=document.createElement("option");custom.value="";custom.textContent=t("Custom date range");select.appendChild(custom);
 for(let i=1;i<withdrawals.length;i++){const a=withdrawals[i-1],b=withdrawals[i],o=document.createElement("option");o.value=a.timestamp+","+b.timestamp;o.textContent=t(dateLabel(a.timestamp)+" → "+dateLabel(b.timestamp));select.appendChild(o)}
 select.value="";
}
let selectedQuickRange='customRange',rangeDraft=null,customPeriod=null;
function captureCustomPeriod(){return {start:$('start').value,end:$('end').value,interval:$('interval').value}}
function restoreCustomPeriod(){if(customPeriod)for(const key of ['start','end','interval'])$(key).value=customPeriod[key]}
const quickRangeIds=['monthRange','yearRange','days30Range','days90Range','oneYearRange','customRange'];
function rollingRangeStart(id,now){
 if(id==='days30Range'||id==='days90Range'){const start=new Date(now);start.setDate(start.getDate()-(id==='days30Range'?30:90));return start;}
 const start=new Date(now);start.setDate(1);start.setFullYear(now.getFullYear()-1);start.setDate(Math.min(now.getDate(),new Date(start.getFullYear(),start.getMonth()+1,0).getDate()));return start;
}
function selectQuickRange(selected){
 selectedQuickRange=selected;
 for(const id of quickRangeIds)$(id).setAttribute('aria-pressed',String(id===selected));
}
for(const id of quickRangeIds)$(id).addEventListener('click',async()=>{
 if(selectedQuickRange==='customRange')customPeriod=captureCustomPeriod();
 if(id==='customRange'){
  restoreCustomPeriod();selectQuickRange(id);await saveReportFrom();currentPage=1;loadAnalytics();return
 }
 selectQuickRange(id);
 const now=new Date(),start=['days30Range','days90Range','oneYearRange'].includes(id)?rollingRangeStart(id,now):new Date(now.getFullYear(),id==='yearRange'?0:now.getMonth(),1);
 $('start').value=localInput(start.getTime());$('end').value=localInput(now.getTime());$('interval').value='';
 await saveReportFrom();currentPage=1;loadAnalytics();
});
$('editCustomRange').addEventListener('click',()=>{
 rangeDraft={...captureCustomPeriod(),selected:selectedQuickRange};
 if(selectedQuickRange==='customRange')customPeriod=captureCustomPeriod();
 restoreCustomPeriod();$('rangeError').textContent='';$('rangeDialog').returnValue='';$('rangeDialog').showModal();
});
$("interval").addEventListener("change",()=>{applySelectedInterval();$('rangeError').textContent=''});
["start","end"].forEach(id=>$(id).addEventListener("change",()=>{$("interval").value="";$('rangeError').textContent=''}));
$('cancelRange').addEventListener('click',()=>$('rangeDialog').close('cancel'));
$('rangeDialog').addEventListener('close',()=>{
 if($('rangeDialog').returnValue!=='apply'&&rangeDraft){$('start').value=rangeDraft.start;$('end').value=rangeDraft.end;$('interval').value=rangeDraft.interval;selectQuickRange(rangeDraft.selected)}
 rangeDraft=null;
});
$('rangeForm').addEventListener('submit',event=>{
 event.preventDefault();try{selectedPeriod()}catch(error){$('rangeError').textContent=t(error.message);return}
 customPeriod=captureCustomPeriod();selectQuickRange('customRange');$('rangeDialog').close('apply');saveReportFrom();saveReportView();currentPage=1;loadAnalytics();
});
function activityStatus(row){
 if(row.type==="Deposit")return row.depositStatus==="confirmed"?{label:"Confirmed ✓",tone:"confirmed"}:{label:"—",tone:"muted"};
 if(row.simulated)return {label:"Simulation",tone:"muted"};
 if(row.type==="Buy")return row.purchaseStatus&&row.purchaseStatus!=="confirmed"?{label:"Unverified",tone:"muted"}:{label:"Confirmed ✓",tone:"confirmed"};
 if(row.type!=="TransferOut")return {label:"—",tone:"muted"};
 const status=String(row.withdrawalStatus||"legacy_unverified").toLowerCase();
 if(status==="completed")return {label:"Confirmed ✓",tone:"confirmed"};
 if(["failed","failure"].includes(status))return {label:"Failed",tone:"failed"};
 if(["canceled","cancelled"].includes(status))return {label:"Cancelled",tone:"muted"};
 if(status==="legacy_unverified")return {label:"Unverified",tone:"muted"};
 return {label:"Pending",tone:"pending"};
}
function renderActivities(){
 const body=$("activities");body.innerHTML="";
 const pageSize=Number($("pageSize").value),total=activityTotal,totalPages=activityPages;
 currentPage=Math.min(Math.max(1,currentPage),totalPages);
 const start=(currentPage-1)*pageSize,end=Math.min(start+pageSize,total);
 for(const row of activityRows){
  const rate=Number.isFinite(activityRates[row.currency])?activityRates[row.currency]:1,currency=Number.isFinite(activityRates[row.currency])?displayCurrency:row.currency;
  const status=activityStatus(row);
  const tr=document.createElement("tr"),type=row.simulated?"Buy (Simulation)":(row.type==="TransferOut"?"Withdrawal":row.type),vals=[Number.isFinite(Date.parse(row.datetime))?dateLabel(Date.parse(row.datetime)):"—",t(type||"—"),row.type==="Deposit"?"—":activityBtc(row.shares),row.type==="Deposit"?"—":activityMoney(row.price,rate,currency,"/BTC"),activityMoney(row.amount,rate,currency),(row.type==="Deposit"&&!row.depositStatus)?"—":(row.simulated&&knownNumber(row.fee)?"~":"")+activityMoney(row.fee,rate,currency),t(status.label)];
  vals.forEach((v,i)=>{const td=document.createElement("td");td.textContent=v;if(i>=2&&i<=5)td.className="num";if(i===6)td.className="activity-status status-"+status.tone;tr.appendChild(td)});
  body.appendChild(tr)
 }
 if(!total){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=7;td.textContent=t("No activity in this period.");td.className="notice";tr.appendChild(td);body.appendChild(tr)}
 $("pageInfo").textContent=t(total?("Showing "+(start+1)+"–"+end+" of "+total+" · Page "+currentPage+" of "+totalPages):"No entries");
 $("previousPage").disabled=currentPage<=1;$("nextPage").disabled=currentPage>=totalPages;
 $("pageNumber").value=currentPage;$("pageNumber").max=totalPages;
 $("pageNumber").disabled=!total;$("goToPage").disabled=!total;
}
$("pageSize").addEventListener("change",()=>{saveReportView();currentPage=1;loadAnalytics()});
$("previousPage").addEventListener("click",()=>{if(currentPage>1){currentPage--;loadAnalytics()}});
$("nextPage").addEventListener("click",()=>{currentPage++;loadAnalytics()});
$("pageJump").addEventListener("submit",event=>{
 event.preventDefault();const page=Number($("pageNumber").value);
 if(!activityTotal||!Number.isInteger(page)||page<1||page>activityPages)return;
 if(page!==currentPage){currentPage=page;loadAnalytics()}
});
async function loadAnalytics(){
 const request=++reportRequest;$("periodReport").ariaBusy="true";saveReportView();sectionFeedback("reportFeedback","");
 try{showError("");const p=selectedPeriod();const response=await fetch("/api/analytics?start="+p.start+"&end="+p.end+"&page="+currentPage+"&limit="+$("pageSize").value);const d=await response.json();if(!response.ok)throw new Error(d.error||"Could not load the report.");if(request!==reportRequest)return;quote=d.quote;$('selectedPeriodLabel').textContent=dateLabel(p.start)+' – '+dateLabel(p.end);
 displayCurrency=["EUR","USD"].includes(d.configuration.displayCurrency)?d.configuration.displayCurrency:(["EUR","USD"].includes(quote)?quote:"EUR");
 document.title="Bitcoin DCA Dashboard";
 let livePrice=Number((d.snapshot||{}).price||0),currencyRates={[quote]:1};
 const currencies=[...new Set([...Object.keys(d.summaryByCurrency||{}),...Object.keys(d.depositsByCurrency||{})])];
 try{
  const priceResponse=await fetch("/api/market-price?currency="+displayCurrency+"&currencies="+encodeURIComponent(currencies.join(",")));const market=await priceResponse.json();if(!priceResponse.ok)throw new Error(market.error||"Could not load current BTC price.");
  if(request!==reportRequest)return;
  fxRate=Number(market.conversionRate);livePrice=Number(market.price);currencyRates=Object.fromEntries(Object.entries(market.conversionRates||{[quote]:fxRate})
   .map(([currency,rate])=>[currency,Number(rate)]).filter(([,rate])=>Number.isFinite(rate)&&rate>0));
  currencyRates[displayCurrency]=1;

 }catch(priceError){
  if(request!==reportRequest)return;
  displayCurrency=quote;fxRate=1;
  if(!(livePrice>0)&&balanceDisplayCurrency===quote&&balanceDisplayPrice>0)livePrice=balanceDisplayPrice;

 }
 balanceDisplayPrice=livePrice;balanceDisplayCurrency=displayCurrency;renderExchangeBtcValue();
 $("spot").textContent=t(livePrice>0?money(livePrice,displayCurrency)+"/BTC":"—");
 let depositTotal=0,depositConversionAvailable=true;
 for(const [currency,values] of Object.entries(d.depositsByCurrency||{})){
  if(!Number.isFinite(currencyRates[currency])){depositConversionAvailable=false;continue}
  depositTotal+=Number(values.amount)*currencyRates[currency];
 }
 $('depositVolume').textContent=depositConversionAvailable?money(depositTotal,displayCurrency):'—';
 const converted={buyVolume:0,tradeFees:0,withdrawalFees:0};
 let moneyAvailable=true;
 for(const [currency,values] of Object.entries(d.summaryByCurrency||{})){
  if(!Number.isFinite(currencyRates[currency])){moneyAvailable=false;continue}
  for(const key of Object.keys(converted))converted[key]+=Number(values[key]||0)*currencyRates[currency];
 }
 if(!moneyAvailable)showError("A required currency conversion is unavailable; monetary totals are hidden.");
 if(livePrice>0&&moneyAvailable){
  const periodPurchaseValue=Number(d.summary.boughtBtc)*livePrice;
  const periodPurchaseCosts=converted.buyVolume+converted.tradeFees;
  const profitLoss=periodPurchaseValue-periodPurchaseCosts;
  $("profitLoss").textContent=t(money(profitLoss,displayCurrency));
  $("profitLoss").className="value "+(profitLoss>=0?"positive":"negative");
 }else{$("profitLoss").textContent=t("—");$("profitLoss").className="value"}
 $('investedTotal').textContent=moneyAvailable?money(converted.buyVolume+converted.tradeFees,displayCurrency):'—';
 $('periodValue').textContent=livePrice>0?money(Number(d.summary.boughtBtc)*livePrice,displayCurrency):'—';
 $('modeBadge').textContent=t(d.configuration.liveTrading?'Live':'Simulation');
 $('withdrawalBadge').textContent=t(d.configuration.withdrawalsEnabled?'Enabled':'Disabled');
 $("buyCount").textContent=t(d.summary.buyCount);$("buyBtc").textContent=t(btc(d.summary.boughtBtc));
 $("buyVolume").textContent=t(moneyAvailable?money(converted.buyVolume,displayCurrency):"—");$("avgPrice").textContent=t(moneyAvailable?"Average: "+money(Number(d.summary.boughtBtc)>0?converted.buyVolume/Number(d.summary.boughtBtc):0,displayCurrency)+"/BTC":"Conversion unavailable");
 $("tradeFees").textContent=t(moneyAvailable?money(converted.tradeFees,displayCurrency):"—");$("withdrawBtc").textContent=t(btc(d.summary.withdrawnBtc));
 $("withdrawFees").textContent=t(moneyAvailable?money(converted.withdrawalFees,displayCurrency):"—");$("netBtc").textContent=t(btc(d.summary.netBtc));
 activityRates=currencyRates;activityRows=d.activities;activityTotal=d.pagination.total;activityPages=d.pagination.pages;currentPage=d.pagination.page;renderActivities();
 }catch(e){if(request===reportRequest)showError(e.message)}
 finally{if(request===reportRequest){$("periodReport").ariaBusy="false";sectionFeedback("reportFeedback","")}}
}
let exportDialogRequest=0,exportIntervalError='';
function exportDialogMessage(message){$('exportDialogMessage').textContent=t(message);$('exportDialogMessage').classList.toggle('hidden',!message)}
async function requestParqetExport(){
 logUiEvent('export_clicked');actionFeedback('export','',false,false);
 const request=++exportDialogRequest,select=$('exportInterval');select.replaceChildren();select.disabled=true;$('confirmExport').disabled=true;exportIntervalError='';exportDialogMessage('');$('exportDialog').showModal();
 try{
  const response=await fetch('/api/withdrawals');if(!response.ok)throw new Error('Could not load withdrawal history.');
  const records=await response.json();if(request!==exportDialogRequest)return;
  const previous=new Map();let period;try{period=selectedPeriod()}catch{period={start:0,end:Date.now()}}let preferred='';
  for(const withdrawal of records){
   const end=Number(withdrawal.timestamp);if(!Number.isFinite(end)||end<=0)continue;
   const exchange=withdrawal.exchange||'',start=previous.get(exchange)||0;previous.set(exchange,end);if(start>=end)continue;
   const option=document.createElement('option');option.value=start+','+end;
   const name=exchange==='KRAKEN'?'Kraken':exchange==='BITVAVO'?'Bitvavo':exchange;
   option.textContent=(name?name+' · ':'')+(start?dateLabel(start):t('First recorded purchase'))+' → '+dateLabel(end);
   select.appendChild(option);if(end>period.start&&end<=period.end)preferred=option.value;
  }
  if(!select.children.length){const option=document.createElement('option');option.value='';option.textContent=t('Select a withdrawal interval');select.appendChild(option);select.value=''}
  else{select.disabled=false;select.value=preferred||select.children[select.children.length-1].value}
 }catch(error){if(request!==exportDialogRequest)return;exportIntervalError=error.message;const option=document.createElement('option');option.value='';option.textContent=t('Select a withdrawal interval');select.appendChild(option);select.value=''}
 finally{if(request===exportDialogRequest)$('confirmExport').disabled=false}
}
$('cancelExport').addEventListener('click',()=>$('exportDialog').close());
$('confirmExport').addEventListener('click',downloadParqetCsv);
async function downloadParqetCsv(){
 const button=$('confirmExport');exportDialogMessage('');button.disabled=true;
 try{
  if(exportIntervalError)throw new Error(exportIntervalError);
  const choice=$('exportInterval').value;
  if(!choice)throw new Error('No confirmed withdrawal is available. Export after your first confirmed withdrawal.');
  const [start,end]=choice.split(',').map(Number);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||start>=end)throw new Error('Please choose a valid withdrawal interval.');
  const response=await fetch('/api/export.csv?start='+start+'&end='+end);
  if(!response.ok){const data=await response.json();throw new Error(data.error||'Could not generate the CSV export.')}
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='parqet_btc_'+new Date(end).toISOString().slice(0,10)+'.csv';link.click();URL.revokeObjectURL(url);
  $('exportDialog').close();actionFeedback('export',t('CSV export prepared.'),false);
 }catch(error){exportDialogMessage(error.message)}
 finally{button.disabled=false}
}

async function withdrawalPost(path, body){
 const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-DCA-Action":"withdrawal"},body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok)throw new Error(result.error||"Withdrawal request failed.");
 if(!result.jobId)return result;
 showWithdrawalMessage("Request queued. Waiting for the account worker…",false);
 for(let i=0;i<600;i++){
  const check=await fetch("/api/withdrawal/jobs/"+encodeURIComponent(result.jobId));const job=await check.json();
  if(!check.ok)throw new Error(job.error||"Could not check the request. Check exchange status before trying again.");
  if(job.state==="failed")throw new Error(job.error);
  if(job.state==="completed")return job.result;
  await new Promise(resolve=>setTimeout(resolve,1000));
 }
 throw new Error("The request is still unresolved. Check exchange status before starting another withdrawal.");
}
async function loadWithdrawalConfiguration(){
 const response=await fetch("/api/withdrawal/config");const d=await response.json();
 if(!response.ok)throw new Error(d.error||"Could not load withdrawal configuration.");
 const destinationText=d.target
  ?(d.exchange==="KRAKEN"
    ?"BTC is sent to the address saved in Kraken under “"+d.target+"”."
    :"BTC is sent to "+d.target+" via "+(d.network||"BTC")+" on Bitvavo.")
  :"No withdrawal target is configured for "+(d.exchange==="KRAKEN"?"Kraken":"Bitvavo")+".";
 $("withdrawalDestination").textContent=t(destinationText);$("automaticWithdrawalDestination").textContent=t(destinationText);

 return d;
}
function actionFeedback(action,message,error=false,busy=null){
 const frame=$("settingsFrame");
 frame?.contentWindow?.postMessage({type:'dca-dashboard-action-feedback',action,message,error,busy},window.location.origin);
}
function showWithdrawalMessage(message,error=true){

 actionFeedback('withdraw',t(message),error);
}
async function requestManualWithdrawal(){
 logUiEvent("withdrawal_clicked");
 actionFeedback("withdraw","",false,true);
 try{
 showWithdrawalMessage("Preparing withdrawal preview…",false);
 const configuration=await loadWithdrawalConfiguration();
 if(!configuration.enabled){showWithdrawalMessage(configuration.reason||"Manual withdrawal is not configured. See Notes.");return}
 const p=await withdrawalPost("/api/withdrawal/preview",{});
 if(!await confirmWithdrawal(p)){

  actionFeedback("withdraw","",false);
  return;
 }
 showWithdrawalMessage("Submitting withdrawal…",false);
 const result=await withdrawalPost("/api/withdrawal/confirm",{token:p.token});showWithdrawalMessage(result.message,false);
 $("interval").value="";$("end").value=localInput(Date.now()+60000);currentPage=1;await loadAnalytics();
 }catch(e){showWithdrawalMessage(e.message)}
 finally{actionFeedback("withdraw",null,false,false)}
}
window.DCA_DASHBOARD_ACTIONS={withdraw:requestManualWithdrawal,export:requestParqetExport};
refreshPurchaseSchedule();

(async()=>{
 try{await loadIntervals()}catch(e){
  $("interval").value="";$("start").value=localInput(Date.parse($("reportFrom").value)||Date.now()-1000);$("end").value=localInput(Date.now());
  sectionFeedback("intervalFeedback","Withdrawal intervals unavailable. Custom dates remain available.",true);
 }
 restoreReportView();await loadAnalytics();
})();

// Preserve readable text and values; only changed account/report numbers fade briefly.
(()=>{
 if(typeof MutationObserver==='undefined'||!document.querySelectorAll||!document.createTextNode)return;
 const previous=new WeakMap();
 for(const element of document.querySelectorAll('.metric>.value,.plan-card>.value')){
  let animation;
  const update=()=>{
   const text=element.textContent,old=previous.get(element);
   previous.set(element,text);
   const unit=text.match(/(\sBTC|\/BTC)$/);
   if(unit&&!element.querySelector('.value-unit')){const suffix=document.createElement('span');suffix.className='value-unit';suffix.textContent=unit[0];element.replaceChildren(document.createTextNode(text.slice(0,-unit[0].length)),suffix)}
   if(text!==old&&old&&old!=='—'&&/\d/.test(text)&&element.animate){animation?.cancel();animation=element.animate([{opacity:.6},{opacity:1}],{duration:180,easing:'ease-out'})}
  };
  update();new MutationObserver(update).observe(element,{childList:true,characterData:true,subtree:true});
 }
})();
