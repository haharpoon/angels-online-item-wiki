/* Pet evolution viewer. Data: window.PET_DATA {forms, sheets, palettes}.
 * Sheets are 8-bit greyscale PNGs whose pixel value IS the palette index (0 = transparent);
 * colours are rebuilt from the sprite's palette, then passed through
 * applyColourShift(imageData, {base, mask}, {section, indices, palette}) for SP_ATTRIB_BIAS forms.
 * URL hash: #pet=<id>&angle=<0-7>&act=<Wait|Run|Att|Hurt|Dead>&stage=<0-4>&q=<text>&zoom=<fit|1|2|3>&page=<n> */
(function(){
'use strict';
const D=window.PET_DATA, F=D.forms;
const STAGES=['Egg','Basic','Mid','High','Top'];
const ACTS=['Wait','Run','Att','Hurt','Dead'];
const ACT_LABEL={Wait:'Wait',Run:'Run',Att:'Attack',Hurt:'Hurt',Dead:'Dead'};
// 8 view angles clockwise from back. Stored dirs: 0 back,1 back-left,2 left,3 front-left,4 front; right side mirrors 3/2/1.
const ANGLES=[['Back',0,false],['Back-left',1,false],['Left',2,false],['Front-left',3,false],['Front',4,false],['Front-right',3,true],['Right',2,true],['Back-right',1,true]];
const TICK=1000/60, PER_PAGE=60;
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const state={q:'',stage:-1,onlyEn:false,onlySpr:false,colour:true,page:0,cur:null,angle:4,act:'Wait',zoom:'fit',t0:performance.now()};
const isStub=()=>!window.applyColourShift||window.applyColourShift.isStub;
const shifting=()=>state.colour&&!isStub();
const hasSpr=f=>Object.keys(f.acts).length>0;
const stageName=s=>s>=0?STAGES[s]:'?';

/* ---------- sheets (lazy) ---------- */
const sheetCache=new Map();
function loadSheet(name){
  if(sheetCache.has(name)) return sheetCache.get(name);
  const p=new Promise((res,rej)=>{const im=new Image();im.decoding='async';im.onload=()=>{
      const c=document.createElement('canvas');c.width=im.width;c.height=im.height;
      const x=c.getContext('2d',{willReadFrequently:true});x.drawImage(im,0,0);
      const d=x.getImageData(0,0,c.width,c.height).data, idx=new Uint8Array(c.width*c.height);
      for(let i=0;i<idx.length;i++) idx[i]=d[i*4];
      res({w:c.width,h:c.height,idx});};im.onerror=()=>rej(new Error('sheet '+name));im.src='pets/sheets/'+name+'.png';});
  p.catch(()=>sheetCache.delete(name));
  sheetCache.set(name,p);return p;
}
const ready=new Map(); // img -> sheet once loaded (sync access for the render loop)
function want(name){ if(!ready.has(name)) loadSheet(name).then(s=>ready.set(name,s)).catch(()=>{}); return ready.get(name); }
const palCache=new Map();
function palette(i){ if(!palCache.has(i)) palCache.set(i,D.palettes[i].map(h=>[parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)])); return palCache.get(i); }
const frameCache=new Map();
function frameCanvas(form,act,fi,sheet){
  const a=form.acts[act], m=D.sheets[a.img].f[fi]; if(!m) return null;
  const doShift=shifting()&&form.biasFlag;
  const key=a.img+'|'+fi+'|'+a.pal+'|'+(doShift?(form.baseBias+'/'+form.maskBias):'raw');
  let r=frameCache.get(key); if(r) return r;
  const [x0,y0,w,h,ax,ay]=m, pal=palette(a.pal);
  let img=new ImageData(w,h); const idx=new Uint8Array(w*h);
  for(let y=0;y<h;y++){const row=(y0+y)*sheet.w+x0; for(let x=0;x<w;x++){
    const v=sheet.idx[row+x]; idx[y*w+x]=v; if(!v) continue;
    const o=(y*w+x)*4, c=pal[v]; img.data[o]=c[0];img.data[o+1]=c[1];img.data[o+2]=c[2];img.data[o+3]=255; }}
  if(doShift){ try{ img=window.applyColourShift(img,{base:form.baseBias||null,mask:form.maskBias||null},{section:'pet',indices:idx,palette:D.palettes[a.pal]})||img; }catch(e){ console.warn('applyColourShift failed',e); } }
  const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').putImageData(img,0,0);
  r={c,ax,ay};
  if(frameCache.size>4000) frameCache.clear();
  frameCache.set(key,r);return r;
}
function frameIndex(form,act,angle,t){
  const a=form.acts[act], seq=a.seq.length?a.seq:[0];
  const step=Math.floor(t/(Math.max(1,a.delay)*TICK*2))%seq.length;
  return seq[step]*5+ANGLES[angle][1];
}
function draw(ctx,form,act,angle,t,cx,cy,scale,sheet){
  let fr=frameCanvas(form,act,frameIndex(form,act,angle,t),sheet)||frameCanvas(form,act,ANGLES[angle][1],sheet);
  if(!fr) return;
  ctx.save();ctx.imageSmoothingEnabled=false;ctx.translate(Math.round(cx),Math.round(cy));ctx.scale(ANGLES[angle][2]?-scale:scale,scale);
  ctx.drawImage(fr.c,-fr.ax,-fr.ay);ctx.restore();
}
const bestAct=f=>f.acts.Wait?'Wait':Object.keys(f.acts)[0];
const boxCache=new Map();
function actBox(form,act){ const k=form.acts[act].img; if(boxCache.has(k)) return boxCache.get(k);
  let l=1e9,t=1e9,r=-1e9,b=-1e9;
  for(const m of D.sheets[k].f){ if(!m) continue; const [,,w,h,ax,ay]=m; l=Math.min(l,-ax,ax-w); r=Math.max(r,w-ax,ax); t=Math.min(t,-ay); b=Math.max(b,h-ay); }
  const o={l,t,r,b,w:r-l,h:b-t}; boxCache.set(k,o); return o; }
// integer scale for crisp pixels; small sprites get scaled up, big ones fit
function fitScale(box,W,H,max){ const s=Math.min((W-16)/box.w,(H-16)/box.h); return s>=1?Math.min(max,Math.floor(s)):Math.max(.25,Math.floor(s*4)/4); }

/* ---------- list ---------- */
const ALL=Object.values(F).sort((a,b)=>a.id-b.id);
function base(){ const q=state.q.trim().toLowerCase();
  return ALL.filter(f=>(!state.onlyEn||!f.nonEn)&&(!state.onlySpr||hasSpr(f))&&(!q||f.name.toLowerCase().includes(q)||String(f.id).startsWith(q))); }
function filtered(){ return base().filter(f=>state.stage<0||f.stage===state.stage); }
function renderMenu(){
  const b=base(), n=[0,0,0,0,0]; b.forEach(f=>{if(f.stage>=0)n[f.stage]++;});
  const M=$('menu'); M.innerHTML='<div class="h">Stage</div>';
  [['All stages',-1,b.length],...STAGES.map((s,i)=>[s+(i===4?' · Fusion':''),i,n[i]])].forEach(([l,v,c])=>{
    const x=document.createElement('button');x.type='button';x.innerHTML=`<span>${l}</span><span class="n">${c}</span>`;
    x.setAttribute('aria-pressed',state.stage===v);x.onclick=()=>{state.stage=v;state.page=0;renderList();syncHash();};M.appendChild(x);});
}
const io=new IntersectionObserver(es=>{for(const e of es) if(e.isIntersecting){io.unobserve(e.target);paintThumb(e.target);}},{rootMargin:'300px'});
function paintThumb(cv){
  const f=F[cv.dataset.id], act=bestAct(f); if(!act) return;
  loadSheet(f.acts[act].img).then(sh=>{
    cv.parentNode.classList.remove('loading');
    const ctx=cv.getContext('2d');ctx.clearRect(0,0,cv.width,cv.height);
    const m=D.sheets[f.acts[act].img].f[4]; // front-facing first frame: fit to what is drawn
    const bx=m?{l:-m[4],r:m[2]-m[4],t:-m[5],b:m[3]-m[5],w:m[2],h:m[3]}:actBox(f,act), s=fitScale(bx,cv.width,cv.height,3);
    draw(ctx,f,act,4,0,cv.width/2-(bx.l+bx.r)/2*s,cv.height/2-(bx.t+bx.b)/2*s,s,sh);
  }).catch(()=>{cv.parentNode.className='frame none';cv.parentNode.textContent='load failed';});
}
function card(f){
  const d=document.createElement('div');d.className='card'+(state.cur===f?' on':'');d.dataset.id=f.id;d.tabIndex=0;d.setAttribute('role','button');
  const spr=hasSpr(f);
  d.innerHTML=`<span class="badge s${f.stage}">${stageName(f.stage)}</span>${f.nonEn?'<span class="badge r" title="No English name in the client data">non-EN</span>':''}${f.stage===4?'<span class="badge fu" title="Top forms come from Pet Fusion">Fusion</span>':''}
    ${spr?`<div class="frame loading"><canvas width="84" height="84" data-id="${f.id}"></canvas></div>`:'<div class="frame none">no sprite<br>in client</div>'}<div class="nm"></div><div class="id">#${f.id}</div>`;
  d.querySelector('.nm').textContent=f.name; d.title=f.name+' #'+f.id;
  if(spr) io.observe(d.querySelector('canvas'));
  d.onclick=()=>select(f.id); d.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(f.id);}};
  return d;
}
let LIST=[];
function renderList(){
  renderMenu();
  LIST=filtered(); const pages=Math.max(1,Math.ceil(LIST.length/PER_PAGE));
  state.page=Math.max(0,Math.min(state.page,pages-1));
  $('count').textContent=LIST.length+' form'+(LIST.length===1?'':'s')+(state.stage>=0?' · '+STAGES[state.stage]:'');
  $('page').textContent=(state.page+1)+' / '+pages;
  $('prev').disabled=state.page===0;$('next').disabled=state.page>=pages-1;
  const g=$('grid');g.innerHTML='';
  if(!LIST.length){g.innerHTML='<div class="empty">No pets match. Clear the search or pick another stage.</div>';return;}
  const frag=document.createDocumentFragment();
  LIST.slice(state.page*PER_PAGE,(state.page+1)*PER_PAGE).forEach(f=>frag.appendChild(card(f)));
  g.appendChild(frag);
}

/* ---------- evolution mini-tree ---------- */
function rootsOf(id){ const seen=new Set(),out=new Set(),st=[id]; while(st.length){const x=st.pop();if(seen.has(x))continue;seen.add(x);const p=F[x].prev;if(!p.length)out.add(x);else st.push(...p);} return [...out]; }
function lineage(id){ // ancestors + descendants of the current form
  const s=new Set([id]); let st=[id]; while(st.length){const x=st.pop(); for(const p of F[x].prev) if(!s.has(p)){s.add(p);st.push(p);}}
  st=[id]; while(st.length){const x=st.pop(); for(const n of F[x].next) if(!s.has(n)){s.add(n);st.push(n);}} return s; }
function renderTree(f){
  const T=$('tree'); T.innerHTML='';
  const roots=rootsOf(String(f.id)); const all=new Set(), st=[...roots];
  while(st.length){const x=st.pop(); if(all.has(x)) continue; all.add(x); st.push(...F[x].next);}
  const path=lineage(String(f.id)), cols=[[],[],[],[],[]];
  [...all].sort((a,b)=>+a-+b).forEach(x=>{const s=F[x].stage; if(s>=0) cols[s].push(x);});
  cols.forEach((c,i)=>{ if(!c.length) return; const col=document.createElement('div');col.className='col';col.innerHTML=`<div class="h">${STAGES[i]}</div>`;
    c.forEach(x=>{const b=document.createElement('button');b.type='button';b.className='chip'+(x==f.id?' on':path.has(x)?' path':' dim');b.textContent=F[x].name;b.title=`#${x} ${F[x].name}`;b.onclick=()=>select(x);col.appendChild(b);});
    T.appendChild(col); });
}

/* ---------- viewer ---------- */
function btn(label,fn,title){const b=document.createElement('button');b.type='button';b.innerHTML=label;if(title)b.title=title;b.onclick=fn;return b;}
function select(id,opts={}){
  const f=F[id]; if(!f) return; state.cur=f;
  if(!f.acts[state.act]) state.act=bestAct(f)||'Wait';
  if(!opts.keepTime) state.t0=performance.now();
  document.querySelectorAll('.card').forEach(c=>c.classList.toggle('on',c.dataset.id==id));
  $('vName').textContent=f.name;
  $('vMeta').innerHTML=`#${f.id} · <b>${stageName(f.stage)}</b> stage · ${esc(f.typeEn||f.type||'')} · ${esc(f.familyEn||f.family||'')}${f.exp?' · EXP table '+esc(f.exp.replace('升級表','')):''}`;
  // intentional states
  let co='';
  if(f.stage===4){ co=`<div class="callout"><b>Fusion Pet · Top stage.</b> Top forms are not reached by levelling up. They are born from Pet Fusion: Main pet + Assistant pet + Fusion Potion.`+
      (f.fusionItem?` Source item: <a href="items.html" title="${esc(f.fusionItem.desc)}">${esc(f.fusionItem.name)} #${f.fusionItem.id}</a>.`:' No matching Fusion Pet item was found in the catalog.')+`</div>`; }
  if(!hasSpr(f)) co+=`<div class="callout miss"><b>No sprite in the client data.</b> Sequence ${f.seq} (<code>${esc(f.dir||'')}</code>) is listed in NPC.OBD, but none of its .spr files are in any Global or legacy pak.</div>`;
  $('callout').innerHTML=co;
  const warns=[]; if(f.nonEn) warns.push('Name is not English in the client data (shown as-is).');
  if(hasSpr(f)){ const miss=ACTS.filter(a=>!f.acts[a]); if(miss.length) warns.push('Missing animations: '+miss.map(a=>ACT_LABEL[a]).join(', ')+'.'); }
  if(hasSpr(f)&&f.biasFlag&&!shifting()) warns.push(state.colour?'Colour formula not loaded yet: showing raw sprite colours.':'Raw sprite colours (game colours off).');
  $('vWarn').textContent=warns.join(' ');
  renderActs(); renderZoom();
  for(const id of ['strip','zoom','save','rotL','rotR']) $(id).closest('.row,.rot,.strip').style.display=hasSpr(f)?'':'none';
  // branch choice
  const B=$('branch');B.innerHTML='';
  f.prev.forEach(p=>B.appendChild(btn(`◀ ${esc(F[p].name)}<small>back to ${stageName(F[p].stage)} · #${p}</small>`,()=>select(p))));
  f.next.forEach((n,i)=>B.appendChild(btn(`${f.next.length>1?'Branch '+(i+1)+': ':''}${esc(F[n].name)} ▶<small>evolves to ${stageName(F[n].stage)} · #${n}</small>`,()=>select(n))));
  if(!f.prev.length&&!f.next.length) B.innerHTML='<div class="meta" style="grid-column:1/-1">Standalone form: no evolution links.</div>';
  else if(!f.next.length&&f.stage!==4) B.appendChild(Object.assign(document.createElement('div'),{className:'meta',textContent:'Final 升階 form. Top forms come from Fusion.'}));
  renderTree(f);
  const s=f.stats; $('stats').innerHTML=(s?`<table><tr><th>${esc(f.typeEn||f.type)}</th><th>Lv 1</th><th>Lv ${s.lvMax}</th></tr>`+s.rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('')+'</table>':'<div class="meta">No PETATTRIB table for this pet type.</div>')+
    `<table><tr><td>Move speed</td><td>${f.move||'-'}</td></tr><tr><td>Attack speed</td><td>${f.atkSpd||'-'}</td></tr><tr><td>Attack range</td><td>${f.range||'-'}</td></tr><tr><td>Crit chance</td><td>${f.crit||'-'}%</td></tr></table>`;
  $('sprite').innerHTML=`Sequence <code>${f.seq}</code> · ${esc(f.obdName||'')}<br>Directory <code>${esc(f.dir||'')}</code><br>`+
    Object.entries(f.acts).map(([a,v])=>`${ACT_LABEL[a]}: <code>${esc(v.file)}</code>`).join('<br>')+
    `<br>BaseBias <code>${esc(f.baseBias||'—')}</code><br>MaskBias <code>${esc(f.maskBias||'—')}</code><br>SP_ATTRIB_BIAS: ${f.biasFlag?'yes':'no'}`;
  // lazy: current animation now, the others when idle
  if(hasSpr(f)){ $('vStatus').textContent='Loading sprites…'; want(f.acts[state.act].img);
    (window.requestIdleCallback||setTimeout)(()=>Object.values(f.acts).forEach(a=>want(a.img))); }
  else $('vStatus').textContent='';
  syncHash();
}
function renderActs(){ const f=state.cur, A=$('acts'); A.innerHTML='<span class="lbl">Anim</span>';
  ACTS.forEach((a,i)=>{const b=btn(ACT_LABEL[a],()=>setAct(a),`${ACT_LABEL[a]} (key ${i+1})`);b.disabled=!f||!f.acts[a];b.setAttribute('aria-pressed',a===state.act&&!b.disabled);A.appendChild(b);}); }
function setAct(a){ const f=state.cur; if(!f||!f.acts[a]) return; state.act=a; state.t0=performance.now(); want(f.acts[a].img); renderActs(); syncHash(); }
function renderZoom(){ const Z=$('zoom'); Z.innerHTML=''; [['fit','Fit'],['1','1×'],['2','2×'],['3','3×']].forEach(([v,l])=>{const b=btn(l,()=>{state.zoom=v;renderZoom();syncHash();});b.setAttribute('aria-pressed',state.zoom===v);Z.appendChild(b);}); }
function rotate(d){ state.angle=(state.angle+d+8)%8; syncHash(); }
function stepPet(d){ if(!LIST.length) return; let i=LIST.indexOf(state.cur); i=i<0?0:(i+d+LIST.length)%LIST.length;
  const p=Math.floor(i/PER_PAGE); if(p!==state.page){state.page=p;renderList();} select(String(LIST[i].id)); }
function buildStrip(){ const S=$('strip');S.innerHTML='';
  ANGLES.forEach((a,i)=>{const c=document.createElement('canvas');c.width=64;c.height=64;c.title=a[0];c.onclick=()=>{state.angle=i;syncHash();};S.appendChild(c);}); }

/* ---------- render loop ---------- */
function paintStage(now){
  const f=state.cur, cv=$('stage'), ctx=cv.getContext('2d');
  // keep backing store matched to CSS size for crisp pixels
  const W=Math.round(cv.clientWidth), H=Math.round(cv.clientHeight); if(W&&(cv.width!==W||cv.height!==H)){cv.width=W;cv.height=H;}
  ctx.clearRect(0,0,cv.width,cv.height);
  $('angleLbl').textContent=ANGLES[state.angle][0];
  const strip=[...$('strip').children];
  if(!f||!hasSpr(f)){ ctx.fillStyle='#a49cc0';ctx.font='14px system-ui';ctx.textAlign='center';
    ctx.fillText(f?'No sprite in the client data':'Pick a pet',cv.width/2,cv.height/2);
    strip.forEach(c=>c.getContext('2d').clearRect(0,0,64,64)); return; }
  const a=f.acts[state.act]?state.act:bestAct(f), sh=want(f.acts[a].img);
  if(!sh){ ctx.fillStyle='#a49cc0';ctx.font='13px system-ui';ctx.textAlign='center';ctx.fillText('Loading sprites…',cv.width/2,cv.height/2); return; }
  if($('vStatus').textContent) $('vStatus').textContent='';
  const t=(now-state.t0), bx=actBox(f,a);
  const s=state.zoom==='fit'?fitScale(bx,cv.width,cv.height,3):+state.zoom;
  const cx=cv.width/2-(bx.l+bx.r)/2*s, cy=cv.height/2-(bx.t+bx.b)/2*s;
  ctx.fillStyle='rgba(0,0,0,.35)';ctx.beginPath();ctx.ellipse(cx,cy,Math.min(60,bx.w*.3)*s,Math.min(18,bx.w*.09)*s,0,0,7);ctx.fill();
  draw(ctx,f,a,state.angle,t,cx,cy,s,sh);
  const s2=fitScale(bx,64,64,2);
  strip.forEach((c,i)=>{c.classList.toggle('on',i===state.angle);const x=c.getContext('2d');x.clearRect(0,0,64,64);
    draw(x,f,a,i,t,32-(bx.l+bx.r)/2*s2,32-(bx.t+bx.b)/2*s2,s2,sh);});
}
function tick(now){ if(!document.hidden){ try{ paintStage(window.matchMedia('(prefers-reduced-motion: reduce)').matches?state.t0:now); }catch(e){ console.error(e); } } requestAnimationFrame(tick); }

/* ---------- URL hash ---------- */
let applying=false;
function syncHash(){ if(applying) return; const p=new URLSearchParams();
  if(state.cur) p.set('pet',state.cur.id); if(state.angle!==4) p.set('angle',state.angle); if(state.act!=='Wait') p.set('act',state.act);
  if(state.stage>=0) p.set('stage',state.stage); if(state.q) p.set('q',state.q); if(state.zoom!=='fit') p.set('zoom',state.zoom); if(state.page) p.set('page',state.page);
  if(state.onlyEn) p.set('en',1); if(state.onlySpr) p.set('spr',1); if(!state.colour) p.set('raw',1);
  const h='#'+p.toString(); if(location.hash!==h) history.replaceState(null,'',h); }
function readHash(){ const raw=location.hash.slice(1); const p=new URLSearchParams(/^\d+$/.test(raw)?'pet='+raw:raw);
  applying=true;
  state.angle=Math.max(0,Math.min(7,+(p.get('angle')??4)||0)); if(!p.has('angle')) state.angle=4;
  state.act=ACTS.includes(p.get('act'))?p.get('act'):'Wait';
  state.stage=p.has('stage')?Math.max(-1,Math.min(4,+p.get('stage'))):-1;
  state.q=p.get('q')||''; $('q').value=state.q;
  state.zoom=['fit','1','2','3'].includes(p.get('zoom'))?p.get('zoom'):'fit';
  state.page=+(p.get('page')||0)||0;
  state.onlyEn=p.has('en'); $('onlyEn').checked=state.onlyEn; state.onlySpr=p.has('spr'); $('onlySpr').checked=state.onlySpr;
  state.colour=!p.has('raw'); $('colour').checked=state.colour;
  renderList();
  const id=p.get('pet'); const def=ALL.find(f=>f.stage===0&&f.next.length===2&&hasSpr(f));
  select(F[id]?id:String(def.id),{});
  applying=false; syncHash(); }

/* ---------- controls ---------- */
$('rotL').onclick=()=>rotate(-1); $('rotR').onclick=()=>rotate(1);
let qT; $('q').oninput=e=>{clearTimeout(qT);qT=setTimeout(()=>{state.q=e.target.value;state.page=0;renderList();syncHash();},120);};
$('onlyEn').onchange=e=>{state.onlyEn=e.target.checked;state.page=0;renderList();syncHash();};
$('onlySpr').onchange=e=>{state.onlySpr=e.target.checked;state.page=0;renderList();syncHash();};
$('colour').onchange=e=>{state.colour=e.target.checked;frameCache.clear();renderList();if(state.cur)select(state.cur.id,{keepTime:true});noteColour();};
$('prev').onclick=()=>{state.page--;renderList();syncHash();window.scrollTo(0,0);};
$('next').onclick=()=>{state.page++;renderList();syncHash();window.scrollTo(0,0);};
$('save').onclick=()=>{ try{ const a=document.createElement('a'); a.download=`pet-${state.cur?state.cur.id:'none'}-${ANGLES[state.angle][0]}.png`; a.href=$('stage').toDataURL('image/png'); a.click(); }catch(e){ $('vStatus').textContent='Save PNG is blocked when the page is opened as a file.'; } };
$('share').onclick=()=>{ syncHash(); (navigator.clipboard?navigator.clipboard.writeText(location.href):Promise.reject()).then(()=>{$('vStatus').textContent='Link copied.';},()=>{$('vStatus').textContent=location.href;}); };
const cv=$('stage'); let drag=null;
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX};cv.setPointerCapture(e.pointerId);cv.style.cursor='grabbing';});
cv.addEventListener('pointermove',e=>{ if(!drag) return; const dx=e.clientX-drag.x; if(Math.abs(dx)>=28){ rotate(dx<0?1:-1); drag.x=e.clientX; } });
const end=e=>{ if(!drag) return; drag=null; cv.style.cursor=''; try{cv.releasePointerCapture(e.pointerId);}catch(_){} };
cv.addEventListener('pointerup',end); cv.addEventListener('pointercancel',end);
window.addEventListener('keydown',e=>{
  const t=e.target; if(t&&(t.tagName==='INPUT'||t.tagName==='TEXTAREA'||t.tagName==='SELECT'||t.isContentEditable)) return;
  if(e.ctrlKey||e.metaKey||e.altKey) return;
  if(e.key==='ArrowLeft'){e.preventDefault();rotate(-1);} else if(e.key==='ArrowRight'){e.preventDefault();rotate(1);}
  else if(/^[1-5]$/.test(e.key)) setAct(ACTS[+e.key-1]);
  else if(e.key==='['||e.key===',') stepPet(-1); else if(e.key===']'||e.key==='.') stepPet(1);
  else if(e.key==='/'){e.preventDefault();$('q').focus();}
});
window.addEventListener('hashchange',()=>{ const p=new URLSearchParams(location.hash.slice(1)); if(state.cur&&p.get('pet')==state.cur.id) return; readHash(); });
function noteColour(){ $('colourNote').textContent=isStub()?'Colour-shift formula pending: forms with BaseBias/MaskBias show raw sprite colours.':(state.colour?'':'Raw sprite colours.'); }
buildStrip(); noteColour(); readHash();
const boot=$('boot'); if(boot) boot.remove();
requestAnimationFrame(tick);
window.PetViewer={select,state,setAct,rotate};
})();
