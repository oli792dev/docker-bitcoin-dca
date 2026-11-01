(()=>{
 const state=globalThis.DCA_I18N,catalog=state.catalog;
 state.locale=state.language==='de'?'de-DE':'en-GB';
 const patterns=Object.entries(catalog).filter(([source])=>source.includes('{')).map(([source,target])=>{
  const names=[];let expression='',last=0;
  for(const match of source.matchAll(/\{(\w+)\}/g)){
   expression+=source.slice(last,match.index).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'([\\s\\S]+?)';
   names.push(match[1]);last=match.index+match[0].length;
  }
  expression+=source.slice(last).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  return {pattern:new RegExp('^'+expression+'$'),names,target};
 });
 state.t=value=>{
  if(typeof value!=='string'||state.language!=='de')return value;
  if(Object.prototype.hasOwnProperty.call(catalog,value))return catalog[value];
  for(const {pattern,names,target} of patterns){const match=pattern.exec(value);if(match){const values=Object.fromEntries(names.map((name,index)=>[name,match[index+1]]));return target.replace(/\{(\w+)\}/g,(_,name)=>values[name]);}}
  return value;
 };
})();
