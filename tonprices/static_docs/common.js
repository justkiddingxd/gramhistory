(() => {
'use strict';
const $=id=>document.getElementById(id);let timer;
async function copy(text){try{await navigator.clipboard.writeText(text);$('toast').textContent='Скопировано';}catch{$('toast').textContent='Не удалось скопировать. Выделите текст и скопируйте вручную.';}clearTimeout(timer);$('toast').hidden=false;timer=setTimeout(()=>{$('toast').hidden=true;},2600);}
document.querySelectorAll('[data-copy-text]').forEach(button=>button.addEventListener('click',()=>copy(button.dataset.copyText)));
document.querySelectorAll('[data-copy-target]').forEach(button=>button.addEventListener('click',()=>copy($(button.dataset.copyTarget).textContent)));
function theme(value,persist=false){document.documentElement.dataset.theme=value;$('theme-toggle').setAttribute('aria-label',value==='dark'?'Включить светлую тему':'Включить тёмную тему');if(persist){try{localStorage.setItem('gram-docs-theme',value);}catch{}}}
let savedTheme;try{savedTheme=localStorage.getItem('gram-docs-theme');}catch{}theme(savedTheme==='light'?'light':'dark');$('theme-toggle').addEventListener('click',()=>theme(document.documentElement.dataset.theme==='dark'?'light':'dark',true));
})();
