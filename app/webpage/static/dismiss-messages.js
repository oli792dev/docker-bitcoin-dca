
document.querySelectorAll("[data-dismiss]").forEach(button=>button.addEventListener("click",()=>{
 const message=document.getElementById(button.dataset.dismiss);
 if(message){message.classList.add("hidden");message.textContent=""}
}));
