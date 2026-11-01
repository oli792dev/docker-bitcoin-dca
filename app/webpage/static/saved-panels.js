
(()=>{
 let saved={};try{const value=JSON.parse(localStorage.getItem("bitcoinDcaPanels")||"{}");if(value&&typeof value==="object")saved=value}catch(e){}
 document.querySelectorAll("details.panel").forEach(panel=>{
  const key=panel.getAttribute("aria-labelledby");
  if(typeof saved[key]==="boolean")panel.open=saved[key];
  panel.addEventListener("toggle",()=>{saved[key]=panel.open;try{localStorage.setItem("bitcoinDcaPanels",JSON.stringify(saved))}catch(e){}});
 });
})();
