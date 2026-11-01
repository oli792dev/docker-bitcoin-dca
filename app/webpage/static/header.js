
(()=>{
 const brand=document.querySelector(".top .dashboard-brand");
 if(!brand)return;
 let pending=false;
 function updateHeader(){
  document.body.classList.toggle("compact-brand-visible",window.scrollY>70);
  document.body.classList.toggle("header-actions-hidden",window.scrollY>70);
  pending=false;
 }
 window.addEventListener("scroll",()=>{if(!pending){pending=true;requestAnimationFrame(updateHeader)}},{passive:true});
 window.addEventListener("resize",updateHeader);
 updateHeader();
})();
