(() => {
'use strict';
const $=id=>document.getElementById(id);
  function menu(open){$('sidebar').classList.toggle('is-open',open);$('menu-toggle').setAttribute('aria-expanded',String(open));$('menu-toggle').setAttribute('aria-label',open?'Закрыть оглавление':'Открыть оглавление');}
  $('menu-toggle').addEventListener('click',()=>menu(!$('sidebar').classList.contains('is-open')));
  const links=[...document.querySelectorAll('.nav-link')];links.forEach(link=>link.addEventListener('click',()=>menu(false)));
  function filter(){const query=$('doc-search').value.toLocaleLowerCase('ru').trim();let count=0;links.forEach(link=>{const match=(link.textContent+' '+link.dataset.search).toLocaleLowerCase('ru').includes(query);link.hidden=!match;if(match)count++;});document.querySelectorAll('.nav-group').forEach(group=>{group.hidden=![...group.querySelectorAll('.nav-link')].some(link=>!link.hidden);});$('search-empty').hidden=count>0;}
  $('doc-search').addEventListener('input',filter);
  document.addEventListener('keydown',event=>{const editing=/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);if((event.key==='/'&&!editing)||((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k')){event.preventDefault();if(matchMedia('(max-width:900px)').matches)menu(true);$('doc-search').focus();}if(event.key==='Escape'){if($('doc-search').value){$('doc-search').value='';filter();}else if($('sidebar').classList.contains('is-open')){menu(false);$('menu-toggle').focus();}}});
  if('IntersectionObserver'in window){const visible=new Set();const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>entry.isIntersecting?visible.add(entry.target.id):visible.delete(entry.target.id));const current=links.find(link=>visible.has(link.hash.slice(1)));if(current)links.forEach(link=>{const active=link===current;link.classList.toggle('is-active',active);if(active)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});},{rootMargin:'-100px 0px -55% 0px',threshold:0});links.forEach(link=>{const section=document.querySelector(link.hash);if(section)observer.observe(section);});}

})();
