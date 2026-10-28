/* OpenDesign landing interactions, converted to a mount/cleanup module.
 * Call initOdLanding() in a mount effect; call the returned destroy() on
 * unmount. Nav scroll, hamburger, and reveal-on-scroll live in React.
 * three.js comes from the npm dependency (was a CDN importmap).
 */
import * as THREE from 'three';

export function initOdLanding() {
  const __cleanups = [];
  let __dead = false;
  const __on = (target, evt, fn, opts) => {
    target.addEventListener(evt, fn, opts);
    __cleanups.push(() => target.removeEventListener(evt, fn, opts));
  };
  const __raf = (fn) => {
    if (__dead) return 0;
    return requestAnimationFrame((t) => {
      if (__dead) return;
      fn(t);
    });
  };
  const __iv = (...args) => {
    const id = setInterval(...args);
    __cleanups.push(() => clearInterval(id));
    return id;
  };
  const __to = (...args) => {
    const id = setTimeout(...args);
    __cleanups.push(() => clearTimeout(id));
    return id;
  };
  const __RealIO = window.IntersectionObserver;
  const __trackedIO = [];
  window.IntersectionObserver = function (cb, opts) {
    const ob = new __RealIO(cb, opts);
    __trackedIO.push(ob);
    return ob;
  };
  window.IntersectionObserver.prototype = __RealIO.prototype;


/* ---------- hero wave canvas + interactive demo ---------- */
/* ═══════════════════════════════════════════════════
   Hero Waveform Canvas — multi-layered speech visualization
   ═══════════════════════════════════════════════════ */
(function(){
  const cv=document.getElementById('waveCanvas');
  const ctx=cv.getContext('2d');
  let w,h;
  function resize(){w=cv.width=cv.clientWidth;h=cv.height=cv.clientHeight}
  resize();__on(window, 'resize',resize);

  /* Speech wave functions — each layer has its own character */
  const layers=[
    {freq:.018,speed:.003,amp:14,color:'163,154,142',alpha:.7,lw:1.8,offset:0},      /* stone — primary human voice */
    {freq:.028,speed:-.004,amp:10,color:'163,154,142',alpha:.35,lw:1.2,offset:2},    /* stone ghost — human shadow */
    {freq:.022,speed:.005,amp:16,color:'233,228,218',alpha:.85,lw:2.2,offset:0},     /* pearl — primary echo */
    {freq:.035,speed:-.006,amp:8,color:'233,228,218',alpha:.3,lw:1,offset:4},        /* pearl ghost — echo shadow */
    {freq:.012,speed:.002,amp:6,color:'143,134,118',alpha:.2,lw:.8,offset:6},        /* deep harmonic */
  ];

  function waveY(x,t,layer){
    return Math.sin(x*layer.freq+t*layer.speed)*layer.amp
      +Math.sin(x*layer.freq*2.3-t*layer.speed*1.7)*layer.amp*.3
      +Math.cos(x*layer.freq*.7+t*layer.speed*.5)*layer.amp*.15;
  }

  (function draw(t){
    ctx.clearRect(0,0,w,h);
    const cx=w*.5,cy=h*.48;
    const halfW=Math.min(w,h)*.48;

    /* Ambient glow behind center */
    const cg=ctx.createRadialGradient(cx,cy,0,cx,cy,halfW*.6);
    cg.addColorStop(0,'rgba(233,228,218,.08)');cg.addColorStop(.5,'rgba(233,228,218,.02)');cg.addColorStop(1,'rgba(233,228,218,0)');
    ctx.fillStyle=cg;ctx.fillRect(0,0,w,h);

    /* Expanding echo rings from center */
    for(let r=0;r<5;r++){
      const ph=(t*.00035+r*.2)%1,rad=8+ph*halfW*.85;
      ctx.beginPath();ctx.arc(cx,cy,rad,0,Math.PI*2);
      ctx.strokeStyle='rgba(233,228,218,'+((1-ph)*.18).toFixed(3)+')';ctx.lineWidth=.8;ctx.stroke();
    }

    /* Center orb — the "voice origin" */
    const pulse=.85+Math.sin(t*.003)*.15;
    const orbGrad=ctx.createRadialGradient(cx,cy,0,cx,cy,28*pulse);
    orbGrad.addColorStop(0,'rgba(233,228,218,.95)');orbGrad.addColorStop(.3,'rgba(233,228,218,.4)');orbGrad.addColorStop(.7,'rgba(233,228,218,.08)');orbGrad.addColorStop(1,'rgba(233,228,218,0)');
    ctx.fillStyle=orbGrad;ctx.beginPath();ctx.arc(cx,cy,28*pulse,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='rgba(250,248,244,.95)';ctx.beginPath();ctx.arc(cx,cy,3.5,0,Math.PI*2);ctx.fill();

    ctx.lineJoin='round';ctx.lineCap='round';

    /* Draw all waveform layers — left side (human) and right side (echo) */
    layers.forEach(layer=>{
      const eneLeft=layer.color==='163,154,142';
      const eneRight=layer.color==='233,228,218';
      if(!eneLeft&&!eneRight)return;

      ctx.beginPath();
      ctx.strokeStyle='rgba('+layer.color+','+layer.alpha+')';
      ctx.lineWidth=layer.lw;
      if(layer.alpha>.5){ctx.shadowColor='rgba('+layer.color+','+(layer.alpha*.6)+')';ctx.shadowBlur=8;}

      const startX=eneLeft?0:cx;
      const endX=eneLeft?cx:w;
      for(let x=startX;x<=endX;x+=2){
        const u=(x-startX)/(endX-startX);
        /* Envelope: fade in, sustain, fade out */
        const fadeIn=Math.sin(Math.min(1,u*1.2)*Math.PI*.5);
        const fadeOut=Math.sin(Math.max(0,Math.min(1,(1-u)*7))*Math.PI*.5);
        const env=fadeIn*fadeOut;
        const y=cy+waveY(x+layer.offset,t,layer)*env;
        x===startX?ctx.moveTo(x,y):ctx.lineTo(x,y);
      }
      ctx.stroke();ctx.shadowBlur=0;
    });

    /* Ghost reflection — faint inverted echo on right side */
    ctx.beginPath();
    ctx.strokeStyle='rgba(233,228,218,.12)';ctx.lineWidth=.8;
    for(let x=cx;x<=w;x+=3){
      const u=(x-cx)/(w-cx);
      const env=Math.sin(Math.min(1,u*1.08)*Math.PI*.5);
      const y=cy-waveY(x,t,layers[2])*env*.5;
      x===cx?ctx.moveTo(x,y):ctx.lineTo(x,y);
    }
    ctx.stroke();

    /* Floating particles — sparse, atmospheric */
    for(let i=0;i<18;i++){
      const px=cx+Math.sin(t*.0008+i*1.7)*halfW*.7;
      const py=cy+Math.cos(t*.0006+i*2.3)*halfW*.35;
      const sz=.8+Math.sin(t*.002+i)*.5;
      const a=.08+Math.sin(t*.0015+i*3)*.06;
      ctx.fillStyle='rgba(233,228,218,'+a.toFixed(3)+')';
      ctx.beginPath();ctx.arc(px,py,sz,0,Math.PI*2);ctx.fill();
    }

    __raf(draw);
  })(0);
})();


/* Demo DOM refs. These used to resolve as window globals from their id
 * attributes; the mismatched ones (dLatency/dSummary/dFields) threw, and
 * FIELD_DEFS was missing entirely — the demo failed on first click. */
const dTranscript=document.getElementById('dTranscript');
const dChoices=document.getElementById('dChoices');
const dTimer=document.getElementById('dTimer');
const dOrb=document.getElementById('dOrb');
const dChip=document.getElementById('dChip');
const dChipTxt=document.getElementById('dChipTxt');
const dIntBtn=document.getElementById('dIntBtn');
const dEndBtn=document.getElementById('dEndBtn');
const dLatEl=document.getElementById('dLatency');
const dSumEl=document.getElementById('dSummary');
const dFieldsEl=document.getElementById('dFields');
const FIELD_DEFS=[
  ['contact_name','Contact'],
  ['purpose','Purpose'],
  ['outcome','Outcome'],
  ['callback_requested','Callback'],
];

function setField(k,v,conf){
  const row=dFieldsEl.querySelector(`[data-k="${k}"]`);
  if(row)row.querySelector('.v').innerHTML=`${v} <span class="conf ${conf>=85?'hi':'md'}">${conf}%</span>`;
}
function addLat(stt,llm,tts,e2e){
  dLatEl.innerHTML+=`<div class="lat-row"><span>${stt?'Turn '+(dLatEl.children.length+1):'Connecting'}</span><b>STT ${stt||'—'}ms · LLM ${llm}ms · TTS ${tts}ms · E2E ${e2e}ms</b></div>`;
}

let dMode='idle',dSec=0,dTimerIv=null,dWordIv=null,dCurResolve=null;

function dSetState(m,label){
  dMode=m;dOrb.dataset.m=m;
  if(label!==false){dChip.dataset.s=m==='thinking'?'listening':m;dChipTxt.textContent=label||m.charAt(0).toUpperCase()+m.slice(1);}
  dIntBtn.classList.toggle('show',m==='speaking');
}
function dBubble(who,text,instant){
  const b=document.createElement('div');b.className='d-bub '+who;
  b.innerHTML=`<span class="who">${who==='agent'?'Sarathi Agent':'Caller'}</span><span class="txt"></span>`;
  dTranscript.appendChild(b);dTranscript.scrollTop=dTranscript.scrollHeight;
  const txt=b.querySelector('.txt');
  if(instant){txt.textContent=text;return Promise.resolve();}
  const words=text.split(' ');let i=0;
  return new Promise(res=>{
    dCurResolve=res;
    dWordIv=__iv(()=>{
      txt.textContent=words.slice(0,++i).join(' ');
      dTranscript.scrollTop=dTranscript.scrollHeight;
      if(i>=words.length){clearInterval(dWordIv);dCurResolve=null;res();}
    },who==='agent'?95:130);
  });
}
function dStopSpeech(){if(dCurResolve){clearInterval(dWordIv);const r=dCurResolve;dCurResolve=null;r();}}
function dChoice(opts){
  return new Promise(res=>{
    dChoices.innerHTML='';
    opts.forEach(o=>{
      const b=document.createElement('button');b.className='choice-btn';b.textContent=o;
      b.onclick=()=>{dChoices.innerHTML='';dBubble('caller',o,true).then(()=>res(o));};
      dChoices.appendChild(b);
    });
  });
}
function dWait(ms){return new Promise(r=>__to(r,ms))}
async function runDemo(){
  dTranscript.innerHTML='';dLatEl.innerHTML='';dChoices.innerHTML='';
  dSumEl.classList.remove('show');
  FIELD_DEFS.forEach(([k])=>{const r=dFieldsEl.querySelector(`[data-k="${k}"]`);r.querySelector('.v').innerHTML='— <span class="conf wait">waiting</span>';});
  dSec=0;dTimer.textContent='00:00';
  dTimerIv=__iv(()=>{dSec++;dTimer.textContent=String(Math.floor(dSec/60)).padStart(2,'0')+':'+String(dSec%60).padStart(2,'0')},1000);
  dOrb.classList.add('live');
  dSetState('connecting','Connecting');await dWait(800);
  dSetState('listening');await dWait(500);
  setField('contact_name','Mr. Rao',96);
  await dBubble('agent','Hello, am I speaking with Mr. Rao?');
  addLat(180,320,195,695);dSetState('listening');
  const ans=await dChoice(["Yes, speaking.","Sorry, who is this?"]);
  if(ans.startsWith("Sorry")){await dBubble('agent','This is Sarathi, calling from Prestige Realty about your site visit yesterday.');addLat(180,340,190,710);dSetState('listening');}
  setField('purpose','Site visit follow-up',93);dSetState('speaking');
  await dBubble('agent','I\'m calling from Prestige Realty about your site visit yesterday. Did you get a chance to see the 3BHK at Whitefield?');
  addLat(180,310,188,678);dSetState('listening');
  const seen=await dChoice(["Yes, I saw it.","I couldn\'t make it."]);
  if(seen.startsWith("Yes")){
    dSetState('speaking');
    await dBubble('agent','Great. Would you like our sales team to call you with pricing and availability?');
    addLat(180,300,192,672);dSetState('listening');
    const cb=await dChoice(["Yes, please.","Not right now."]);
    const wants=cb.startsWith("Yes");
    setField('outcome',wants?'Interested — pricing call requested':'Visited — not ready yet',90);
    setField('callback_requested',wants?'Yes':'No',92);
    dSetState('speaking');
    await dBubble('agent',wants?'Perfect. I\'ve asked the sales team to call you this evening. Thank you, Mr. Rao.':'Understood. I\'ve noted your feedback. Thank you, Mr. Rao.');
    addLat(180,290,185,655);
  }else{
    dSetState('speaking');
    await dBubble('agent','No problem at all. Would you like to reschedule the visit for this weekend?');
    addLat(180,300,190,668);dSetState('listening');
    const re=await dChoice(["Yes, Saturday works.","No, I\'ll get back to you."]);
    const resched=re.startsWith("Yes");
    setField('outcome',resched?'Visit rescheduled — Saturday':'Not visited — will call back',90);
    setField('callback_requested',resched?'Yes':'No',88);
    dSetState('speaking');
    await dBubble('agent',resched?'Done — you\'re booked for Saturday. I\'ll send the location on WhatsApp. Thank you, Mr. Rao.':'Noted. I\'ll leave it with you — thank you, Mr. Rao.');
    addLat(180,290,186,661);
  }
  finishDemo();
}
function finishDemo(){
  clearInterval(dTimerIv);dSetState('completed','Completed');dOrb.classList.remove('live');
  document.getElementById('dSumTxt').textContent=`Duration ${dTimer.textContent} · ${FIELD_DEFS.length} of ${FIELD_DEFS.length} fields captured · outcome logged to campaign sheet.`;
  dSumEl.classList.add('show');
}
dIntBtn.onclick=()=>{dStopSpeech();dSetState('interrupted','Interrupted');__to(async()=>{dSetState('speaking');await dBubble('agent','Of course — go ahead.');addLat(180,295,188,663);dSetState('listening');},400);};
dEndBtn.onclick=()=>{dStopSpeech();clearInterval(dTimerIv);dChoices.innerHTML='';finishDemo();};
dOrb.onclick=()=>{if(dMode==='idle'||dMode==='completed')runDemo();};

/* ---------- three.js scenes ---------- */
/* ═══════════════════════════════════════════════════
   Echo Sarathi · 3D layer (Three.js)
   B — "Orbital Voice Core": closing flourish in CTA
   ═══════════════════════════════════════════════════ */
const RM=matchMedia('(prefers-reduced-motion: reduce)').matches;
const DPR=Math.min(devicePixelRatio||1,1.75);
const PEARL=0xe9e4da;
let mx=0,my=0;
__on(window, 'pointermove',e=>{mx=e.clientX/innerWidth*2-1;my=e.clientY/innerHeight*2-1},{passive:true});
function makeRenderer(cv){
  const r=new THREE.WebGLRenderer({canvas:cv,alpha:true,antialias:false,powerPreference:'low-power'});
  r.setPixelRatio(DPR);r.setClearColor(0x000000,0);
  return r;
}

/* ── Scene A removed — hero uses CSS ambient glow + echo wave canvas ── */

/* ── Scene B · Orbital Voice Core (CTA) ── */
(function(){
  const cv=document.getElementById('ctaOrb');if(!cv)return;
  let renderer;try{renderer=makeRenderer(cv)}catch(e){return}
  const scene=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(45,1,.1,30);
  cam.position.set(0,0,6.6);
  const group=new THREE.Group();scene.add(group);

  const CN=850,R=1.28,cp=new Float32Array(CN*3),GA=Math.PI*(3-Math.sqrt(5));
  for(let i=0;i<CN;i++){
    const y=1-(i/(CN-1))*2,r=Math.sqrt(Math.max(0,1-y*y)),th=GA*i;
    cp[i*3]=Math.cos(th)*r*R;cp[i*3+1]=y*R;cp[i*3+2]=Math.sin(th)*r*R;
  }
  const cg=new THREE.BufferGeometry();
  cg.setAttribute('position',new THREE.BufferAttribute(cp,3));
  const core=new THREE.Points(cg,new THREE.PointsMaterial({color:PEARL,size:.035,sizeAttenuation:true,transparent:true,opacity:.95,depthWrite:false}));
  group.add(core);

  const gc=document.createElement('canvas');gc.width=gc.height=128;
  const gx=gc.getContext('2d');
  const gg=gx.createRadialGradient(64,64,0,64,64,64);
  gg.addColorStop(0,'rgba(233,228,218,.55)');gg.addColorStop(.4,'rgba(233,228,218,.14)');gg.addColorStop(1,'rgba(233,228,218,0)');
  gx.fillStyle=gg;gx.fillRect(0,0,128,128);
  const glow=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(gc),transparent:true,depthWrite:false,opacity:.8}));
  glow.scale.setScalar(3.4);scene.add(glow);

  function ring(rad,count,tx,tz){
    const g=new THREE.BufferGeometry(),p=new Float32Array(count*3);
    for(let i=0;i<count;i++){
      const a=i/count*Math.PI*2;
      p[i*3]=Math.cos(a)*rad;p[i*3+1]=(Math.random()-.5)*.06;p[i*3+2]=Math.sin(a)*rad;
    }
    g.setAttribute('position',new THREE.BufferAttribute(p,3));
    const h=new THREE.Group();h.rotation.set(tx,0,tz);
    h.add(new THREE.Points(g,new THREE.PointsMaterial({color:STONE,size:.03,sizeAttenuation:true,transparent:true,opacity:.7,depthWrite:false})));
    group.add(h);return h;
  }
  const r1=ring(2.05,240,1.15,.35),r2=ring(2.55,300,-.9,-.5);
  const head=new THREE.Points(
    new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(new Float32Array([2.05,0,0]),3)),
    new THREE.PointsMaterial({color:PEARL,size:.09,sizeAttenuation:true,transparent:true,opacity:1,depthWrite:false}));
  r1.add(head);

  const clock=new THREE.Clock();
  function size(){
    const s=cv.clientWidth||320;
    renderer.setSize(s,s,false);cam.aspect=1;cam.updateProjectionMatrix();
  }
  size();__on(window, 'resize',size);
  let vis=true,raf=null;
  function frame(){
    const t=clock.getElapsedTime();
    core.rotation.y=t*.22;core.rotation.x=Math.sin(t*.18)*.14;
    group.rotation.y=t*.07;
    r1.rotation.y=t*.5;r2.rotation.y=-t*.36;
    const hp=t*1.4%(Math.PI*2);
    head.position.set(Math.cos(hp)*2.05,0,Math.sin(hp)*2.05);
    glow.material.opacity=.66+Math.sin(t*2.1)*.16;
    glow.scale.setScalar(3.25+Math.sin(t*2.1)*.3);
    cam.position.x+=(mx*.5-cam.position.x)*.05;
    cam.position.y+=(-my*.4-cam.position.y)*.05;
    cam.lookAt(0,0,0);
    renderer.render(scene,cam);
    raf=(vis&&!document.hidden)?__raf(frame):null;
  }
  if(RM){core.rotation.y=.6;r1.rotation.y=1.1;r2.rotation.y=-.8;renderer.render(scene,cam)}
  else{
    new IntersectionObserver(es=>es.forEach(e=>{
      const was=!!raf;vis=e.isIntersecting;
      if(vis&&!was){clock.getDelta();if(!raf)frame()}
    }),{threshold:.05}).observe(cv);
    __on(document, 'visibilitychange',()=>{
      if(!document.hidden&&vis&&!raf){clock.getDelta();frame()}
    });
    frame();
  }
})();

  return function destroyOdLanding() {
    __dead = true;
    window.IntersectionObserver = __RealIO;
    for (const fn of __cleanups.splice(0)) {
      try { fn(); } catch { /* already gone */ }
    }
  };
}
