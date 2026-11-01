const {t,locale}=typeof DCA_I18N!=="undefined"?DCA_I18N:{t:value=>value,locale:"en-GB"};

const $=id=>document.getElementById(id);
let quote="EUR", displayCurrency="", fxRate=1, activityRows=[], currentPage=1, activityTotal=0, activityPages=1, activityRates={};
function localInput(ms){const d=new Date(ms);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,19)}
function parseInput(el){return new Date(el.value).getTime()}
function money(v,c){try{return new Intl.NumberFormat(locale,{style:"currency",currency:c,maximumFractionDigits:2}).format(Number(v||0))}catch(e){return Number(v||0).toFixed(2)+" "+c}}
function btc(v){return Number(v||0).toLocaleString(locale,{minimumFractionDigits:0,maximumFractionDigits:8})+" BTC"}
function dateLabel(ms){return new Date(ms).toLocaleString(locale)}
let exchangeBtcBalance=null, balanceDisplayPrice=null, balanceDisplayCurrency=null;
function renderExchangeBtcValue(){
 $("exchangeBtcValue").textContent=t(exchangeBtcBalance!==null&&balanceDisplayPrice>0&&balanceDisplayCurrency===displayCurrency?money(exchangeBtcBalance*balanceDisplayPrice,displayCurrency):"—");
}
let nextPurchaseTimestamp=null, estimatedWithdrawalTimestamp=null, scheduleClockOffset=0, nextPurchaseMessage="Not scheduled";
function renderCountdown(id, timestamp){
 const output=$(id);
 if(timestamp===null){output.textContent=t("—");return}
 let seconds=Math.max(0,Math.ceil((timestamp-Date.now()-scheduleClockOffset)/1000));
 if(!seconds){output.textContent=t("Due now");return}
 const days=Math.floor(seconds/86400);seconds%=86400;
 const hours=Math.floor(seconds/3600);seconds%=3600;
 const minutes=Math.floor(seconds/60),remaining=seconds%60;
 output.textContent=t((days?days+"d ":"")+String(hours).padStart(2,"0")+"h "+String(minutes).padStart(2,"0")+"m "+String(remaining).padStart(2,"0")+"s");
}
function renderPurchaseCountdown(){
 renderCountdown("nextPurchaseCountdown",nextPurchaseTimestamp);
 if(nextPurchaseTimestamp===null)$("nextPurchaseCountdown").textContent=t(nextPurchaseMessage);
 renderCountdown("withdrawalCountdown",estimatedWithdrawalTimestamp);
 if(estimatedWithdrawalTimestamp===null)$("withdrawalCountdown").textContent=t("Not estimated");
}
function updateStatusLight(tone){
 $('botStatusLight').className='status-light status-'+(['active','waiting','error'].includes(tone)?tone:'waiting');
}
async function refreshPurchaseSchedule(){
 const request=++scheduleRequest;sectionFeedback("scheduleFeedback","Updating schedule…");
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
   $('spotUpdated').textContent=t('Last checked '+new Date(Number(market.updatedAt)*1000).toLocaleString(locale));
   renderExchangeBtcValue();
  }
  const detail=schedule.forecastDetails;
  $('forecastProgress').textContent=detail?t('About {btc} BTC · {buys} purchases remaining'.replace('{btc}',Number(detail.remainingBtc).toLocaleString(locale,{maximumFractionDigits:8})).replace('{buys}',detail.remainingPurchases)):'';
  $('forecastAssumptions').hidden=!detail;
  if(detail)$('forecastAssumptionsText').textContent=t('BTC price: {price}. BTC per purchase: {quantity}. Threshold: {threshold}. Assumes unchanged price and fees. Monthly deposit: {amount}. Deposit: day {day}, {time} ({zone}).'.replace('{price}',money(detail.price,detail.quote)).replace('{quantity}',btc(detail.quantity)).replace('{threshold}',money(detail.threshold,detail.quote)).replace('{amount}',detail.monthlyDeposit?money(detail.monthlyDeposit,detail.quote):t('Not configured')).replace('{day}',detail.depositDay).replace('{time}',detail.depositTime).replace('{zone}',detail.timezone));
  $("monthlyDepositCurrency").textContent=t(schedule.quote);
  if(!monthlyDepositDirty&&!monthlyDepositSaving)$("monthlyDeposit").value=schedule.expectedMonthlyDeposit??"";
  if(schedule.configuredBuyAmount!==undefined){
   const minimumMode=Number(schedule.configuredBuyAmount)===0;
   const effective=Number(schedule.effectiveBuyAmount);
   $("buyAmount").textContent=t(schedule.finalPurchase&&effective>0?btc(effective):minimumMode?(effective>0?btc(effective):"—"):btc(schedule.configuredBuyAmount));
   $("buyAmountNote").textContent=t(schedule.finalPurchase?"Final purchase · uses remaining fiat":minimumMode?"(exchange minimum)"+(effective>0?"":" · waiting for account check"):"");
  }
  $("quoteBalanceLabel").textContent=t("Available "+schedule.quote+" balance on exchange");
  const balanceKnown=schedule.quoteBalance!==null&&schedule.quoteBalance!==undefined&&Number.isFinite(Number(schedule.quoteBalance));
  $("quoteBalance").textContent=t(balanceKnown?money(schedule.quoteBalance,schedule.quote):"—");
  const checkedAt=Date.parse(schedule.balanceUpdatedAt);
  $("quoteBalanceUpdated").textContent=t(balanceKnown
   ?(Number.isFinite(checkedAt)?"Last checked "+new Date(checkedAt).toLocaleString(locale,{timeZone:schedule.timezone||"UTC"}):"Last account check")
   :"Waiting for account check");
  nextPurchaseTimestamp=Number.isFinite(target)?target:null;

  nextPurchaseMessage=schedule.nextPurchaseStatus||"Not scheduled";
  $("nextPurchaseAt").textContent=t(nextPurchaseTimestamp===null?nextPurchaseMessage:new Date(nextPurchaseTimestamp).toLocaleString(locale,{timeZone:schedule.timezone||"UTC",timeZoneName:"short"}));
  exchangeBtcBalance=schedule.btcBalance!=null&&Number.isFinite(Number(schedule.btcBalance))?Number(schedule.btcBalance):null;
  $("exchangeBtcBalance").textContent=t(exchangeBtcBalance===null?"—":btc(exchangeBtcBalance));
  $("exchangeBtcUpdated").textContent=t(exchangeBtcBalance===null?"Waiting for account check":(Number.isFinite(checkedAt)?"Last checked "+new Date(checkedAt).toLocaleString(locale,{timeZone:schedule.timezone||"UTC"}):"Last account check"));
  renderExchangeBtcValue();
  const withdrawalTarget=Date.parse(schedule.estimatedWithdrawalAt);
  estimatedWithdrawalTimestamp=Number.isFinite(withdrawalTarget)?withdrawalTarget:null;
  $("estimatedWithdrawalAt").textContent=t(estimatedWithdrawalTimestamp===null?"Not estimated":new Date(estimatedWithdrawalTimestamp).toLocaleString(locale,{timeZone:schedule.timezone||"UTC",timeZoneName:"short"}));
  $("estimatedWithdrawalStatus").textContent=t(estimatedWithdrawalTimestamp===null?(schedule.estimatedWithdrawalStatus||"Waiting for account check"):(schedule.estimatedWithdrawalStatus||"Estimate at the current BTC price, deposit and purchase interval"));
  $("withdrawalCountdownStatus").textContent=t(estimatedWithdrawalTimestamp===null?$("estimatedWithdrawalStatus").textContent:(schedule.estimatedWithdrawalStatus||"Estimate at the current BTC price, deposit and purchase interval"));
  renderPurchaseCountdown();
  sectionFeedback("scheduleFeedback","");
 }catch(e){if(request===scheduleRequest){$("botStatusLabel").textContent=t("Connection unavailable; showing previous values");updateStatusLight("error");sectionFeedback("scheduleFeedback","Could not refresh the schedule. Previous values are still shown.",true)}}
}
let monthlyDepositDirty=false,monthlyDepositSaving=false;
$("monthlyDeposit").addEventListener("input",()=>{monthlyDepositDirty=true});
$("monthlyDeposit").addEventListener("change",async()=>{
 const input=$("monthlyDeposit"),amount=input.value.trim();
 if(amount!==""&&(!Number.isFinite(Number(amount))||Number(amount)<0)){input.reportValidity();return}
 monthlyDepositDirty=true;monthlyDepositSaving=true;input.disabled=true;
 sectionFeedback("scheduleFeedback","Saving forecast amount…");
 try{
  const response=await fetch("/api/settings/forecast",{method:"POST",headers:{"Content-Type":"application/json","X-DCA-Action":"settings"},body:JSON.stringify({monthlyDeposit:amount})});
  if(response.status===401){window.location.reload();return}
  const data=await response.json();if(!response.ok)throw new Error(data.error||"Forecast amount could not be saved.");
  input.value=data.monthlyDeposit;monthlyDepositDirty=false;
  await refreshPurchaseSchedule();
 }catch(error){sectionFeedback("scheduleFeedback",error.message||"Forecast amount could not be saved.",true)}
 finally{monthlyDepositSaving=false;input.disabled=false}
});
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
$("interval").addEventListener("change",()=>{applySelectedInterval();saveReportFrom();saveReportView();currentPage=1;loadAnalytics()});
["start","end"].forEach(id=>$(id).addEventListener("change",()=>{$("interval").value="";saveReportView();if(id==="start")return saveReportFrom()}));
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
 const occupiedRows=activityRows.length||(!total?1:0);
 for(let i=occupiedRows;i<pageSize;i++){
  const tr=document.createElement("tr");tr.className="activity-placeholder";tr.ariaHidden="true";
  for(let column=0;column<7;column++){
   const td=document.createElement("td");td.textContent=t(" ");if(column>=2&&column<=5)td.className="num";tr.appendChild(td);
  }
  body.appendChild(tr);
 }
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
 const request=++reportRequest;$("refresh").ariaBusy="true";$("periodReport").ariaBusy="true";saveReportView();sectionFeedback("reportFeedback","");
 try{showError("");const p=selectedPeriod();const response=await fetch("/api/analytics?start="+p.start+"&end="+p.end+"&page="+currentPage+"&limit="+$("pageSize").value);const d=await response.json();if(!response.ok)throw new Error(d.error||"Could not load the report.");if(request!==reportRequest)return;quote=d.quote;
 displayCurrency=["EUR","USD"].includes(d.configuration.displayCurrency)?d.configuration.displayCurrency:(["EUR","USD"].includes(quote)?quote:"EUR");
 const ex=d.exchange==="KRAKEN"?"Kraken":d.exchange==="BITVAVO"?"Bitvavo":d.exchange;document.title="Bitcoin DCA Dashboard";
 let livePrice=Number((d.snapshot||{}).price||0),currencyRates={[quote]:1};
 const currencies=[...new Set([...Object.keys(d.summaryByCurrency||{}),...Object.keys(d.depositsByCurrency||{})])];
 try{
  const priceResponse=await fetch("/api/market-price?currency="+displayCurrency+"&currencies="+encodeURIComponent(currencies.join(",")));const market=await priceResponse.json();if(!priceResponse.ok)throw new Error(market.error||"Could not load current BTC price.");
  if(request!==reportRequest)return;
  fxRate=Number(market.conversionRate);livePrice=Number(market.price);currencyRates=Object.fromEntries(Object.entries(market.conversionRates||{[quote]:fxRate})
   .map(([currency,rate])=>[currency,Number(rate)]).filter(([,rate])=>Number.isFinite(rate)&&rate>0));
  currencyRates[displayCurrency]=1;
  $("spotUpdated").textContent=t("Last checked "+new Date(Number(market.updatedAt)*1000).toLocaleString(locale));
 }catch(priceError){
  if(request!==reportRequest)return;
  displayCurrency=quote;fxRate=1;
  if(!(livePrice>0)&&balanceDisplayCurrency===quote&&balanceDisplayPrice>0)livePrice=balanceDisplayPrice;
  const checked=Date.parse((d.snapshot||{}).updatedAt);
  if(Number((d.snapshot||{}).price)>0&&Number.isFinite(checked))
   $("spotUpdated").textContent=t("Last checked "+new Date(checked).toLocaleString(locale));
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
 $("settingExchange").textContent=t(ex);$("settingQuoteCurrency").textContent=t(quote);$("tradingMode").textContent=t(d.configuration.liveTrading?"live":"Simulation");
 const amountSnapshot=d.snapshot||{};
 const effectiveMinimum=amountSnapshot.exchange===d.exchange&&amountSnapshot.quote===quote?Number((amountSnapshot.withdrawalForecastPlan||{}).orderAmount):NaN;
 $("buyAmount").textContent=t(d.snapshot.withdrawalForecastPlan?.useRemainingBudget&&effectiveMinimum>0?btc(effectiveMinimum):Number(d.configuration.buyAmount)===0
  ?(Number.isFinite(effectiveMinimum)&&effectiveMinimum>0?btc(effectiveMinimum):"—")
  :btc(d.configuration.buyAmount));
 $("buyAmountNote").textContent=t(d.snapshot.withdrawalForecastPlan?.useRemainingBudget?"Final purchase · uses remaining fiat":Number(d.configuration.buyAmount)===0?"(exchange minimum)"+(Number.isFinite(effectiveMinimum)&&effectiveMinimum>0?"":" · waiting for account check"):"");
 $("depositDay").textContent=t(String(d.configuration.depositDay));$("depositTime").textContent=t((d.configuration.depositTime||"00:00")+" · "+(d.configuration.timezone||"UTC"));$("withdrawEnabled").textContent=t(d.configuration.withdrawalsEnabled?"Enabled":"Disabled");
 $("threshold").textContent=t(money(Number(d.configuration.withdrawalThreshold)*fxRate,displayCurrency));$("thresholdNote").textContent=t("Threshold in "+quote+", shown in "+displayCurrency);
 $("buyCount").textContent=t(d.summary.buyCount);$("buyBtc").textContent=t(btc(d.summary.boughtBtc));
 $("buyVolume").textContent=t(moneyAvailable?money(converted.buyVolume,displayCurrency):"—");$("avgPrice").textContent=t(moneyAvailable?"Average: "+money(Number(d.summary.boughtBtc)>0?converted.buyVolume/Number(d.summary.boughtBtc):0,displayCurrency)+"/BTC":"Conversion unavailable");
 $("tradeFees").textContent=t(moneyAvailable?money(converted.tradeFees,displayCurrency):"—");$("withdrawBtc").textContent=t(btc(d.summary.withdrawnBtc));
 $("withdrawFees").textContent=t(moneyAvailable?money(converted.withdrawalFees,displayCurrency):"—");$("netBtc").textContent=t(btc(d.summary.netBtc));
 activityRates=currencyRates;activityRows=d.activities;activityTotal=d.pagination.total;activityPages=d.pagination.pages;currentPage=d.pagination.page;renderActivities();
 }catch(e){if(request===reportRequest)showError(e.message)}
 finally{if(request===reportRequest){$("refresh").ariaBusy="false";$("periodReport").ariaBusy="false";sectionFeedback("reportFeedback","")}}
}
$("refresh").addEventListener("click",()=>{currentPage=1;loadAnalytics()});
$("download").addEventListener("click",async()=>{
 logUiEvent("export_clicked");
 const button=$("download"),message=$("exportMessage");
 message.textContent=t("");message.classList.add("hidden");
 button.disabled=true;button.textContent=t("Generating CSV…");
 try{
  const p=selectedPeriod(),response=await fetch("/api/export.csv?start="+p.start+"&end="+p.end);
  if(!response.ok){const d=await response.json();throw new Error(d.error||"Could not generate the CSV export.")}
  const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download="parqet_btc_"+new Date(p.start).toISOString().slice(0,10)+"_"+new Date(p.end).toISOString().slice(0,10)+".csv";
  a.click();URL.revokeObjectURL(url);
 }catch(e){message.textContent=t(e.message);message.classList.remove("hidden")}
 finally{button.disabled=false;button.textContent=t("Download Parqet CSV")}
});

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
 const target=d.target||"";
 $("withdrawalTarget").textContent=target?(d.exchange==="BITVAVO"&&target.length>22?target.slice(0,10)+"…"+target.slice(-8):target):"Not configured";
 $("withdrawalTarget").title=target;
 $("withdrawMessage").textContent=t(d.reason||"Manual withdrawals are available. Automatic withdrawals may remain disabled.");
 return d;
}
function showWithdrawalMessage(message,error=true){
 $("withdrawMessage").textContent=t(message);
 const feedback=$("withdrawalFeedback");
 feedback.textContent=t(message);feedback.classList.remove("hidden");
 feedback.classList.toggle("success",!error);
}
$("manualWithdraw").addEventListener("click",async()=>{
 logUiEvent("withdrawal_clicked");
 const button=$("manualWithdraw");button.disabled=true;
 $("withdrawalFeedback").textContent=t("");$("withdrawalFeedback").classList.add("hidden");
 try{
 showWithdrawalMessage("Preparing withdrawal preview…",false);
 const configuration=await loadWithdrawalConfiguration();
 if(!configuration.enabled){showWithdrawalMessage(configuration.reason||"Manual withdrawal is not configured. See Notes.");return}
 const p=await withdrawalPost("/api/withdrawal/preview",{});
 if(!await confirmWithdrawal(p)){
  $("withdrawMessage").textContent=t(configuration.reason||"");
  $("withdrawalFeedback").textContent=t("");$("withdrawalFeedback").classList.add("hidden");
  return;
 }
 showWithdrawalMessage("Submitting withdrawal…",false);
 const result=await withdrawalPost("/api/withdrawal/confirm",{token:p.token});showWithdrawalMessage(result.message,false);
 $("interval").value="";$("end").value=localInput(Date.now()+60000);currentPage=1;await loadAnalytics();
 }catch(e){showWithdrawalMessage(e.message)}
 finally{button.disabled=false}
});
loadWithdrawalConfiguration().catch(e=>{showWithdrawalMessage(e.message)});
refreshPurchaseSchedule();

(async()=>{
 try{await loadIntervals()}catch(e){
  $("interval").value="";$("start").value=localInput(Date.parse($("reportFrom").value)||Date.now()-1000);$("end").value=localInput(Date.now());
  sectionFeedback("intervalFeedback","Withdrawal intervals unavailable. Custom dates remain available.",true);
 }
 restoreReportView();await loadAnalytics();
})();
