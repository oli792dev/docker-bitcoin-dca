(()=>{
 let saved={};try{const value=JSON.parse(localStorage.getItem("bitcoinDcaPanels")||"{}");if(value&&typeof value==="object")saved=value}catch(e){}
 document.querySelectorAll("details.panel").forEach(panel=>{
  const key=panel.getAttribute("aria-labelledby");
  if(typeof saved[key]==="boolean")panel.open=saved[key];
  panel.addEventListener("toggle",()=>{saved[key]=panel.open;try{localStorage.setItem("bitcoinDcaPanels",JSON.stringify(saved))}catch(e){}});
  if(!panel.animate)return;
  const summary=panel.querySelector('summary');
  if(!summary)return;
  let animation=null,expanded=panel.open;
  summary.addEventListener('click',event=>{
   if(event.target.closest('a,button,input,select'))return;
   event.preventDefault();
   const from=panel.getBoundingClientRect().height;
   if(animation){animation.onfinish=null;animation.cancel()}
   expanded=!expanded;
   panel.style.height='';panel.open=true;
   const to=expanded?panel.getBoundingClientRect().height:summary.getBoundingClientRect().height+2;
   panel.classList.add('panel-animating');
   animation=panel.animate([{height:from+'px'},{height:to+'px'}],{duration:240,easing:'cubic-bezier(.2,.8,.2,1)'});
   animation.onfinish=()=>{panel.open=expanded;panel.classList.remove('panel-animating');animation=null};
  });
 });
})();
