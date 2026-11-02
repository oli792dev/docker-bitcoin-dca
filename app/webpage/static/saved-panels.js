// Disclosures are a per-visit view, never a persisted preference.
(()=>{
 function collapseSections(){
  document.querySelectorAll('details.report-details,details.period-activities,details.dashboard-footnotes').forEach(section=>{section.open=false});
 }
 collapseSections();
 // Browsers may restore open states when returning through their page cache.
 window.addEventListener?.('pageshow',collapseSections);
})();
