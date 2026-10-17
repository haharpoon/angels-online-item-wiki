/* Pet evolution viewer. Data: window.PET_DATA {forms, sheets, palettes}.
 * Sheets are 8-bit grayscale PNGs whose pixel value IS the palette index (0 = transparent),
 * so colours are rebuilt here from the sprite's own palette and then passed through
 * applyColourShift(imageData, {base, mask}, {section, indices, palette}) for SP_ATTRIB_BIAS forms. */
(function(){
'use strict';
const D=window.PET_DATA, F=D.forms;
const STAGES=['Egg','Basic','Mid','High','Top'];
const ACT_LABEL={Wait:'Wait',Run:'Run',Att:'Attack',Hurt:'Hurt',Dead:'Dead'};
// 8 view angles, clockwise from back. Stored dirs: 0 back,1 back-left,2 left,3 front-left,4 front; right side mirrors 3/2/1.
const ANGLES=[['Back',0,false],['Back-left',1,false],['Left',2,false],['Front-left',3,false],['Front',4,false],['Front-right',3,true],['Right',2,true],['Back-right',1,true]];
const TICK=1000/60;
const PER_PAGE=120;
const $=id=>document.getElementById(id);
const state={q:'',stage:-1,onlyEn:false,colour:true,page:0,cur:null,angle:4,act:'Wait',t0:performance.now()};
const shifting=()=>state.colour && !(window.applyColourShift && window.applyColourShift.isStub);

/* ---------- sheet + frame cache ---------- */
const sheetCache=new Map();
function loadSheet(name){
  if(sheetCache.has(name)) return sheetCache.get(name);
  const p=new Promise((res,rej)=>{const im=new Image();im.onload=()=>{
      const c=document.createElement('canvas');c.width=im.width;c.height=im.height;
      const x=c.getContext('2d',{willReadFrequently:true});x.drawImage(im,0,0);
      const d=x.getImageData(0,0,c.width,c.height).data, idx=new Uint8Array(c.width*c.height);
      for(let i=0;i<idx.length;i++) idx[i]=d[i*4];
      res({w:c.width,h:c.height,idx});};im.onerror=rej;im.src='pets/sheets/'+name+'.png';});
  sheetCache.set(name,p);return p;
}
const palCache=new Map();
function palette(i){ if(!palCache.has(i)) palCache.set(i,D.palettes[i].map(h=>[parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)])); return palCache.get(i); }
const frameCache=new Map();
function frameCanvas(form,act,fi,sheet){
  const a=form.acts[act], m=D.sheets[a.img].f[fi]; if(!m) return null;
  const doShift=shifting() && form.biasFlag;
  const key=a.img+'|'+fi+'|'+a.pal+'|'+(doShift?(form.baseBias+'/'+form.maskBias):'raw');
  if(frameCache.has(key)) return frameCache.get(key);
  const [x0,y0,w,h,ax,ay]=m, pal=palette(a.pal);
  let img=new ImageData(w,h); const idx=new Uint8Array(w*h);
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    const v=sheet.idx[(y0+y)*sheet.w+x0+x]; idx[y*w+x]=v; if(!v) continue;
    const o=(y*w+x)*4, c=pal[v]; img.data[o]=c[0];img.data[o+1]=c[1];img.data[o+2]=c[2];img.data[o+3]=255;
  }
  if(doShift) img=window.applyColourShift(img,{base:form.baseBias||null,mask:form.maskBias||null},{section:'pet',indices:idx,palette:D.palettes[a.pal]})||img;
  const c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').putImageData(img,0,0);
  const r={c,ax,ay,w,h};frameCache.set(key,r);return r;
}
function frameIndex(form,act,angle,t){
  const a=form.acts[act]; const seq=a.seq.length?a.seq:[0];
  const step=Math.floor(t/(Math.max(1,a.delay)*TICK*2))%seq.length; // #delay ticks at 60Hz, game runs 2 ticks/frame
  return seq[step]*5+ANGLES[angle][1];
}
function draw(ctx,form,act,angle,t,cx,cy,scale,sheet){
  const fi=frameIndex(form,act,angle,t); let fr=frameCanvas(form,act,fi,sheet);
  if(!fr){ fr=frameCanvas(form,act,ANGLES[angle][1],sheet); if(!fr) return; }
  ctx.save();ctx.imageSmoothingEnabled=false;ctx.translate(cx,cy);ctx.scale(ANGLES[angle][2]?-scale:scale,scale);
  ctx.drawImage(fr.c,-fr.ax,-fr.ay);ctx.restore();
}
function bestAct(form){ return form.acts.Wait?'Wait':Object.keys(form.acts)[0]; }
// bounding box of a whole action across all frames (for fitting)
function actBox(form,act){ const fs=D.sheets[form.acts[act].img].f.filter(Boolean);
  let l=1e9,t=1e9,r=-1e9,b=-1e9; for(const [,,w,h,ax,ay] of fs){l=Math.min(l,-ax,ax-w);r=Math.max(r,w-ax,ax);t=Math.min(t,-ay);b=Math.max(b,h-ay);} return {l,t,r,b}; }

/* ---------- list ---------- */
const ALL=Object.values(F).sort((a,b)=>a.id-b.id);
function stageName(s){return s>=0?STAGES[s]:'?';}
function filtered(){
  const q=state.q.trim().toLowerCase();
  return ALL.filter(f=>(state.stage<0||f.stage===state.stage)&&(!state.onlyEn||!f.nonEn)&&
    (!q||f.name.toLowerCase().includes(q)||String(f.id)===q||String(f.id).startsWith(q)));
}
const io=new IntersectionObserver(es=>{for(const e of es) if(e.isIntersecting){io.unobserve(e.target);paintThumb(e.target);}},{rootMargin:'200px'});
function paintThumb(cv){
  const f=F[cv.dataset.id]; const act=bestAct(f); if(!act) return;
  loadSheet(f.acts[act].img).then(sh=>{
    const ctx=cv.getContext('2d');ctx.clearRect(0,0,cv.width,cv.height);
    const bx=actBox(f,act), w=bx.r-bx.l, h=bx.b-bx.t, s=Math.max(.25,Math.min(1,88/Math.max(w,h)));
    draw(ctx,f,act,4,0,cv.width/2-(bx.l+bx.r)/2*s,cv.height/2-(bx.t+bx.b)/2*s,s,sh);
  });
}
function renderList(){
  const list=filtered(), pages=Math.max(1,Math.ceil(list.length/PER_PAGE));
  state.page=Math.min(state.page,pages-1);
  $('count').textContent=list.length+' forms';
  $('page').textContent=(state.page+1)+' / '+pages;
  $('prev').disabled=state.page===0;$('next').disabled=state.page>=pages-1;
  const g=$('grid');g.innerHTML='';
  for(const f of list.slice(state.page*PER_PAGE,(state.page+1)*PER_PAGE)){
    const d=document.createElement('div');d.className='card'+(state.cur===f?' on':'');d.dataset.id=f.id;
    d.innerHTML=`<span class="stg s${f.stage}">${stageName(f.stage)}</span>${f.nonEn?'<span class="flag" title="No English name in the client data">non-EN</span>':''}
      <div class="frame"><canvas width="92" height="92" data-id="${f.id}"></canvas></div><div class="nm"></div><div class="id">#${f.id}</div>`;
    d.querySelector('.nm').textContent=f.name;
    const cv=d.querySelector('canvas'); if(Object.keys(f.acts).length) io.observe(cv); else d.querySelector('.frame').textContent='?';
    d.onclick=()=>select(f.id);g.appendChild(d);
  }
}

/* ---------- viewer ---------- */
function btn(label,fn,title){const b=document.createElement('button');b.type='button';b.textContent=label;if(title)b.title=title;b.onclick=fn;return b;}
function rootsOf(id){ const seen=new Set(),out=new Set(),st=[id]; while(st.length){const x=st.pop();if(seen.has(x))continue;seen.add(x);const p=F[x].prev;if(!p.length)out.add(x);else st.push(...p);} return [...out]; }
function treeHTML(id,cur,seen){
  const f=F[id]; if(!f) return '';
  const loop=seen.has(id); seen=new Set(seen).add(id);
  const kids=loop?'':f.next.map(n=>treeHTML(n,cur,seen)).join('');
  return `<li><a data-id="${id}" class="${id==cur?'on':''}">${esc(f.name)}</a> <span class="s">#${id} · ${stageName(f.stage)}</span>${kids?'<ul>'+kids+'</ul>':''}</li>`;
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function select(id,keepAngle){
  const f=F[id]; if(!f) return; state.cur=f;
  if(!f.acts[state.act]) state.act=bestAct(f)||'Wait';
  history.replaceState(null,'','#'+id);
  document.querySelectorAll('.card').forEach(c=>c.classList.toggle('on',c.dataset.id==id));
  $('vName').textContent=f.name;
  $('vMeta').innerHTML=`#${f.id} · <b>${stageName(f.stage)}</b> stage · ${esc(f.typeEn||f.type||'')} · ${esc(f.familyEn||f.family||'')}${f.exp?' · EXP table '+esc(f.exp.replace('升級表','')):''}`;
  const warns=[]; if(f.nonEn) warns.push('Name is not English in the client data (shown as-is).');
  if(!Object.keys(f.acts).length) warns.push('No sprite file found for this form in any pak.');
  else { const miss=Object.keys(ACT_LABEL).filter(a=>!f.acts[a]); if(miss.length) warns.push('Missing animations: '+miss.join(', ')); }
  if(f.biasFlag && !shifting()) warns.push(state.colour?'Colour formula not loaded yet: showing raw sprite colours.':'Raw sprite colours (game colour shift off).');
  $('vWarn').textContent=warns.join(' ');
  // acts
  const A=$('acts');A.innerHTML='';
  for(const a of Object.keys(ACT_LABEL)){const b=btn(ACT_LABEL[a],()=>{state.act=a;state.t0=performance.now();select(id,true);});b.disabled=!f.acts[a];b.setAttribute('aria-pressed',a===state.act);A.appendChild(b);}
  // evolution arrows
  const P=$('evoPrev'),N=$('evoNext');P.innerHTML='';N.innerHTML='';
  f.prev.forEach(p=>P.appendChild(btn('◀ '+F[p].name,()=>select(p),'Previous stage: #'+p+' '+stageName(F[p].stage))));
  if(!f.prev.length) P.appendChild(Object.assign(btn('◀',()=>{}),{disabled:true}));
  f.next.forEach((n,i)=>N.appendChild(btn((f.next.length>1?'Branch '+(i+1)+': ':'')+F[n].name+' ▶',()=>select(n),'Evolves to #'+n+' '+stageName(F[n].stage))));
  if(!f.next.length) N.appendChild(Object.assign(btn('▶',()=>{}),{disabled:true}));
  $('evoCur').innerHTML=`${stageName(f.stage)}<br>${f.next.length>1?'2 branches':f.next.length?'1 evolution':'final form'}`;
  let rt='';
  if(f.stage===4){ rt='<b>Top stage · Fusion Pet.</b> Top forms are not reached through 升階 evolution: they are born from Pet Fusion (Main pet + Assistant pet + Fusion Potion).';
    if(f.fusionItem) rt+=` Source item: <a href="items.html" title="${esc(f.fusionItem.desc)}" style="color:var(--gold-strong)">${esc(f.fusionItem.name)} #${f.fusionItem.id}</a>.`;
    else rt+=' No matching Fusion Pet item found in the catalog.'; }
  else if(f.route&&f.route.length>1) rt='Route: '+f.route.map(r=>`<a data-id="${r}" style="color:var(--gold-strong);cursor:pointer">${esc(F[r].name)}</a>`).join(' → ');
  $('route').innerHTML=rt;
  $('route').querySelectorAll('a').forEach(a=>a.onclick=()=>select(a.dataset.id));
  $('tree').innerHTML='<ul>'+rootsOf(String(id)).map(r=>treeHTML(r,id,new Set())).join('')+'</ul>';
  $('tree').querySelectorAll('a').forEach(a=>a.onclick=()=>select(a.dataset.id));
  // stats
  const s=f.stats; $('stats').innerHTML=(s?`<table><tr><th>${esc(f.typeEn||f.type)}</th><th>Lv 1</th><th>Lv ${s.lvMax}</th></tr>`+s.rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('')+'</table>':'<div class="meta">No PETATTRIB table for this pet type.</div>')+
    `<table><tr><td>Move speed</td><td>${f.move||'-'}</td></tr><tr><td>Attack speed</td><td>${f.atkSpd||'-'}</td></tr><tr><td>Attack range</td><td>${f.range||'-'}</td></tr><tr><td>Crit chance</td><td>${f.crit||'-'}%</td></tr></table>`;
  $('sprite').innerHTML=`Sequence <code>${f.seq}</code> · ${esc(f.obdName||'')}<br>Directory <code>${esc(f.dir||'')}</code><br>`+
    Object.entries(f.acts).map(([a,v])=>`${a}: <code>${esc(v.file)}</code>`).join('<br>')+
    `<br>BaseBias <code>${esc(f.baseBias||'—')}</code><br>MaskBias <code>${esc(f.maskBias||'—')}</code><br>Flag SP_ATTRIB_BIAS: ${f.biasFlag?'yes':'no'}`;
  buildStrip();
}
function buildStrip(){
  const S=$('strip');S.innerHTML='';
  ANGLES.forEach((a,i)=>{const c=document.createElement('canvas');c.width=72;c.height=72;c.title=a[0];c.onclick=()=>{state.angle=i;};S.appendChild(c);});
}
$('rotL').onclick=()=>{state.angle=(state.angle+7)%8;};
$('rotR').onclick=()=>{state.angle=(state.angle+1)%8;};
function tick(now){
  const f=state.cur;
  if(f && f.acts[state.act]){
    const a=state.act; $('angleLbl').textContent=ANGLES[state.angle][0];
    loadSheet(f.acts[a].img).then(sh=>{
      if(state.cur!==f||state.act!==a) return;
      const t=now-state.t0, cv=$('stage'), ctx=cv.getContext('2d'); ctx.clearRect(0,0,cv.width,cv.height);
      const bx=actBox(f,a), s=Math.max(.5,Math.min(3,Math.floor(Math.min((cv.width-20)/(bx.r-bx.l),(cv.height-20)/(bx.b-bx.t))*2)/2));
      const cx=cv.width/2-(bx.l+bx.r)/2*s, cy=cv.height/2-(bx.t+bx.b)/2*s;
      ctx.fillStyle='rgba(0,0,0,.35)';ctx.beginPath();ctx.ellipse(cx,cy,22*s,7*s,0,0,7);ctx.fill();
      draw(ctx,f,a,state.angle,t,cx,cy,s,sh);
      [...$('strip').children].forEach((c,i)=>{c.classList.toggle('on',i===state.angle);const x=c.getContext('2d');x.clearRect(0,0,72,72);
        const s2=Math.min(1,64/Math.max(bx.r-bx.l,bx.b-bx.t)); draw(x,f,a,i,t,36-(bx.l+bx.r)/2*s2,36-(bx.t+bx.b)/2*s2,s2,sh);});
    });
  } else if(f){ const cv=$('stage');cv.getContext('2d').clearRect(0,0,cv.width,cv.height); }
  requestAnimationFrame(tick);
}

/* ---------- controls ---------- */
const sg=$('stages');
[['All',-1],...STAGES.map((s,i)=>[s,i])].forEach(([l,v])=>{const b=btn(l,()=>{state.stage=v;state.page=0;sg.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',x===b));renderList();});b.setAttribute('aria-pressed',v===-1);sg.appendChild(b);});
$('q').oninput=e=>{state.q=e.target.value;state.page=0;renderList();};
$('onlyEn').onchange=e=>{state.onlyEn=e.target.checked;state.page=0;renderList();};
$('colour').onchange=e=>{state.colour=e.target.checked;frameCache.clear();renderList();if(state.cur)select(state.cur.id,true);noteColour();};
$('prev').onclick=()=>{state.page--;renderList();window.scrollTo(0,0);};
$('next').onclick=()=>{state.page++;renderList();window.scrollTo(0,0);};
function noteColour(){ $('colourNote').textContent=(window.applyColourShift&&window.applyColourShift.isStub)?'Colour-shift formula pending (pd/colour-shift.js is a stub): BaseBias/MaskBias forms show raw sprite colours.':(state.colour?'':'Raw sprite colours.'); }
noteColour(); renderList();
const start=location.hash.slice(1); select(F[start]?start:String(ALL.find(f=>f.stage===0&&f.next.length===2&&Object.keys(f.acts).length).id));
requestAnimationFrame(tick);
window.PetViewer={select,state};
})();
