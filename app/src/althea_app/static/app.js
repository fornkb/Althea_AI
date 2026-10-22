const $ = (query, parent = document) => parent.querySelector(query);
const $$ = (query, parent = document) => [...parent.querySelectorAll(query)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>', upload:'<path d="M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4"/>',
  mic:'<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/>',
  file:'<path d="M14 2H5v20h14V7zM14 2v6h5M8 13h8m-8 4h6"/>', play:'<path d="m8 4 12 8-12 8z"/>',
  check:'<path d="m5 12 4 4L19 6"/>', clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  back:'<path d="M19 12H5m5-5-5 5 5 5"/>', download:'<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>', settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
  x:'<path d="m6 6 12 12M6 18 18 6"/>', external:'<path d="M14 3h7v7m0-7L10 14M9 5H3v16h16v-6"/>'
};
const icon = (name, cls='') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const time = seconds => `${Math.floor(seconds/60).toString().padStart(2,'0')}:${Math.floor(seconds%60).toString().padStart(2,'0')}`;
const date = value => new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const providerName = p => ({gemini:'Gemini API',vertex:'Google Cloud',sample:'Sample demo'}[p] || p);
const jobUrl = (p,id) => `/jobs/${encodeURIComponent(p)}/${encodeURIComponent(id)}`;
const apiJob = (p,id) => `/api/jobs/${encodeURIComponent(p)}/${encodeURIComponent(id)}`;
const state = {csrf:'',settings:{},file:null,fileUrl:null,method:'upload',title:'',includeEvidence:false,active:null,jobs:[],snapshot:null,tab:'transcript',selected:new Set(),route:0};
let toastTimer, pollTimer, recorder=null;
const resultTabs=['transcript','claims','compare','evidence'];
function savedTab() {
  const hash=location.hash.slice(1);
  if(resultTabs.includes(hash))return hash;
  try {const stored=localStorage.getItem('althea:view:'+location.pathname);if(resultTabs.includes(stored))return stored;}catch{}
  return 'transcript';
}
function rememberTab(tab) {
  state.tab=tab;
  history.replaceState({},'',location.pathname+'#'+tab);
  try {localStorage.setItem('althea:view:'+location.pathname,tab);}catch{}
}


async function api(url, options={}) {
  const headers = {...options.headers};
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token']=state.csrf;
  if (options.body && !(options.body instanceof FormData)) {headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body);}
  const response=await fetch(url,{...options,headers});
  const data=await response.json();
  if (!response.ok) throw new Error(data.error || 'This action could not finish.');
  return data;
}
function toast(message,error=false) {
  const el=$('#toast'); el.textContent=message; el.classList.toggle('error',error); el.hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>{el.hidden=true;},6500);
}
function empty(title,description,action='') {return `<div class="empty-state"><span class="empty-icon">${icon('file')}</span><h3>${title}</h3><p>${description}</p>${action}</div>`;}
function badge(status) {return `<span class="badge badge-${esc(status)}"><span></span>${esc(status.replaceAll('_',' '))}</span>`;}
function safeUrl(raw) {try {const u=new URL(raw);return ['http:','https:'].includes(u.protocol)&&!u.username&&!u.password ? esc(u.href) : '#';}catch{return '#';}}
function notice(message,kind='info') {return `<div class="notice ${kind}">${esc(message)}</div>`;}
function setFile(file) {
  if (!file) return;
  if (!/\.(mp3|wav|json)$/i.test(file.name)) return toast('Choose an MP3, WAV or complete transcript JSON file.',true);
  const max=state.settings.provider==='gemini'&&!/\.json$/i.test(file.name) ? 13 : 20;
  if (!file.size || file.size>max*1024*1024) return toast(`Choose a nonempty file smaller than ${max} MiB.`,true);
  if(state.fileUrl) URL.revokeObjectURL(state.fileUrl);
  state.file=file; state.fileUrl=URL.createObjectURL(file);
  if (!state.title) state.title=file.name.replace(/\.[^.]+$/,'').replaceAll('_',' ');
  renderInput();
}

document.addEventListener('click',event=>{
  const anchor=event.target.closest('a');
  if(!anchor || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button!==0 || anchor.target || anchor.download) return;
  const url=new URL(anchor.href,location.href);
  if(url.pathname===location.pathname&&url.hash==='#main'){event.preventDefault();$('#main').focus();return;}
  if(url.origin===location.origin && (['/','/history','/settings'].includes(url.pathname)||url.pathname.startsWith('/jobs/'))) {
    event.preventDefault(); navigate(url.pathname+url.hash);
  }
});
window.addEventListener('popstate',()=>route());
window.addEventListener('beforeunload',event=>{if(recorder){event.preventDefault(); event.returnValue='';}});
function navigate(path) {if(location.pathname+location.hash!==path)history.pushState({},'',path);route();window.scrollTo({top:0,behavior:'instant'});}

async function route() {
  const generation=++state.route;
  if(recorder && location.pathname!=='/') await stopRecording();
  const path=location.pathname;
  if(path.startsWith('/jobs/')&&!state.active)$('#activity').hidden=true;
  const nav=path==='/history'||path.startsWith('/jobs/')?'history':path==='/settings'?'settings':'home';
  $$('[data-nav]').forEach(a=>{if(a.dataset.nav===nav)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  try {
    if(path==='/') {renderHome(); const data=await api('/api/jobs'); if(generation!==state.route)return;state.jobs=data.jobs;renderRecents();}
    else if(path==='/history') {$('#main').innerHTML=pageHeading('YOUR LIBRARY','Conversations, kept.','Pick up where you left off. Every analysis stays on this device.')+'<div class="panel loading">Loading your conversations…</div>';const data=await api('/api/jobs');if(generation!==state.route)return;state.jobs=data.jobs;renderHistory();}
    else if(path==='/settings') {$('#main').innerHTML=pageHeading('MAKE IT YOURS','Workspace settings.','Connect your provider once. Come back to the conversation.')+'<div class="panel loading">Loading settings…</div>';const data=await api('/api/settings');if(generation!==state.route)return;state.settings=data.settings;renderSettings(data.checks);}
    else {
      const match=path.match(/^\/jobs\/(gemini|vertex|sample)\/([^/]+)$/);
      if(!match) throw new Error('This page could not be found.');
      $('#main').innerHTML='<div class="panel loading">Opening your conversation…</div>';
      const data=await api(apiJob(match[1],match[2]));if(generation!==state.route)return;
      state.snapshot=data.snapshot; state.usage=data.usage;state.versions=data.versions;state.jobProvider=match[1];state.selected.clear();state.tab=savedTab();renderJob();
    }
  } catch(error) {if(generation===state.route)$('#main').innerHTML=empty('Something needs attention.',esc(error.message),'<a href="/" class="button primary">Back to workspace</a>');}
  document.title=`${nav==='home'?'Workspace':nav==='settings'?'Settings':state.snapshot&&path.startsWith('/jobs/')?state.snapshot.title:'History'} · Althea`;
}
function pageHeading(eyebrow,title,subtitle,action='') {return `<section class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="muted">${subtitle}</p></div>${action}</section>`;}

function renderHome() {
  $('#main').innerHTML=`<section class="hero"><div class="hero-copy"><p class="eyebrow"><span class="eyebrow-line"></span> A LITTLE MORE CLARITY</p><h1>Hear the conversation.<br>See the <span>whole picture.</span></h1><p>A thoughtful workspace for turning debate audio into<br class="desktop-break"> clear claims, meaningful comparisons and evidence.</p></div><div class="sound-art" aria-hidden="true"><span class="orbit orbit-one"></span><span class="orbit orbit-two"></span><span class="orbit orbit-three"></span><div class="wave-bars">${[18,32,51,28,73,100,58,85,40,65,32,18,36,58,23].map((h,i)=>`<i class="bar bar-${i}" data-height="${h}"></i>`).join('')}</div><span class="sound-note">Clarity starts with listening.</span><span class="art-dot art-dot-one"></span><span class="art-dot art-dot-two"></span></div></section>
    <section class="workspace-grid"><div class="panel input-card"><div class="section-heading"><div><p class="eyebrow">NEW CONVERSATION</p><h2>What are we listening to?</h2></div><span class="provider-chip"><span class="status-dot"></span>${providerName(state.settings.provider)}</span></div>
    <div class="input-tabs" role="tablist" aria-label="Audio source"><button type="button" data-method="upload" role="tab">${icon('upload')} Upload audio</button><button type="button" data-method="record" role="tab">${icon('mic')} Record audio</button></div><div id="input-pane"></div></div>
    <aside class="workspace-aside"><div class="guide-step"><span>01</span><div><h3>Bring the conversation</h3><p>Upload a debate, interview or discussion. Or record one right here.</p></div></div><div class="guide-step"><span>02</span><div><h3>Follow the claims</h3><p>Read the transcript and compare what each speaker actually said.</p></div></div><div class="guide-step"><span>03</span><div><h3>Look at the evidence</h3><p>Choose disagreements to check against retrieved sources.</p></div></div><div class="sample-card"><span class="tiny-label">SAVED ON THIS DEVICE</span><h3>Pick up the conversation.</h3><p>Your recordings, claims and evidence stay together in History.</p><a href="/history" class="text-button">Open History ${icon('arrow')}</a></div></aside></section>
    <section class="recent-section"><div class="section-heading"><div><p class="eyebrow">PICK UP WHERE YOU LEFT OFF</p><h2>Recent conversations</h2></div><a class="text-link" href="/history">View history ${icon('arrow')}</a></div><div id="recent-jobs"></div></section>`;
  $$('[data-method]').forEach(button=>button.addEventListener('click',async()=>{if(recorder)await stopRecording();state.method=button.dataset.method;renderInput();}));
  renderInput();renderRecents();
}
function renderInput() {
  const pane=$('#input-pane');if(!pane)return;
  $$('[data-method]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.method===state.method)));
  const hasFile=!!state.file;
  pane.innerHTML=`${state.method==='record'?`<div class="record-zone"><button id="record-toggle" class="microphone ${recorder?'recording':''}" aria-label="${recorder?'Stop recording':'Start recording'}">${recorder?'<span class="stop-square"></span>':icon('mic')}</button><h3 id="record-label">${recorder?'Listening…':'A conversation starts here.'}</h3><p id="record-caption">${recorder?'Choose stop when you’re done.':'Tap the microphone when you’re ready.'}</p><span id="record-time" class="record-time">${recorder?time(recorder.seconds):'00:00'}</span></div>`:
    `<label class="drop-zone ${hasFile?'has-file':''}" id="drop-zone" for="audio-file"><span class="upload-symbol">${icon(hasFile?'check':'upload')}</span><strong>${hasFile?esc(state.file.name):'Drop your audio here'}</strong><span>${hasFile?`${(state.file.size/1024/1024).toFixed(1)} MB · Click to choose another file`:'or <span class="underlined">browse files</span>'}</span><small>MP3 or WAV · English · Up to 5 minutes</small><input type="file" id="audio-file" accept=".mp3,.wav,.json,audio/mpeg,audio/wav" class="visually-hidden"></label>`}
    ${hasFile?`<div class="file-preview"><div class="preview-label">${icon('file')}<span>${esc(state.file.name)}</span><button class="icon-button" id="remove-file" aria-label="Remove selected recording">${icon('x')}</button></div>${/\.json$/i.test(state.file.name)?'<p class="muted">Complete transcript JSON selected.</p>':`<audio controls preload="metadata" src="${state.fileUrl}"></audio>`}</div>`:''}
    <label class="field-label" for="conversation-title">Conversation title <span>Optional</span></label><input id="conversation-title" class="input" maxlength="160" placeholder="e.g. Presidential debate · economy" value="${esc(state.title)}">
    <div class="input-actions"><label class="checkbox-label"><input id="include-evidence" type="checkbox"><span>Also check disagreements against web evidence<small>Optional · Provider access and search quotas apply</small></span></label><button id="analyze" class="button primary" ${!hasFile||recorder||state.active?'disabled':''}>Analyze conversation ${icon('arrow')}</button></div>
    ${state.settings.provider==='gemini'&&!state.settings.key_configured?'<div class="setup-note">One quick setup: <a href="/settings">add your Gemini key in Settings</a> to analyze audio. You can try the sample right away.</div>':'<div class="privacy-note">Your recording is sent to your selected provider only when you choose Analyze.</div>'}`;
  $('#conversation-title').oninput=e=>{state.title=e.target.value;};
  $('#include-evidence').checked=state.includeEvidence;
  $('#include-evidence').onchange=e=>{state.includeEvidence=e.target.checked;};
  $('#analyze').onclick=()=>startAnalysis(false);
  if($('#record-toggle'))$('#record-toggle').onclick=()=>recorder?stopRecording():startRecording();
  if($('#audio-file')){
    $('#audio-file').onchange=e=>setFile(e.target.files[0]);
    const drop=$('#drop-zone');
    ['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('drag-over');}));
    ['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('drag-over');}));
    drop.addEventListener('drop',e=>setFile(e.dataTransfer.files[0]));
  }
  if($('#remove-file'))$('#remove-file').onclick=()=>{state.file=null;if(state.fileUrl)URL.revokeObjectURL(state.fileUrl);state.fileUrl=null;renderInput();};
}
async function startAnalysis(sample) {
  if(state.active)return toast('An analysis is already running. You can keep navigating.',true);
  if(!sample&&!state.file)return toast('Choose or record audio first.',true);
  if(!sample&&state.settings.provider==='gemini'&&!state.settings.key_configured){toast('Add your Gemini key in Settings first.',true);return navigate('/settings');}
  const form=new FormData();form.set('kind',sample?'sample':'audio');form.set('provider',state.settings.provider);form.set('title',sample?'Riverton · sample conversation':state.title);form.set('verify',String(sample||!!$('#include-evidence')?.checked));
  if(!sample)form.set('file',state.file);
  const button=sample?$('#try-sample'):$('#analyze'); if(button)button.disabled=true;
  try {const result=await api('/api/jobs',{method:'POST',body:form});state.operationOrigin=location.pathname;followOperation(result.operation_id);}
  catch(error){toast(error.message,true);if(button)button.disabled=false;}
}
function renderRecents(){const element=$('#recent-jobs');if(!element)return;const jobs=state.jobs.slice(0,3);element.innerHTML=jobs.length?`<div class="recent-grid">${jobs.map(job=>`<a href="${jobUrl(job.provider,job.job_id)}" class="recent-card"><div class="recent-top"><span class="conversation-icon">${icon(job.provider==='sample'?'file':'mic')}</span>${badge(job.status)}</div><h3>${esc(job.title)}</h3><div class="card-meta"><span>${providerName(job.provider)} · ${date(job.updated_at)}</span>${icon('arrow')}</div></a>`).join('')}</div>`:'<div class="quiet-empty">A little quiet here. Your first conversation will appear once you analyze it.</div>';}

function renderHistory() {
  $('#main').innerHTML=pageHeading('YOUR LIBRARY','Conversations, kept.','Pick up where you left off. Every analysis stays on this device.','<a href="/" class="button primary">New conversation '+icon('arrow')+'</a>')+
    `<section class="panel history-panel"><div class="history-tools"><label class="search-input">${icon('search')}<input id="history-search" type="search" placeholder="Find a conversation" aria-label="Search conversations"></label><select id="history-status" class="input compact" aria-label="Filter conversations by status"><option value="all">All conversations</option><option value="complete">Complete</option><option value="failed">Needs attention</option><option value="partial">Partial</option></select></div><div id="history-list"></div></section>`;
  $('#history-search').oninput=renderHistoryList;$('#history-status').onchange=renderHistoryList;renderHistoryList();
}
function renderHistoryList(){const term=$('#history-search').value.toLowerCase(),status=$('#history-status').value;const jobs=state.jobs.filter(j=>j.title.toLowerCase().includes(term)&&(status==='all'||status===j.status));$('#history-list').innerHTML=jobs.length?jobs.map(job=>`<a class="history-row" href="${jobUrl(job.provider,job.job_id)}"><span class="conversation-icon">${icon(job.provider==='sample'?'file':'mic')}</span><div class="history-title"><h3>${esc(job.title)}</h3><p>${providerName(job.provider)} <span>·</span> ${date(job.updated_at)}</p></div>${badge(job.status)}${icon('arrow')}</a>`).join(''):empty('A fresh page.','No conversations match this view.','<a href="/" class="text-link">Start a conversation '+icon('arrow')+'</a>');}

function renderSettings(checks) {
  const s=state.settings;
  $('#main').innerHTML=pageHeading('MAKE IT YOURS','Workspace settings.','Connect your provider once. Come back to the conversation.')+
    `<div class="settings-layout"><form id="settings-form" class="panel settings-card"><div class="section-heading"><div><h2>Analysis provider</h2><p class="muted">Choose how Althea processes your conversations.</p></div>${icon('settings')}</div>
    <label class="field-label" for="provider">Provider</label><select id="provider" class="input"><option value="gemini" ${s.provider==='gemini'?'selected':''}>Gemini API key</option><option value="vertex" ${s.provider==='vertex'?'selected':''}>Google Cloud / Vertex AI</option></select>
    <div id="gemini-settings"><label class="field-label" for="api-key">Gemini API key <span>${s.key_configured?'Key saved':''}</span></label><div class="key-input"><input id="api-key" class="input" type="password" autocomplete="new-password" placeholder="${s.key_configured?'A key is already configured. Enter a new key to replace it.':'Paste your Gemini API key'}"><button type="button" id="toggle-key" class="text-button">Show</button></div><p class="field-help">Your saved key stays on this device and is never included in analysis exports. <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Get a key ${icon('external')}</a></p></div>
    <div id="vertex-settings"><label class="field-label" for="project-id">Cloud project ID</label><input id="project-id" class="input" value="${esc(s.project_id)}" placeholder="your-project-id"><label class="field-label" for="location">Location</label><input id="location" class="input" value="${esc(s.location)}"><p class="field-help">Uses your existing Application Default Credentials and Cloud model access.</p></div>
    <hr><h3>Models</h3><p class="field-help">Gemini 3.5 Flash-Lite is the default for all Gemini stages.</p>${[['gemini_audio_model','Audio transcription'],['text_model','Claim analysis'],['grounding_model','Evidence search']].map(([key,label])=>`<label class="field-label" for="${key}">${label}</label><input id="${key}" class="input mono" value="${esc(s[key])}" required>`).join('')}
    <hr><label class="checkbox-label"><input id="persist-settings" type="checkbox" checked><span>Remember these settings<small>Save locally in .env so they survive restarts.</small></span></label><div class="settings-actions"><button type="submit" class="button primary">Save settings ${icon('check')}</button>${s.key_configured?'<button type="button" id="clear-key" class="text-button danger">Remove saved key</button>':''}</div></form>
    <aside><div class="panel status-card"><p class="eyebrow">ON THIS DEVICE</p><h3>Ready when you are.</h3><div class="check-list">${checks.filter(c=>['ffmpeg','ffprobe','Gemini API key','Google Cloud project','Local ADC configuration'].includes(c.name)).map(c=>`<div class="check-row"><span class="check-icon ${c.ok?'ok':''}">${c.ok?icon('check'):icon('x')}</span><div><strong>${esc(c.name)}</strong><small>${c.ok?'Configured locally':'Needs setup'}</small></div></div>`).join('')}</div><p class="field-help">These are local setup checks. Saving settings makes no provider request.</p></div><div class="settings-note"><h3>A note on evidence</h3><p>Audio and text can use the Gemini free tier, subject to your quotas. Search grounding with 3.5 Flash-Lite requires paid-tier access.</p><p>Review source dates and the original recording before relying on a result.</p></div></aside></div>`;
  const toggle=()=>{$('#gemini-settings').hidden=$('#provider').value!=='gemini';$('#vertex-settings').hidden=$('#provider').value!=='vertex';};$('#provider').onchange=toggle;toggle();
  $('#toggle-key').onclick=()=>{const field=$('#api-key');field.type=field.type==='password'?'text':'password';$('#toggle-key').textContent=field.type==='password'?'Show':'Hide';};
  $('#settings-form').onsubmit=async event=>{event.preventDefault();await saveSettings(false);};
  if($('#clear-key'))$('#clear-key').onclick=()=>saveSettings(true);
}
async function saveSettings(clear) {
  const button=$('#settings-form button[type="submit"]');button.disabled=true;
  const body={provider:$('#provider').value,project_id:$('#project-id').value.trim(),location:$('#location').value.trim(),api_key:clear?'':$('#api-key').value.trim(),clear_key:clear,persist:$('#persist-settings').checked};
  ['gemini_audio_model','text_model','grounding_model'].forEach(key=>{body[key]=$('#'+key).value.trim();});
  try {const result=await api('/api/settings',{method:'POST',body});state.settings=result.settings;$('#api-key').value='';toast(result.message);await route();}catch(error){toast(error.message,true);button.disabled=false;}
}

function renderJob() {
  const s=state.snapshot,t=s.transcript,a=s.analysis,v=s.verification,provider=state.jobProvider;
  const conflicts=(a?.pairs||[]).filter(p=>['direct_conflict','numeric_discrepancy','insufficient_context'].includes(p.relation));
  const base=apiJob(provider,s.job_id);
  $('#main').innerHTML=`<div class="breadcrumb"><a href="/history">${icon('back')} All conversations</a><span>${providerName(provider)}</span></div><section class="result-heading"><div><div class="result-meta">${badge(s.status)}<span>${date(s.updated_at)}</span></div><h1>${esc(s.title)}</h1></div><div class="export-actions"><a class="button secondary small" href="${base}/export/json" download>${icon('download')} JSON</a><a class="button secondary small" href="${base}/export/csv" download>Claims CSV</a></div></section>
    ${s.mode==='fixture'?notice('Sample conversation · This transcript and its evidence are fictional. No recording or live search was used.','warm'):''}${s.issues.map(i=>notice(i.message,'error')).join('')}
    <div class="stats-strip"><div><strong>${t?.speakers.length||0}</strong><span>Speakers</span></div><div><strong>${a?.claims.length||0}</strong><span>Factual claims</span></div><div><strong>${conflicts.length}</strong><span>Potential disagreements</span></div><div><strong>${v?.results.length||0}</strong><span>Evidence checks</span></div></div>
    <div class="result-tabs" role="tablist" aria-label="Analysis views">${[['transcript','Transcript'],['claims','Claims'],['compare','Disagreements'],['evidence','Evidence']].map(([key,label])=>`<button role="tab" data-tab="${key}" aria-selected="${state.tab===key}">${label}${key==='claims'?` <span>${a?.claims.length||0}</span>`:''}</button>`).join('')}</div><section id="result-content"></section>
    <details class="usage-details"><summary>Usage and saved versions</summary><p>${state.usage.attempts_used} / ${state.usage.attempt_limit} provider attempts · ${state.usage.verification_pairs_used} / ${state.usage.pair_limit} distinct evidence pairs</p>${state.usage.cache_hits.length?`<p>Reused saved results: ${esc(state.usage.cache_hits.join(', '))}</p>`:''}<div class="version-links">${state.versions.map(version=>`<a href="${base}/versions/${encodeURIComponent(version.artifact_id)}" download>${esc(version.kind)} · ${date(version.created_at)} ${icon('download')}</a>`).join('')}</div></details>`;
  $$('[data-tab]').forEach(button=>button.onclick=()=>{rememberTab(button.dataset.tab);$$('[data-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===button)));renderJobContent();});renderJobContent();
}
function renderJobContent() {
  const s=state.snapshot,t=s.transcript,a=s.analysis,v=s.verification,base=apiJob(state.jobProvider,s.job_id);
  const speakers=Object.fromEntries((t?.speakers||[]).map(sp=>[sp.speaker_id,sp.display_name]));
  const segments=Object.fromEntries((t?.segments||[]).map(seg=>[seg.segment_id,seg]));
  const claims=Object.fromEntries((a?.claims||[]).map(c=>[c.claim_id,c]));
  const content=$('#result-content');
  if(state.tab==='transcript') {
    if(!t){content.innerHTML=empty('No transcript saved yet.','The transcription could not finish. Review the issue above and start a new analysis.','<a href="/" class="button primary">Back to workspace</a>');return;}
    content.innerHTML=`<div class="transcript-layout"><div class="panel transcript-panel"><div class="section-heading"><h2>The conversation</h2><button class="text-button" id="edit-transcript">Review & edit</button></div>${t.source.audio_relpath?`<audio id="job-audio" controls preload="metadata" src="${base}/audio"></audio>`:'<p class="field-help">No audio attached to this transcript.</p>'}<div class="transcript-turns">${t.segments.map(seg=>`<article class="transcript-turn"><button class="time-button" data-seek="${seg.start_s}" aria-label="Play from ${time(seg.start_s)}">${time(seg.start_s)} ${icon('play')}</button><div><h3><span class="speaker-dot ${seg.speaker_id==='speaker_02'?'second':''}"></span>${esc(speakers[seg.speaker_id])}</h3><p>${esc(seg.text)}</p></div></article>`).join('')}</div></div><aside class="transcript-aside"><p class="eyebrow">IN THE ROOM</p>${t.speakers.map((sp,i)=>`<div class="speaker-name"><span class="avatar ${i%2?'second':''}">${i+1}</span><div><strong>${esc(sp.display_name)}</strong><small>${t.segments.filter(seg=>seg.speaker_id===sp.speaker_id).length} turns</small></div></div>`).join('')}<hr><div class="detail-line"><span>Duration</span><strong>${time(t.duration_s)}</strong></div><div class="detail-line"><span>Language</span><strong>English</strong></div><p class="field-help">${t.origin==='human_reviewed'?'Transcript reviewed by a person.':'Review names, numbers and speaker attribution against the recording.'}</p>${t.issues.map(issue=>notice(issue.message)).join('')}<button id="reanalyze" class="button primary full">${a?'Reanalyze transcript':'Analyze this transcript'} ${icon('arrow')}</button><p class="field-help">Uses the saved transcript. May use your provider quota.</p></aside></div>`;
    $$('[data-seek]').forEach(button=>button.onclick=()=>{const audio=$('#job-audio');if(audio){audio.currentTime=Number(button.dataset.seek);audio.play().catch(()=>toast('Use the audio player to start playback.'));}});
    $('#edit-transcript').onclick=()=>editTranscript();if($('#reanalyze'))$('#reanalyze').onclick=()=>jobAction('reanalyze');
  } else if(state.tab==='claims') {
    if(!a?.claims.length){content.innerHTML=empty('No factual claims to show.','Review the transcript or analyze it to build a claim ledger.');return;}
    content.innerHTML=`<div class="section-heading claim-heading"><div><h2>What was said.</h2><p class="muted">Every claim links back to the speaker’s exact words.</p></div><select id="claim-speaker" class="input compact" aria-label="Filter claims by speaker"><option value="all">All speakers</option>${t.speakers.map(sp=>`<option value="${sp.speaker_id}">${esc(sp.display_name)}</option>`).join('')}</select></div><div id="claim-list">${a.claims.map(c=>`<article class="panel claim-card" data-claim-speaker="${c.speaker_id}"><div class="claim-label"><span class="speaker-dot ${c.speaker_id==='speaker_02'?'second':''}"></span>${esc(speakers[c.speaker_id])}<span>·</span><span>${time(segments[c.source_spans[0].segment_id].start_s)}</span><span class="claim-checkability">${esc(c.checkability.replaceAll('_',' '))}</span></div><h3>${esc(c.proposition)}</h3><details><summary>Exact quote & scope</summary>${c.source_spans.map(span=>`<blockquote>${esc(span.quote)}</blockquote>`).join('')}<dl class="scope-grid">${[['Subject',c.subject],['Metric',c.metric],['Period',c.period],['Geography',c.geography],['Population',c.population],['Basis',c.measurement_basis],['Quantity',c.quantity?.raw_text],['Qualifiers',c.qualifiers.join('; ')]].map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value||'Not specified')}</dd></div>`).join('')}</dl>${c.missing_context.length?notice('Missing context: '+c.missing_context.join(', '),'warm'):''}</details></article>`).join('')}</div>`;
    $('#claim-speaker').onchange=e=>$$('[data-claim-speaker]').forEach(card=>{card.hidden=e.target.value!=='all'&&card.dataset.claimSpeaker!==e.target.value;});
  } else if(state.tab==='compare') {
    const pairs=(a?.pairs||[]).filter(p=>['direct_conflict','numeric_discrepancy','insufficient_context'].includes(p.relation)).sort((x,y)=>x.priority-y.priority);
    content.innerHTML=`<div class="section-heading"><div><h2>Where the stories differ.</h2><p class="muted">Potential conflicts and context-needed comparisons. Neither is a fact-check verdict.</p></div></div>${pairs.length?`<div class="comparison-list">${pairs.slice(0,8).map(p=>`<article class="panel comparison-card"><div class="section-heading"><span class="comparison-type">${esc(p.relation==='insufficient_context'?'Needs context':p.relation.replaceAll('_',' '))}</span><label class="checkbox-label"><input type="checkbox" data-pair="${p.pair_id}" ${state.selected.has(p.pair_id)?'checked':''}> Select</label></div><div class="comparison-quotes">${[p.claim_a_id,p.claim_b_id].map(id=>`<div><p class="claim-label">${esc(speakers[claims[id].speaker_id])}</p><blockquote>${claims[id].source_spans.map(span=>esc(span.quote)).join(' ')}</blockquote></div>`).join('')}</div><p>${esc(p.explanation)}</p>${p.numeric_difference!==null?`<p class="field-help">Absolute difference: ${esc(p.numeric_difference)} ${esc(p.numeric_difference_unit)}</p>`:''}<p class="field-help">${v?.results.some(r=>r.pair_id===p.pair_id)?'Evidence assessed':esc(v?.unverified.find(u=>u.pair_id===p.pair_id)?.reason.replaceAll('_',' ')||(p.relation==='insufficient_context'?'Needs context · Select to investigate sources':'Not checked against evidence'))}</p></article>`).join('')}</div><div class="comparison-actions"><p id="selection-count">${state.selected.size} selected · Choose up to four</p><button id="verify-pairs" class="button primary">Check evidence ${icon('arrow')}</button><button id="refresh-pairs" class="button secondary">Refresh selected</button></div>`:empty('No related comparisons found.','No related cross-speaker claims were shortlisted. This does not mean the claims are accurate or consistent.')}<details class="usage-details"><summary>All assessed comparisons (${a?.pairs.length||0})</summary>${(a?.pairs||[]).map(p=>`<p><strong>${esc(p.relation==='insufficient_context'?'Needs context':p.relation.replaceAll('_',' '))}</strong> — ${esc(p.explanation)}</p>`).join('')}</details>`;
    $$('[data-pair]').forEach(box=>box.onchange=()=>{if(box.checked)state.selected.add(box.dataset.pair);else state.selected.delete(box.dataset.pair);updatePairActions();});
    if($('#verify-pairs')){$('#verify-pairs').onclick=()=>jobAction('verify');$('#refresh-pairs').onclick=()=>jobAction('refresh');updatePairActions();}
  } else {
    content.innerHTML=`<div class="section-heading"><div><h2>A closer look at the evidence.</h2><p class="muted">Independent assessments, with sources you can inspect.</p><p class="field-help">Saved with this conversation. Opening History or reloading does not run another check.</p></div></div>${v?.results.length?v.results.map(result=>`<article class="panel evidence-card"><div class="evidence-verdicts">${result.verdicts.map(verdict=>`<div><span class="verdict verdict-${esc(verdict.status)}">${esc(verdict.status==='supported'?'Supported by retrieved evidence':verdict.status==='refuted'?'Refuted by retrieved evidence':verdict.status.replaceAll('_',' '))}</span><h3>${esc(claims[verdict.claim_id]?.proposition)}</h3><p>${esc(verdict.rationale)}</p></div>`).join('')}</div><p>${esc(result.summary)}</p>${v.evidence.filter(e=>e.pair_id===result.pair_id).map(e=>`<div class="evidence-source"><p class="tiny-label">${s.mode==='fixture'?'SYNTHETIC DEMO EVIDENCE':esc(e.content_origin.replaceAll('_',' ').toUpperCase())}</p><a href="${safeUrl(e.url)}" target="_blank" rel="noreferrer">${esc(e.title)} ${icon('external')}</a>${e.content?`<p>${esc(e.content)}</p>`:''}<small>${esc(e.publisher||'Publisher not provided')} · Published ${esc(e.published_date||'unknown')} · Retrieved ${date(e.retrieved_at)}</small></div>`).join('')}${v.grounding_attributions.some(g=>g.pair_id===result.pair_id)?`<iframe title="Google Search attribution" class="search-attribution" sandbox="allow-popups allow-popups-to-escape-sandbox" src="${base}/attributions/${encodeURIComponent(result.pair_id)}"></iframe>`:''}</article>`).join(''):(v?.issues.length?empty('Evidence check unavailable.','The attempt is saved below. No source-backed verdict was produced.'):empty('No evidence checks yet.','Open Disagreements, select a comparison and choose Check evidence.'))} ${(v?.issues||[]).map(i=>notice(i.message,'warm')).join('')} ${v?.issues.some(i=>i.code==='RATE_LIMIT')?'<p class="field-help"><a href="https://ai.dev/rate-limit" target="_blank" rel="noreferrer">View Google API quotas</a> · <a href="/settings">Workspace settings</a></p>':''} ${(v?.unverified||[]).map(u=>`<p class="field-help">${esc(u.pair_id)} · ${esc(u.reason.replaceAll('_',' '))}</p>`).join('')}`;
  }
}
function updatePairActions(){const count=state.selected.size;$('#selection-count').textContent=`${count} selected · Choose up to four`;['#verify-pairs','#refresh-pairs'].forEach(id=>{$(id).disabled=count<1||count>4||!!state.active;});}
async function jobAction(action) {
  try{const result=await api(apiJob(state.jobProvider,state.snapshot.job_id)+'/actions',{method:'POST',body:{action,pair_ids:[...state.selected],verify:false}});state.operationOrigin=location.pathname;followOperation(result.operation_id);}catch(error){toast(error.message,true);}
}
function editTranscript() {
  const t=structuredClone(state.snapshot.transcript);const dialog=document.createElement('dialog');dialog.className='review-dialog';
  dialog.innerHTML=`<form id="review-form"><div class="section-heading"><h2>Review the conversation</h2><button type="button" id="close-review" class="icon-button" aria-label="Close transcript review">${icon('x')}</button></div>${notice('Saving a review clears active claims and evidence. Saved versions remain available; reanalyze to update the results.','warm')}<div class="review-speakers">${t.speakers.map((sp,i)=>`<label class="field-label">Speaker ${i+1}<input class="input" data-speaker-name="${sp.speaker_id}" value="${esc(sp.display_name)}" required maxlength="120"></label>`).join('')}</div>${t.segments.map(seg=>`<fieldset class="review-turn" data-segment="${seg.segment_id}"><legend>${time(seg.start_s)} – ${time(seg.end_s)}</legend><label class="field-label">Transcript<textarea class="input" data-edit="text" rows="4" required>${esc(seg.text)}</textarea></label><div class="review-timing"><label class="field-label">Speaker<select class="input" data-edit="speaker_id">${t.speakers.map(sp=>`<option value="${sp.speaker_id}" ${sp.speaker_id===seg.speaker_id?'selected':''}>${esc(sp.display_name)}</option>`).join('')}</select></label><label class="field-label">Start (seconds)<input class="input" data-edit="start_s" type="number" min="0" step="0.001" value="${seg.start_s}" required></label><label class="field-label">End (seconds)<input class="input" data-edit="end_s" type="number" min="0" step="0.001" value="${seg.end_s}" required></label></div></fieldset>`).join('')}<p id="review-error" class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" id="cancel-review" class="button secondary">Cancel</button><button type="submit" class="button primary">Save review ${icon('check')}</button></div></form>`;
  document.body.append(dialog);dialog.showModal();const close=()=>{dialog.close();dialog.remove();};$('#close-review',dialog).onclick=close;$('#cancel-review',dialog).onclick=close;dialog.addEventListener('close',()=>dialog.remove());
  $('#review-form',dialog).onsubmit=async event=>{event.preventDefault();const button=$('button[type="submit"]',dialog);button.disabled=true;$$('[data-speaker-name]',dialog).forEach(input=>{t.speakers.find(sp=>sp.speaker_id===input.dataset.speakerName).display_name=input.value;});$$('[data-segment]',dialog).forEach(fieldset=>{const seg=t.segments.find(seg=>seg.segment_id===fieldset.dataset.segment);$$('[data-edit]',fieldset).forEach(input=>{seg[input.dataset.edit]=input.type==='number'?Math.round(Number(input.value)*1000)/1000:input.value;});});try{await api(apiJob(state.jobProvider,state.snapshot.job_id)+'/review',{method:'POST',body:{transcript_id:state.snapshot.transcript.transcript_id,transcript:t}});close();await route();toast('Review saved. Reanalyze the transcript to update claims.');}catch(error){$('#review-error',dialog).textContent=error.message;button.disabled=false;}};
}

async function followOperation(id) {
  clearTimeout(pollTimer);
  try {
    const operation=await api('/api/operations/'+encodeURIComponent(id));
    const activity=$('#activity');activity.hidden=false;
    if(operation.status==='running') {state.active=operation;activity.innerHTML=`<span class="activity-spinner"></span><div><strong>Working on your conversation</strong><span>${esc(operation.message)}</span></div><a href="/history">You can keep navigating ${icon('arrow')}</a>`;renderInputIfHome();pollTimer=setTimeout(()=>followOperation(id),1300);}
    else {state.active=null;activity.hidden=true;renderInputIfHome();if(operation.job_id){toast(operation.message);const destination=jobUrl(operation.provider,operation.job_id);if(location.pathname===state.operationOrigin)navigate(destination);else{activity.hidden=false;activity.innerHTML=`${icon('check')}<div><strong>Your analysis is ready.</strong><span>Saved in your conversation history.</span></div><a href="${destination}">View analysis ${icon('arrow')}</a><button id="dismiss-activity" class="icon-button" aria-label="Dismiss completed analysis notice">${icon('x')}</button>`;$('#dismiss-activity').onclick=()=>{activity.hidden=true;};}}else toast(operation.message,true);}
  } catch(error){state.active=null;$('#activity').hidden=true;toast(error.message,true);}
}
function renderInputIfHome(){if(location.pathname==='/'&&$('#analyze'))$('#analyze').disabled=!state.file||!!recorder||!!state.active;}

async function startRecording() {
  if(recorder)return;
  const button=$('#record-toggle');if(button)button.disabled=true;
  let stream,context;
  try {
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('Microphone recording needs localhost or a secure browser connection.');
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true},video:false});
    context=new AudioContext({sampleRate:16000});await context.resume();
    await context.audioWorklet.addModule('/static/recorder.js');
    const node=new AudioWorkletNode(context,'althea-recorder');const source=context.createMediaStreamSource(stream);const mute=context.createGain();mute.gain.value=0;source.connect(node);node.connect(mute);mute.connect(context.destination);
    if(location.pathname!=='/'||state.method!=='record'){stream.getTracks().forEach(track=>track.stop());source.disconnect();node.disconnect();await context.close();return;}
    const capture={stream,context,node,source,mute,chunks:[],frames:0,seconds:0,started:Date.now(),timer:null};recorder=capture;
    node.port.onmessage=e=>{if(recorder!==capture)return;const remaining=300*context.sampleRate-capture.frames;const samples=e.data.subarray(0,remaining);capture.chunks.push(samples);capture.frames+=samples.length;if(capture.frames>=300*context.sampleRate)stopRecording();};
    capture.timer=setInterval(()=>{capture.seconds=Math.floor((Date.now()-capture.started)/1000);if($('#record-time'))$('#record-time').textContent=time(capture.seconds);if(capture.seconds>=300)stopRecording();},250);
    renderInput();
  } catch(error){stream?.getTracks().forEach(track=>track.stop());if(context)await context.close();recorder=null;toast(error.name==='NotAllowedError'?'Microphone permission was denied. Allow access in your browser or upload an audio file.':error.message,true);if(button)button.disabled=false;}
}
async function stopRecording() {
  if(!recorder)return;
  const capture=recorder;recorder=null;clearInterval(capture.timer);capture.stream.getTracks().forEach(track=>track.stop());capture.source.disconnect();capture.node.disconnect();await capture.context.close();
  const length=capture.chunks.reduce((n,chunk)=>n+chunk.length,0);
  if(!length){renderInput();return toast('No audio was captured. Try recording again.',true);}
  const buffer=new ArrayBuffer(44+length*2),view=new DataView(buffer);const write=(offset,text)=>[...text].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
  write(0,'RIFF');view.setUint32(4,36+length*2,true);write(8,'WAVE');write(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,capture.context.sampleRate,true);view.setUint32(28,capture.context.sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);write(36,'data');view.setUint32(40,length*2,true);let offset=44;capture.chunks.forEach(chunk=>chunk.forEach(value=>{const sample=Math.max(-1,Math.min(1,value));view.setInt16(offset,Math.round(sample*(sample<0?32768:32767)),true);offset+=2;}));
  setFile(new File([buffer],`recording-${new Date().toISOString().slice(0,16).replaceAll(':','-')}.wav`,{type:'audio/wav'}));toast('Recording ready. Listen back before analyzing.');
}

try {const data=await api('/api/bootstrap');state.csrf=data.csrf;state.settings=data.settings;await route();if(data.active)followOperation(data.active.id);}catch(error){$('#main').innerHTML=empty('Could not open your workspace.',esc(error.message),'<a href="/" class="button primary">Try again</a>');}
