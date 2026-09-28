(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const base = 'https://gram.rin.ms';
  const series = {name:'series',label:'Серия цен',value:'reference',options:[['reference','reference — по времени'],['telegram-usd','telegram-usd — архив USD'],['calcmula-usd','calcmula-usd — текущие USD'],['calcmula-usdt','calcmula-usdt — прежние USDT']]};
  const age = {name:'max_age_seconds',label:'Допустимый возраст записи',hint:'секунды',value:'900',type:'number',min:0,max:86400};
  const dayZone = {name:'timezone',label:'Часовой пояс дня',value:'UTC',options:[['UTC','UTC'],['Europe/Moscow','Europe/Moscow (МСК)'],['Europe/Berlin','Europe/Berlin'],['America/New_York','America/New_York']]};
  const endpoints = {
    at:{path:'/v1/ton/price',fields:[{name:'at',label:'Дата или дата со временем',value:'2024-02-05'}],extra:[dayZone,age,series]},
    latest:{path:'/v1/ton/price/latest',fields:[],extra:[age,series]},
    history:{path:'/v1/ton/history',fields:[{name:'from',label:'Начало периода',hint:'включено',value:'2024-02-05T00:00:00Z'},{name:'to',label:'Конец периода',hint:'исключён',value:'2024-02-06T00:00:00Z'}],extra:[{name:'limit',label:'Записей на странице',value:'3',type:'number',min:1,max:1000},{name:'cursor',label:'Курсор следующей страницы',value:'',optional:true},series]},
    daily:{path:'/v1/ton/daily',fields:[{name:'date',label:'Дата',value:'2024-02-05',type:'date'},{name:'timezone',label:'Часовой пояс',value:'Europe/Moscow',options:[['Europe/Moscow','Europe/Moscow (МСК)'],['UTC','UTC'],['Europe/Berlin','Europe/Berlin'],['America/New_York','America/New_York']]}],extra:[series]},
    coverage:{path:'/v1/ton/coverage',fields:[],extra:[series]}
  };
  let language='curl', sequence=0, controller=null, currentCode='', toastTimer;
  const valuesByEndpoint=new Map();
  const initialJSON=JSON.parse($('response-code').textContent);
  function toast(message){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').hidden=false;toastTimer=setTimeout(()=>{$('toast').hidden=true;},2600);}
  async function copy(text){try{await navigator.clipboard.writeText(text);toast('Скопировано');}catch{toast('Браузер запретил копирование. Выделите код и скопируйте вручную.');}}
  function highlight(value){
    const target=$('response-code'), json=JSON.stringify(value,null,2);
    target.replaceChildren();
    const tokens=/("(?:\\.|[^"\\])*"\s*:|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)/g;
    let last=0;
    for(const match of json.matchAll(tokens)){
      target.append(document.createTextNode(json.slice(last,match.index)));
      const span=document.createElement('span');
      span.className=match[0].endsWith(':')?'json-key':match[0].startsWith('"')?'json-string':/^(true|false|null)$/.test(match[0])?'json-null':'json-number';
      span.textContent=match[0];target.append(span);last=match.index+match[0].length;
    }
    target.append(document.createTextNode(json.slice(last)));
  }
  function remember(){
    const values={};document.querySelectorAll('#request-form [data-param]').forEach(input=>{values[input.name]=input.value;});
    if($('request-fields').dataset.endpoint)valuesByEndpoint.set($('request-fields').dataset.endpoint,values);
  }
  function field(definition,saved){
    const wrapper=document.createElement('div');wrapper.className='field';
    const label=document.createElement('label');label.htmlFor='param-'+definition.name;label.textContent=definition.label;
    if(definition.hint){const hint=document.createElement('span');hint.textContent=definition.hint;label.append(hint);}
    const control=document.createElement(definition.options?'select':'input');control.id=label.htmlFor;control.name=definition.name;control.dataset.param='true';
    if(definition.options){definition.options.forEach(([value,text])=>{const option=document.createElement('option');option.value=value;option.textContent=text;control.append(option);});}
    else{control.type=definition.type||'text';control.spellcheck=false;control.autocomplete='off';if(definition.min!==undefined)control.min=definition.min;if(definition.max!==undefined)control.max=definition.max;if(definition.type==='number')control.step='1';}
    control.required=!definition.optional;control.value=saved??definition.value;
    control.addEventListener('input',updateCode);control.addEventListener('change',updateCode);
    wrapper.append(label,control);
    if(definition.name==='at'){const help=document.createElement('p');help.id='at-mode-note';help.className='field-note';control.setAttribute('aria-describedby',help.id);wrapper.append(help);}
    return wrapper;
  }
  function chooseEndpoint(){
    remember();controller?.abort();sequence++;
    $('run-request').disabled=false;$('run-request').querySelector('span').textContent='Выполнить запрос';$('response-code-panel').removeAttribute('aria-busy');
    const key=$('endpoint').value, config=endpoints[key], saved=valuesByEndpoint.get(key)||{};
    $('request-fields').replaceChildren(...config.fields.map(def=>field(def,saved[def.name])));
    $('request-fields').dataset.endpoint=key;$('request-fields').hidden=config.fields.length===0;
    $('extra-fields').replaceChildren(...config.extra.map(def=>field(def,saved[def.name])));$('advanced').open=false;
    $('form-message').textContent='Параметры готовы. Ответ обновится после запроса.';$('form-message').removeAttribute('data-error');updateCode();
  }
  function parameters(){const params=new URLSearchParams();document.querySelectorAll('#request-form [data-param]').forEach(input=>{if(!input.disabled&&input.value.trim()!=='')params.set(input.name,input.value.trim());});return params;}
  function updateCode(){
    if($('endpoint').value==='at'){
      const isDate=/^\d{4}-\d{2}-\d{2}$/.test($('param-at').value.trim());
      $('param-timezone').disabled=!isDate;$('param-timezone').parentElement.hidden=!isDate;
      $('param-max_age_seconds').disabled=isDate;$('param-max_age_seconds').parentElement.hidden=isDate;
      $('at-mode-note').textContent=isDate?'Дата → сводка: первая, последняя, минимум и максимум. Часовой пояс — в дополнительных параметрах.':'Дата со временем → одна цена. Например, 2024-02-05T12:00:00+03:00. Можно ввести только 2024-02-05 для сводки.';
    }
    const url=base+endpoints[$('endpoint').value].path, entries=[...parameters().entries()];
    const quote=value=>"'"+value.replaceAll("'","'"+String.fromCharCode(92)+"''")+"'";
    if(language==='curl')currentCode=[`curl --get '${url}'`,...entries.map(([key,value])=>'  --data-urlencode '+quote(key+'='+value))].join(' '+String.fromCharCode(92)+'\n');
    else if(language==='python')currentCode='import json\nfrom urllib.parse import urlencode\nfrom urllib.request import Request, urlopen\n\nparams = '+JSON.stringify(Object.fromEntries(entries),null,2)+`\nurl = "${url}?" + urlencode(params)\n\nrequest = Request(url, headers={"User-Agent": "GramPricesClient/1.0", "Accept": "application/json"})\nwith urlopen(request, timeout=15) as response:\n    result = json.load(response)\n\nprint(result)`;
    else currentCode=`const url = new URL("${url}");\nurl.search = new URLSearchParams(`+JSON.stringify(Object.fromEntries(entries),null,2)+');\n\nconst response = await fetch(url);\nconst result = await response.json();\nif (!response.ok) throw new Error(result.code);\n\nconsole.log(result);';
    $('request-code').textContent=currentCode;
  }
  const errors={DATA_GAP:'Запись есть, но она старше допустимого значения. Попробуйте другой момент или измените max_age_seconds.',PRICE_NOT_FOUND:'До этого момента нет записей выбранного источника. Проверьте дату и покрытие данных.',PRICE_STALE:'Последняя цена устарела. Повторите запрос позже или проверьте состояние сборщика.',VALIDATION_ERROR:'Проверьте параметры. Укажите дату 2024-02-05 или время с часовым поясом: 2024-02-05T09:00:00Z.',FUTURE_TIMESTAMP:'Запрос относится к будущему. Выберите время, которое уже наступило.',DATABASE_UNAVAILABLE:'База временно недоступна. Повторите запрос позже.'};
  async function run(event){
    event.preventDefault();if(!$('request-form').reportValidity())return;
    controller?.abort();const ownSequence=++sequence;controller=new AbortController();const ownController=controller;
    const config=endpoints[$('endpoint').value], key=$('endpoint').value, path=config.path+'?'+parameters().toString(), button=$('run-request');
    button.disabled=true;button.querySelector('span').textContent='Выполняем запрос';$('response-code-panel').setAttribute('aria-busy','true');$('form-message').textContent='Отправляем GET-запрос к API…';$('form-message').removeAttribute('data-error');
    const started=performance.now(), timeout=setTimeout(()=>ownController.abort(),15000);
    try{
      const response=await fetch(path,{signal:ownController.signal,headers:{Accept:'application/json'},cache:'no-store'}),result=await response.json();
      if(ownSequence!==sequence)return;
      highlight(result);$('response-code-panel').scrollTop=0;$('response-title').textContent='Ответ API';$('response-status').textContent=`${response.status} ${response.ok?'OK':'Ошибка'}`;$('response-status').dataset.kind=response.ok?'success':'error';$('response-context').replaceChildren();
      for(const text of [config.path,`${Math.round(performance.now()-started)} мс · с учётом сети`]){const span=document.createElement('span');span.textContent=text;$('response-context').append(span);}
      if(response.ok){
        const data=result.data;$('form-message').textContent=`Запрос выполнен. HTTP ${response.status}.`;
        $('response-note').textContent=data?.price?`Найдено: ${data.price} ${data.quote_currency}. Время записи: ${data.observed_at}. Возраст относительно запроса: ${data.age_seconds} с.`:Array.isArray(data)?`Получено записей: ${data.length}. ${result.meta?.next_cursor?'Есть следующая страница: передайте meta.next_cursor в параметре cursor.':'Это последняя страница диапазона.'}`:data?.kind==='daily_summary'?(data.segments.length?'Сводка: первая, последняя, минимальная и максимальная цены. '+(data.is_day_complete?'День завершён.':'День ещё идёт; сводка неполная.'):'В этот день нет сохранённых наблюдений.'):'Границы данных и состояние последнего сбора. Время collector передаётся в Unix seconds.';
      }else{$('form-message').textContent=errors[result.code]||`API вернул ошибку ${result.code||response.status}. Подробности — в ответе.`;$('form-message').dataset.error='true';$('response-note').textContent='Ошибка возвращена самим API. Код и request_id можно использовать для диагностики.';}
    }catch(error){
      if(ownSequence!==sequence)return;
      $('response-status').textContent='Нет ответа';$('response-status').dataset.kind='error';$('form-message').dataset.error='true';$('form-message').textContent=error.name==='AbortError'?'API не ответил за 15 секунд. Повторите запрос.':'Не удалось получить JSON-ответ. Проверьте соединение и повторите запрос.';$('response-title').textContent='Предыдущий ответ';
    }finally{clearTimeout(timeout);if(ownSequence===sequence){button.disabled=false;button.querySelector('span').textContent='Выполнить запрос';$('response-code-panel').removeAttribute('aria-busy');}}
  }
  $('request-form').addEventListener('invalid',event=>{if($('advanced').contains(event.target))$('advanced').open=true;},true);
  $('request-form').addEventListener('submit',run);$('endpoint').addEventListener('change',chooseEndpoint);
  document.querySelectorAll('[data-endpoint]').forEach(button=>button.addEventListener('click',()=>{$('endpoint').value=button.dataset.endpoint;chooseEndpoint();$('playground').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});$('endpoint').focus({preventScroll:true});}));
  const tabs=[...document.querySelectorAll('[data-language]')];
  function selectLanguage(tab){language=tab.dataset.language;tabs.forEach(item=>{const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;});$('request-code-panel').setAttribute('aria-labelledby',tab.id);updateCode();}
  tabs.forEach((tab,index)=>{tab.addEventListener('click',()=>selectLanguage(tab));tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?tabs[0]:event.key==='End'?tabs.at(-1):tabs[(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length];selectLanguage(next);next.focus();});});
  $('copy-request').addEventListener('click',()=>copy(currentCode));$('copy-response').addEventListener('click',()=>copy($('response-code').textContent));
  async function check(){const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),10000);try{const response=await fetch('/v1/ton/price/latest',{signal:abort.signal,cache:'no-store'});$('connection').dataset.status=response.ok?'ready':'error';$('connection-label').textContent=response.ok?'API отвечает':response.status===503?'Курс недоступен':'Проверьте API';}catch{$('connection').dataset.status='error';$('connection-label').textContent='Нет соединения';}finally{clearTimeout(timeout);}}
  const requestedEndpoint=new URLSearchParams(location.search).get('endpoint');
  if(Object.hasOwn(endpoints,requestedEndpoint))$('endpoint').value=requestedEndpoint;
  chooseEndpoint();$('form-message').textContent='Параметры можно менять. Запросы идут к рабочему API.';highlight(initialJSON);check();
})();
