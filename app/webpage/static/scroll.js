
(()=>{
 const areas=[...document.querySelectorAll(".horizontal-scroll")];
 const timers=new WeakMap();
 function update(area){
  const overflow=area.clientWidth>0&&area.scrollWidth>area.clientWidth+1;
  area.classList.toggle("has-overflow",overflow);
  area.classList.toggle("has-more-right",overflow&&area.scrollLeft+area.clientWidth<area.scrollWidth-2);
 }
 const observer=new ResizeObserver(()=>areas.forEach(update));
 areas.forEach(area=>{
  observer.observe(area);
  if(area.firstElementChild)observer.observe(area.firstElementChild);
  area.addEventListener("scroll",()=>{
   update(area);
   area.classList.add("is-scrolling");
   clearTimeout(timers.get(area));
   timers.set(area,setTimeout(()=>area.classList.remove("is-scrolling"),180));
  },{passive:true});
  update(area);
 });
 document.querySelectorAll("details.panel").forEach(panel=>panel.addEventListener("toggle",()=>areas.forEach(update)));
})();
