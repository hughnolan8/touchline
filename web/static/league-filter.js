const originalFetch=window.fetch.bind(window);
window.fetch=(input,options)=>{
 const url=new URL(typeof input==='string'?input:input.url,window.location.origin);
 if(url.pathname.startsWith('/api/v1/')&&document.querySelector('#league')?.value)url.searchParams.set('league',document.querySelector('#league').value);
 return originalFetch(url.toString(),options);
};
const picker=document.querySelector('#league'),page=new URL(window.location);
picker.value=page.searchParams.get('league')||'';
picker.addEventListener('change',()=>{const next=new URL(window.location);picker.value?next.searchParams.set('league',picker.value):next.searchParams.delete('league');window.location.assign(next)});
