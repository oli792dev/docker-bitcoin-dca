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
function renderWithdrawalProgress(balance,price,threshold,enabled){
 const known=enabled&&Number.isFinite(balance)&&price>0&&threshold>0;
 $('withdrawalProgress').hidden=!known;
 $('withdrawalProgress').value=known?Math.min(100,Math.max(0,balance*price/threshold*100)):0;
 $('withdrawalProgressLabel').textContent=known?t('{value} of {threshold}').replace('{value}',money(balance*price,quote)).replace('{threshold}',money(threshold,quote)):t(enabled?'Waiting for account check':'Automatic withdrawals disabled');
}
function renderPurchaseChart(series,rates,price,currency,available,range=selectedPeriod()){
 const chart=$('purchaseChart');chart.replaceChildren();chart.setAttribute('hidden','');const tooltip=$('chartTooltip');tooltip.hidden=true;chart.onpointermove=null;chart.onkeydown=null;
 $('chartStart').textContent='';$('chartEnd').textContent='';
 if(!series?.length){$('chartMessage').textContent=t('No real purchases in this period.');return}
 if(!available||!(price>0)||series.some(point=>Object.keys(point.costs).some(c=>!(rates[c]>0)))){$('chartMessage').textContent=t('Conversion unavailable');return}
 let cost=0,quantity=0;
 const points=series.map(point=>{quantity+=Number(point.btc);cost+=Object.entries(point.costs).reduce((sum,[c,v])=>sum+Number(v)*rates[c],0);return {time:Number(point.timestamp),cost,value:quantity*price}});
 const start=range.start,end=range.end;
 const max=Math.max(...points.map(p=>Math.max(p.cost,p.value)),1)*1.1;
 const x=time=>60+Math.max(0,Math.min(1,(time-start)/Math.max(1,end-start)))*930;
 const y=value=>220-value/max*190;
 const svg=(tag,attrs,text)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,String(v));if(text!==undefined)node.textContent=text;chart.appendChild(node);return node};
 for(let i=0;i<4;i++){const value=max*i/3;svg('path',{d:'M60 '+y(value)+' H990',stroke:'var(--line)',fill:'none'});svg('text',{x:0,y:y(value)+4,fill:'var(--muted)','font-size':11},money(value,currency))}
 for(const [key,color] of [['cost','var(--muted)'],['value','var(--accent)']]){
  let path='M60 220';for(const point of points)path+=' H'+x(point.time)+' V'+y(point[key]);path+=' H990';
  svg('path',{d:path,stroke:color,'stroke-width':key==='value'?3:2,fill:'none','vector-effect':'non-scaling-stroke'});
 }
 for(const point of points)svg('circle',{cx:x(point.time),cy:y(point.value),r:3,fill:'var(--accent)'});
 const guide=svg('path',{d:'',stroke:'var(--muted)','stroke-dasharray':'4 4',fill:'none'});
 const marker=svg('circle',{cx:0,cy:0,r:5,fill:'var(--accent)',stroke:'var(--panel)','stroke-width':2,visibility:'hidden'});
 let active=0;
 function showPoint(index){
  active=Math.max(0,Math.min(points.length-1,index));const point=points[active];
  guide.setAttribute('d','M'+x(point.time)+' 20 V220');marker.setAttribute('cx',x(point.time));marker.setAttribute('cy',y(point.value));marker.setAttribute('visibility','visible');
  tooltip.textContent=t('As of {date}').replace('{date}',dateLabel(point.time))+' · '+t('Invested including trading fees')+': '+money(point.cost,currency)+' · '+t('Value at the current BTC price')+': '+money(point.value,currency);
  tooltip.hidden=false;
 }
 function hidePoint(){tooltip.hidden=true;guide.setAttribute('d','');marker.setAttribute('visibility','hidden')}
 chart.onpointermove=event=>{const rect=chart.getBoundingClientRect(),position=(event.clientX-rect.left)/rect.width*1000;let nearest=0;for(let i=1;i<points.length;i++)if(Math.abs(x(points[i].time)-position)<Math.abs(x(points[nearest].time)-position))nearest=i;showPoint(nearest)};
 chart.onpointerleave=hidePoint;
 chart.onpointerdown=chart.onpointermove;
 chart.onblur=hidePoint;
 chart.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key)){event.preventDefault();if(event.key==='Escape'){hidePoint();return}showPoint(event.key==='Home'?0:event.key==='End'?points.length-1:active+(event.key==='ArrowRight'?1:-1))}};
 svg('title',{},t('Cumulative purchases and their value at the current BTC price'));
 chart.removeAttribute('hidden');$('chartMessage').textContent='';
 $('chartStart').textContent=new Date(start).toLocaleDateString(locale);$('chartEnd').textContent=new Date(end).toLocaleDateString(locale);
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
  $("quoteBalanceLabel").textContent=t("Available "+schedule.quote+" balance on exchange");
  const balanceKnown=schedule.quoteBalance!==null&&schedule.quoteBalance!==undefined&&Number.isFinite(Number(schedule.quoteBalance));
  $("quoteBalance").textContent=t(balanceKnown?money(schedule.quoteBalance,schedule.quote):"—");
  const checkedAt=Date.parse(schedule.balanceUpdatedAt);
  const exchangeChecked=t(Number.isFinite(checkedAt)?'Exchange last checked {date}':'Waiting for account check').replace('{date}',dateLabel(checkedAt,schedule.timezone||'UTC'));
  $('botStatus').title=exchangeChecked;$('botStatus').setAttribute('aria-description',exchangeChecked);
  nextPurchaseTimestamp=Number.isFinite(target)?target:null;

  nextPurchaseMessage=schedule.nextPurchaseStatus||"Not scheduled";
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
  if(!schedule.withdrawalsEnabled)$('estimatedWithdrawalAt').textContent=t('Automatic withdrawals disabled');
  sectionFeedback("scheduleFeedback","");
 }catch(e){if(request===scheduleRequest){$("botStatusLabel").textContent=t("Connection unavailable; showing previous values");updateStatusLight("error");sectionFeedback("scheduleFeedback","")}}
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
function selectQuickRange(selected){
 for(const id of ['monthRange','yearRange','customRange'])$(id).setAttribute('aria-pressed',String(id===selected));
}
for(const id of ['monthRange','yearRange','customRange'])$(id).addEventListener('click',async()=>{
 selectQuickRange(id);
 if(id==='customRange'){$('start').focus();return}
 const now=new Date(),start=new Date(now.getFullYear(),id==='yearRange'?0:now.getMonth(),1);
 $('start').value=localInput(start.getTime());$('end').value=localInput(now.getTime());$('interval').value='';
 await saveReportFrom();currentPage=1;loadAnalytics();
});
$("interval").addEventListener("change",()=>{selectQuickRange("customRange");applySelectedInterval();saveReportFrom();saveReportView();currentPage=1;loadAnalytics()});
["start","end"].forEach(id=>$(id).addEventListener("change",()=>{selectQuickRange("customRange");$("interval").value="";saveReportView();if(id==="start")return saveReportFrom()}));
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
 renderPurchaseChart(d.purchaseSeries,currencyRates,livePrice,displayCurrency,moneyAvailable,p);
 $('modeBadge').textContent=t(d.configuration.liveTrading?'Live':'Simulation');
 $('withdrawalBadge').textContent=t(d.configuration.withdrawalsEnabled?'Enabled':'Disabled');
 $("buyCount").textContent=t(d.summary.buyCount);$("buyBtc").textContent=t(btc(d.summary.boughtBtc));
 $("buyVolume").textContent=t(moneyAvailable?money(converted.buyVolume,displayCurrency):"—");$("avgPrice").textContent=t(moneyAvailable?"Average: "+money(Number(d.summary.boughtBtc)>0?converted.buyVolume/Number(d.summary.boughtBtc):0,displayCurrency)+"/BTC":"Conversion unavailable");
 $("tradeFees").textContent=t(moneyAvailable?money(converted.tradeFees,displayCurrency):"—");$("withdrawBtc").textContent=t(btc(d.summary.withdrawnBtc));
 $("withdrawFees").textContent=t(moneyAvailable?money(converted.withdrawalFees,displayCurrency):"—");$("netBtc").textContent=t(btc(d.summary.netBtc));
 activityRates=currencyRates;activityRows=d.activities;activityTotal=d.pagination.total;activityPages=d.pagination.pages;currentPage=d.pagination.page;renderActivities();
 }catch(e){if(request===reportRequest)showError(e.message)}
 finally{if(request===reportRequest){$("refresh").ariaBusy="false";$("periodReport").ariaBusy="false";sectionFeedback("reportFeedback","")}}
}
$("refresh").addEventListener("click",()=>{currentPage=1;loadAnalytics()});
async function downloadParqetCsv(){
 logUiEvent("export_clicked");
 actionFeedback("export",t("Generating CSV…"),false,true);
 try{
  const p=selectedPeriod(),response=await fetch("/api/export.csv?start="+p.start+"&end="+p.end);
  if(!response.ok){const d=await response.json();throw new Error(d.error||"Could not generate the CSV export.")}
  const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement("a");
  a.href=url;a.download="parqet_btc_"+new Date(p.start).toISOString().slice(0,10)+"_"+new Date(p.end).toISOString().slice(0,10)+".csv";
  a.click();URL.revokeObjectURL(url);
 actionFeedback("export",t("CSV export prepared."),false);
 }catch(e){actionFeedback("export",t(e.message),true)}
 finally{actionFeedback("export",null,false,false)}
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
 $("withdrawMessage").textContent=t(d.reason||"Manual withdrawals are available. Automatic withdrawals may remain disabled.");
 return d;
}
function actionFeedback(action,message,error=false,busy=null){
 const frame=$("settingsFrame");
 frame?.contentWindow?.postMessage({type:'dca-dashboard-action-feedback',action,message,error,busy},window.location.origin);
}
function showWithdrawalMessage(message,error=true){
 $("withdrawMessage").textContent=t(message);
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
  $("withdrawMessage").textContent=t(configuration.reason||"");
  actionFeedback("withdraw","",false);
  return;
 }
 showWithdrawalMessage("Submitting withdrawal…",false);
 const result=await withdrawalPost("/api/withdrawal/confirm",{token:p.token});showWithdrawalMessage(result.message,false);
 $("interval").value="";$("end").value=localInput(Date.now()+60000);currentPage=1;await loadAnalytics();
 }catch(e){showWithdrawalMessage(e.message)}
 finally{actionFeedback("withdraw",null,false,false)}
}
window.DCA_DASHBOARD_ACTIONS={withdraw:requestManualWithdrawal,export:downloadParqetCsv};
loadWithdrawalConfiguration().catch(e=>{showWithdrawalMessage(e.message)});
refreshPurchaseSchedule();

(async()=>{
 try{await loadIntervals()}catch(e){
  $("interval").value="";$("start").value=localInput(Date.parse($("reportFrom").value)||Date.now()-1000);$("end").value=localInput(Date.now());
  sectionFeedback("intervalFeedback","Withdrawal intervals unavailable. Custom dates remain available.",true);
 }
 restoreReportView();await loadAnalytics();
})();
