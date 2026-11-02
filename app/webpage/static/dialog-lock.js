
(()=>{
 const dialogs=[...document.querySelectorAll('dialog')];
 const body=document.body,root=document.documentElement;
 let saved=null;
 function update(){
  const open=dialogs.some(dialog=>dialog.open);
  if(open&&!saved){
   const gutter=Math.max(0,window.innerWidth-root.clientWidth);
   const padding=parseFloat(window.getComputedStyle(body).paddingRight)||0;
   saved={x:window.scrollX,y:window.scrollY,body:body.style.cssText,root:root.style.cssText};
   root.style.overflow='hidden';root.style.overscrollBehavior='none';
   body.style.position='fixed';body.style.top=-saved.y+'px';body.style.left=-saved.x+'px';
   body.style.width='100%';body.style.overflow='hidden';body.style.paddingRight=padding+gutter+'px';
  }else if(!open&&saved){
   const previous=saved;saved=null;
   body.style.cssText=previous.body;root.style.cssText=previous.root;
   const behavior=root.style.scrollBehavior;root.style.scrollBehavior='auto';
   window.scrollTo(previous.x,previous.y);root.style.scrollBehavior=behavior;
  }
 }
 const observer=new MutationObserver((records=[])=>{
  update();
  for(const {target:dialog} of records){
   if(dialog.open&&dialog.animate){
    dialog.getAnimations().forEach(animation=>animation.cancel());
    dialog.animate([{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)'});
   }
  }
 });
 dialogs.forEach(dialog=>observer.observe(dialog,{attributes:true,attributeFilter:['open']}));
 update();
})();
