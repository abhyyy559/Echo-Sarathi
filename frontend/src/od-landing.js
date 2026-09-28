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


/* ---------- wave canvas + showcase + demo + widget + cursor + monitor + replay ---------- */
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
  dTarget=m==='speaking'?.9:m==='listening'?.34:m==='interrupted'?.12:.06;
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
  setField('parent_name','Mr. Rao',96);
  await dBubble('agent','Hello, am I speaking with Mr. Rao, Anika\'s father?');
  addLat(180,320,195,695);dSetState('listening');
  const ans=await dChoice(["Yes, speaking.","Sorry, who is this?"]);
  if(ans.startsWith("Sorry")){await dBubble('agent','This is Sarathi, calling from CMR College of Engineering & Technology about Anika\'s attendance.');addLat(180,340,190,710);dSetState('listening');}
  setField('student_name','Anika',94);dSetState('speaking');
  await dBubble('agent','Thank you. Could you tell me whether Anika will attend classes today?');
  addLat(180,310,188,678);dSetState('listening');
  const att=await dChoice(["She\'s unwell today.","Yes, she\'ll be there."]);
  if(att.startsWith("She")){
    setField('present_today','No',91);setField('reason','Sick leave',88);
    dSetState('speaking');
    await dBubble('agent','I\'m sorry to hear that. Should I ask her class teacher to call you back this evening?');
    addLat(180,300,192,672);dSetState('listening');
    const cb=await dChoice(["Yes, please.","No, that\'s fine."]);
    setField('callback_requested',cb.startsWith("Yes")?'Yes':'No',90);
    dSetState('speaking');
    await dBubble('agent','Noted. I\'ve recorded everything for the school. Wishing Anika a quick recovery — thank you, Mr. Rao.');
    addLat(180,290,185,655);
  }else{
    setField('present_today','Yes',93);setField('reason','Attending',87);setField('callback_requested','No',84);
    dSetState('speaking');
    await dBubble('agent','Wonderful. That\'s recorded for the school register — thank you, Mr. Rao. Have a good day.');
    addLat(180,310,190,680);
  }
  finishDemo();
}
function finishDemo(){
  clearInterval(dTimerIv);dSetState('completed','Completed');dOrb.classList.remove('live');
  document.getElementById('dSumTxt').textContent=`Duration ${dTimer.textContent} · 5 of 5 fields captured · outcome logged to campaign sheet.`;
  dSumEl.classList.add('show');
}
dIntBtn.onclick=()=>{dStopSpeech();dSetState('interrupted','Interrupted');__to(async()=>{dSetState('speaking');await dBubble('agent','Of course — go ahead.');addLat(180,295,188,663);dSetState('listening');},400);};
dEndBtn.onclick=()=>{dStopSpeech();clearInterval(dTimerIv);dChoices.innerHTML='';finishDemo();};
dOrb.onclick=()=>{if(dMode==='idle'||dMode==='completed')runDemo();};

/* ═══════════════════════════════════════════════════
   Floating Agent Widget
   ═══════════════════════════════════════════════════ */
const agentFab=document.getElementById('agentFab');
const agentPanel=document.getElementById('agentPanel');
const apClose=document.getElementById('apClose');
const apBody=document.getElementById('apBody');
const apInput=document.getElementById('apInput');
const apSend=document.getElementById('apSend');
agentFab.onclick=()=>{agentPanel.classList.toggle('open');agentFab.classList.toggle('open');if(agentPanel.classList.contains('open'))apInput.focus()};
apClose.onclick=()=>{agentPanel.classList.remove('open');agentFab.classList.remove('open')};

const AGENT_REPLIES=[
  "Sarathi makes outbound phone calls using AI voice agents. Upload a contact list, pick an agent, and it handles the conversation — then returns structured data.",
  "Each agent can be customized with questions, context, and an extraction schema. The agent weaves questions into natural conversation, not a rigid script.",
  "Right now we support English. Telugu is next on the roadmap, followed by Telugu+English code-switching and multiple Indian languages.",
  "Try the Playground to test an agent with zero telephony cost. You can speak or type, and see extracted fields populate in real time.",
  "Campaigns run during 9 AM – 9 PM IST. The system handles busy signals, no-answers, and callbacks automatically.",
  "Every call returns a transcript, extracted fields with confidence scores, call duration, and outcome — all exportable as CSV or Excel.",
  "The interrupt handling is real: if a caller speaks while the agent is talking, the agent stops immediately and listens.",
  "You can build agents for attendance calls, surveys, fee reminders, confirmations, follow-ups, qualification — anything that needs a structured phone conversation."
];
let agentMsgIdx=0;
function agentReply(text){const d=document.createElement('div');d.className='msg bot';d.textContent=text;apBody.appendChild(d);apBody.scrollTop=apBody.scrollHeight;}
function agentUserMsg(text){const d=document.createElement('div');d.className='msg user';d.textContent=text;apBody.appendChild(d);apBody.scrollTop=apBody.scrollHeight;}
function handleAgentSend(){const v=apInput.value.trim();if(!v)return;agentUserMsg(v);apInput.value='';__to(()=>{agentReply(AGENT_REPLIES[agentMsgIdx%AGENT_REPLIES.length]);agentMsgIdx++},500);}
apSend.onclick=handleAgentSend;
apInput.onkeydown=e=>{if(e.key==='Enter')handleAgentSend()};

/* ═══════════════════════════════════════════════════
   Custom cursor (fine pointers only)
   ═══════════════════════════════════════════════════ */
(function(){
  if(!matchMedia('(pointer:fine)').matches)return;
  const dot=document.createElement('div');dot.className='cursor-dot';
  const ring=document.createElement('div');ring.className='cursor-ring';
  document.body.append(dot,ring);
  document.body.classList.add('custom-cursor');
  let mx=-100,my=-100,rx=-100,ry=-100;
  __on(window, 'mousemove',e=>{
    mx=e.clientX;my=e.clientY;
    dot.style.left=mx+'px';dot.style.top=my+'px';
  },{passive:true});
  (function loop(){
    rx+=(mx-rx)*.16;ry+=(my-ry)*.16;
    ring.style.left=rx+'px';ring.style.top=ry+'px';
    __raf(loop);
  })();
  document.querySelectorAll('a,button,.step,.transform-card,.problem-item,.stat-card').forEach(el=>{
    const enter=()=>ring.classList.add('hover'), leave=()=>ring.classList.remove('hover');
    __on(el, 'mouseenter', enter);
    __on(el, 'mouseleave', leave);
  });
})();

/* ═══════════════════════════════════════════════════
   Live Call Monitor — animated campaign dashboard
   ═══════════════════════════════════════════════════ */
(function(){
  const contacts=[
    {n:'Priya Sharma',p:'+91 98765 43210'},
    {n:'Rahul Patel',p:'+91 87654 32109'},
    {n:'Ananya Gupta',p:'+91 76543 21098'},
    {n:'Vikram Singh',p:'+91 65432 10987'},
    {n:'Deepa Nair',p:'+91 54321 09876'},
    {n:'Arjun Reddy',p:'+91 43210 98765'},
    {n:'Meera Joshi',p:'+91 32109 87654'},
    {n:'Sanjay Kumar',p:'+91 21098 76543'},
    {n:'Kavita Das',p:'+91 10987 65432'},
    {n:'Rohan Verma',p:'+91 09876 54321'},
  ];
  const statuses=['ok','ringing','miss','busy'];
  const weights=[.55,.2,.18,.07];
  const durations=['0:42','1:18','0:56','—','1:04','0:33','1:31','0:47','0:59','—'];

  const rowsEl=document.getElementById('monRows');
  const chartEl=document.getElementById('monChart');
  const labelsEl=document.getElementById('monLabels');

  /* Build row HTML */
  contacts.forEach((c,i)=>{
    const row=document.createElement('div');row.className='mon-row';
    row.id='mr'+i;
    row.innerHTML='<span class="name">'+c.n+'</span><span class="phone">'+c.p+'</span><span class="status miss">Queued</span><span class="dur">—</span>';
    rowsEl.appendChild(row);
  });

  /* Build chart bars */
  const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const dayCounts=[12,18,24,8,31,6,0];
  const maxD=Math.max(...dayCounts);
  days.forEach((d,i)=>{
    const bar=document.createElement('div');bar.className='mon-bar';
    bar.style.height='4px';bar.setAttribute('data-n',dayCounts[i]);
    bar.id='mb'+i;
    chartEl.appendChild(bar);
    const lb=document.createElement('span');lb.textContent=d;labelsEl.appendChild(lb);
  });

  /* Animate counters */
  const done=document.getElementById('monDone');
  const active=document.getElementById('monActive');
  const miss=document.getElementById('monMiss');
  const busy=document.getElementById('monBusy');
  let dN=0,aN=0,mN=0,bN=0;

  function pickStatus(){
    let r=Math.random(),acc=0;
    for(let i=0;i<weights.length;i++){acc+=weights[i];if(r<=acc)return statuses[i];}
    return statuses[0];
  }

  /* Animate chart on scroll */
  new IntersectionObserver((es,ob)=>es.forEach(e=>{
    if(!e.isIntersecting)return;
    ob.disconnect();
    /* Stagger bar heights */
    dayCounts.forEach((c,i)=>{
      __to(()=>{document.getElementById('mb'+i).style.height=(c/maxD*100)+'%'},i*80);
    });
    /* Animate contacts */
    let idx=0;
    function nextCall(){
      if(idx>=contacts.length)return;
      const row=document.getElementById('mr'+idx);
      const st=row.querySelector('.status');
      /* Ringing */
      st.textContent='Ringing';st.className='status ringing';
      active.textContent=++aN;
      const dur=1200+Math.random()*1800;
      __to(()=>{
        const s=pickStatus();
        active.textContent=Math.max(0,--aN);
        st.textContent=s==='ok'?'Answered':s==='miss'?'No answer':s==='busy'?'Busy':s;
        st.className='status '+s;
        if(s==='ok'){done.textContent=++dN;row.querySelector('.dur').textContent=durations[idx%durations.length]}
        else if(s==='miss')miss.textContent=++mN;
        else busy.textContent=++bN;
        idx++;__to(nextCall,400+Math.random()*600);
      },dur);
    }
    __to(nextCall,600);
  }),{threshold:.3}).observe(document.getElementById('monShell'));
})();

/* ═══════════════════════════════════════════════════
   Conversation Replay — step-by-step transcript
   ═══════════════════════════════════════════════════ */
(function(){
  const turns=[
    {who:'agent',text:'Good morning! This is Sarathi calling from CMR College of Engineering & Technology. May I speak with Mrs. Kumar?',time:'0:00'},
    {who:'caller',text:'Yes, this is she. Who is this?',time:'0:04'},
    {who:'agent',text:'Mrs. Kumar, I\'m calling because Aarav was absent from school today. I wanted to check if everything is alright and if there\'s anything we should know.',time:'0:07'},
    {who:'caller',text:'Oh yes, Aarav has a dental appointment this morning. He should be back by lunch.',time:'0:18'},
    {who:'agent',text:'Thank you for letting us know. Could I get the reason documented — you mentioned a dental appointment?',time:'0:24'},
    {who:'caller',text:'Yes, it\'s a routine dental checkup at Dr. Mehta\'s clinic.',time:'0:31'},
    {who:'agent',text:'Perfect. And will Aarav return for the afternoon session?',time:'0:36'},
    {who:'caller',text:'Yes, he\'ll be there by 1 PM.',time:'0:40'},
    {who:'agent',text:'Wonderful. I\'ve noted the absence as a medical appointment. Is there anything else you\'d like us to know?',time:'0:43'},
    {who:'caller',text:'No, that\'s all. Thank you for calling.',time:'0:52'},
    {who:'agent',text:'You\'re welcome, Mrs. Kumar. Have a great day. Goodbye!',time:'0:55'},
  ];

  const fieldReveal=[
    {at:1,field:0},{at:2,field:1},{at:3,field:2},{at:3,field:3},{at:9,field:4},{at:10,field:5}
  ];

  const transcript=document.getElementById('replayTranscript');
  const fields=document.querySelectorAll('#replayFields .rf-row .v');

  /* Build initial turn elements */
  const turnEls=turns.map((t,i)=>{
    const el=document.createElement('div');
    el.className='replay-turn '+t.who;
    el.innerHTML='<div class="avatar">'+(t.who==='agent'?'S':'P')+'</div><div><div class="text">'+t.text+'</div><div class="time">'+t.time+'</div></div>';
    transcript.appendChild(el);
    return el;
  });

  /* Animate on scroll */
  new IntersectionObserver((es,ob)=>es.forEach(e=>{
    if(!e.isIntersecting)return;
    ob.disconnect();
    let ti=0;
    function showNext(){
      if(ti>=turns.length)return;
      turnEls[ti].classList.add('show');
      transcript.scrollTop=transcript.scrollHeight;
      /* Check if any fields should be revealed at this turn */
      fieldReveal.forEach(fr=>{
        if(fr.at===ti){
          const f=fields[fr.field];
          f.textContent=f.dataset.val;
          f.classList.remove('pending');
          f.style.color='var(--fg)';
        }
      });
      ti++;
      __to(showNext,700);
    }
    showNext();
  }),{threshold:.2}).observe(document.getElementById('replayShell'));

  /* Mini waveform in replay panel */
  const wv=document.getElementById('replayWave');
  if(wv){
    const wctx=wv.getContext('2d');
    let rw,rh;
    function wResize(){rw=wv.width=wv.clientWidth;rh=wv.height=wv.clientHeight}
    wResize();__on(window, 'resize',wResize);
    (function drawW(t){
      wctx.clearRect(0,0,rw,rh);
      wctx.beginPath();wctx.strokeStyle='rgba(233,228,218,.4)';wctx.lineWidth=1.2;
      for(let x=0;x<=rw;x+=2){
        const u=x/rw;
        const env=Math.sin(u*Math.PI);
        const y=rh/2+env*(Math.sin(x*.04+t*.003)*6+Math.sin(x*.08-t*.005)*3);
        x===0?wctx.moveTo(x,y):wctx.lineTo(x,y);
      }
      wctx.stroke();
      __raf(drawW);
    })(0);
  }
})();

/* ---------- labs: simulator / latency / voices ---------- */
/* ═══════════════════════════════════════════════════
   Interactive Labs — simulator / latency / voices
   ═══════════════════════════════════════════════════ */
(function(){
'use strict';
const RM=matchMedia('(prefers-reduced-motion: reduce)').matches;

function typeInto(el,text,delay,cps){
  clearTimeout(el._t);el.textContent='';
  const caret=document.createElement('span');caret.className='type-caret';el.appendChild(caret);
  let i=0;const per=RM?0:Math.max(12,1000/cps);
  __to(function step(){
    if(i<text.length){caret.insertAdjacentText('beforebegin',text[i]);i++;el._t=__to(step,per)}
  },delay);
}

/* ── Campaign simulator ── */
const CONTACTS=[
  {n:'Asha K.',ini:'A',ph:'+91 98××× ×2103',ok:1,f:'Confirmed — Friday 4 PM works',d:'0:52',c:96},
  {n:'Ravi T.',ini:'R',ph:'+91 99××× ×8842',ok:1,f:'Will attend, asked for bus route',d:'0:47',c:92},
  {n:'Meera S.',ini:'M',ph:'+91 97××× ×3327',ok:0,st:'Busy',d:'0:06'},
  {n:'Deepak R.',ini:'D',ph:'+91 96××× ×5518',ok:0,st:'No answer',d:'—'},
  {n:'Fathima Z.',ini:'F',ph:'+91 95××× ×9046',ok:1,f:'Absent — fever, back Monday',d:'1:04',c:95},
  {n:'Karthik V.',ini:'K',ph:'+91 94××× ×7765',ok:1,f:'Confirmed, joining late',d:'0:41',c:91},
  {n:'Lakshmi P.',ini:'L',ph:'+91 93××× ×2294',ok:1,f:'Confirmed — parent callback requested',d:'0:58',c:89},
  {n:'Sana H.',ini:'S',ph:'+91 92××× ×6631',ok:1,f:'Confirmed',d:'0:38',c:97}
];
const simList=document.getElementById('simList');
CONTACTS.forEach((p,i)=>{
  const el=document.createElement('div');el.className='sim-contact';el.id='sc'+i;
  el.innerHTML='<span class="avatar">'+p.ini+'</span><span class="meta"><span class="nm">'+p.n+'</span><br><span class="ph">'+p.ph+'</span></span><span class="sim-chip" id="schip'+i+'">Queued</span>';
  simList.appendChild(el);
});
let simTimers=[],simRunning=false,clockInt=null;
function chip(i,txt,cls){const c=document.getElementById('schip'+i);c.textContent=txt;c.className='sim-chip '+cls}
function resetSim(){
  simTimers.forEach(clearTimeout);simTimers=[];clearInterval(clockInt);simRunning=false;
  document.getElementById('cQueued').textContent='8';
  document.getElementById('cCalling').textContent='0';
  document.getElementById('cDone').textContent='0';
  document.getElementById('cMissed').textContent='0';
  document.getElementById('simBar').style.width='0';
  document.getElementById('simFeed').innerHTML='';
  document.getElementById('simSummary').classList.remove('in');
  document.getElementById('simClock').textContent='00:00';
  CONTACTS.forEach((_,i)=>{chip(i,'Queued','');document.getElementById('sc'+i).classList.remove('hot')});
}
function runSim(){
  if(simRunning)return;
  resetSim();simRunning=true;
  const feed=document.getElementById('simFeed'),bar=document.getElementById('simBar');
  let q=8,cDone=0,cMiss=0;const t0=Date.now();
  clockInt=__iv(()=>{const s=Math.floor((Date.now()-t0)/1000);
    document.getElementById('simClock').textContent=String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')},500);
  let t=400;
  CONTACTS.forEach((p,i)=>{
    simTimers.push(__to(()=>{
      if(!simRunning)return;
      document.getElementById('cQueued').textContent=String(--q);
      const cc=document.getElementById('cCalling');cc.textContent=String(+cc.textContent+1);
      chip(i,'Calling','calling');document.getElementById('sc'+i).classList.add('hot');
    },t));
    t+=RM?60:(900+Math.random()*450);
    simTimers.push(__to(()=>{
      if(!simRunning)return;
      const cc=document.getElementById('cCalling');cc.textContent=String(Math.max(0,+cc.textContent-1));
      document.getElementById('sc'+i).classList.remove('hot');
      const row=document.createElement('div');row.className='sim-row';
      row.innerHTML='<span class="nm">'+p.n+'</span>'+
        '<span class="out '+(p.ok?'ok':'bad')+'">'+(p.ok?'Completed':p.st)+'</span>'+
        '<span class="dur">'+p.d+'</span>'+
        '<span class="field">'+(p.ok?p.f:'— retry scheduled')+'</span>'+
        (p.ok?'<span class="conf">'+p.c+'%</span>':'<span></span>');
      feed.appendChild(row);
      __raf(()=>__raf(()=>row.classList.add('in')));
      if(p.ok){cDone++;chip(i,'Done','done')}else{cMiss++;chip(i,p.st,'missed')}
      document.getElementById('cDone').textContent=String(cDone);
      document.getElementById('cMissed').textContent=String(cMiss);
      bar.style.width=(((i+1)/CONTACTS.length)*100)+'%';
      if(i===CONTACTS.length-1){
        simRunning=false;clearInterval(clockInt);
        document.getElementById('simSumTxt').innerHTML='<strong style="color:var(--fg)">6 of 8 answered</strong> · 5 confirmations captured · 1 flagged for human follow-up · results ready to export.';
        __to(()=>document.getElementById('simSummary').classList.add('in'),250);
      }
    },t));
  });
}
__on(document.getElementById('simStart'), 'click', runSim);
__on(document.getElementById('simReset'), 'click', resetSim);

/* ── Latency lab ── */
const LAT=[{key:'ls_',d:{stt:180,llm:260,tts:200,e2e:640},col:'latColS',ans:'latAnsS',
             reply:'Done — I\u2019ve moved it to Friday between 2 and 6 PM. You\u2019ll get a confirmation text.',cps:46,delay:1450},
            {key:'lb_',d:{stt:430,llm:1180,tts:530,e2e:2140},col:null,ans:'latAnsB',
             reply:'Sorry… could you repeat that? Friday… delivery… moved… I think. Confirming… maybe.',cps:24,delay:2450}];
const MAXMS=2400;
LAT.forEach(L=>{
  const box=document.getElementById(L.key==='ls_'?'latRowsS':'latRowsB');box.innerHTML='';
  [['Speech recognition','stt'],['Reasoning','llm'],['Voice synthesis','tts'],['End-to-end','e2e']].forEach(([lab,k])=>{
    const d=L.d[k];
    const ticks=k==='e2e'
      ?'<span class="lat-tick" style="left:37.5%"></span><span class="lat-tick" style="left:62.5%"></span>'
      :'<span class="lat-tick" style="left:37.5%"></span>';
    const row=document.createElement('div');row.className='lat-mrow';
    row.innerHTML='<div class="lat-mhead"><span>'+lab+'</span><b id="'+L.key+k+'">—</b></div>'+
      '<div class="lat-track"><span class="lat-fill" id="'+L.key+'fill'+k+'" style="width:0"></span>'+ticks+'</div>';
    box.appendChild(row);
  });
});
function countTo(el,target,dur){
  if(RM||dur<=0){el.textContent=target+' ms';return}
  const t0=performance.now();
  (function step(t){const p=Math.min(1,(t-t0)/dur);
    el.textContent=Math.round(target*(1-Math.pow(1-p,3)))+' ms';
    if(p<1)__raf(step)})(t0);
}
let latBusy=false;
function runTurn(){
  if(latBusy)return;latBusy=true;
  const colS=document.getElementById('latColS');colS.classList.remove('done');
  const aS=document.getElementById('latAnsS'),aB=document.getElementById('latAnsB');
  clearTimeout(aS._t);clearTimeout(aB._t);aS.textContent='';
  aB.innerHTML='<span class="typing"><i></i><i></i><i></i></span>';
  LAT.forEach(L=>{
    ['stt','llm','tts','e2e'].forEach((k,idx)=>{
      const f=document.getElementById(L.key+'fill'+k),num=document.getElementById(L.key+k);
      const dur=RM?0:Math.max(380,L.d[k]*0.9);
      const stag=RM?0:idx*240;
      f.style.transition='none';f.style.width='0%';
      void f.offsetWidth;
      f.style.transitionDelay=stag+'ms';
      f.style.transition='width '+dur+'ms cubic-bezier(.25,.1,.25,1)';
      __raf(()=>{f.style.width=(L.d[k]/MAXMS*100)+'%'});
      __to(()=>countTo(num,L.d[k],dur),stag);
    });
    typeInto(document.getElementById(L.ans),L.reply,RM?0:L.delay,L.cps);
  });
  __to(()=>{colS.classList.add('done');latBusy=false},RM?60:3900);
}
__on(document.getElementById('latRun'), 'click', runTurn);
new IntersectionObserver((es,ob)=>es.forEach(e=>{
  if(e.isIntersecting){__to(runTurn,350);ob.disconnect()}
}),{threshold:.35}).observe(document.getElementById('latShell'));

/* ── Voice gallery ── */
const VOICES=[
  {name:'Asha',traits:'Warm · Measured',line:'Hello! This is Asha calling from CMR College of Engineering & Technology about Aarav\u2019s attendance today.'},
  {name:'Rohan',traits:'Calm · Reassuring',line:'Hi, this is Rohan. Just a gentle reminder about tomorrow\u2019s appointment at ten.'},
  {name:'Meera',traits:'Bright · Energetic',line:'Hey! Meera here — a quick call to confirm your slot for Saturday\u2019s session.'},
  {name:'Arjun',traits:'Deep · Authoritative',line:'Good evening. Arjun calling regarding the pending fee reminder for this month.'},
  {name:'Divya',traits:'Soft · Patient',line:'Hello, this is Divya. Take your time — I have two small questions when you\u2019re ready.'},
  {name:'Kabir',traits:'Crisp · Professional',line:'Kabir from operations. One confirmation and I\u2019ll let you go — thirty seconds.'}
];
const grid=document.getElementById('voiceGrid');
const cvs=[];
VOICES.forEach((v,i)=>{
  const b=document.createElement('button');b.className='voice-card';b.type='button';
  b.setAttribute('role','radio');b.setAttribute('aria-checked','false');
  b.innerHTML='<span class="vc-check"><svg viewBox="0 0 24 24"><path d="M4 12l5 5 11-11"/></svg></span>'+
    '<canvas width="260" height="54"></canvas>'+
    '<div class="vc-name">'+v.name+'</div><div class="vc-traits">'+v.traits+'</div>';
  __on(b, 'click', ()=>selectVoice(i));
  grid.appendChild(b);cvs.push(b.querySelector('canvas'));
});
const SIG=i=>({f:.085+i*.013,a:8+(i%3)*3.5,j:i*.9,sp:.0016+i*.00022});
const speak=new Float32Array(VOICES.length);let sel=-1,vInt=null;
function drawSig(cv,i,t){
  const ctx=cv.getContext('2d'),w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);
  const s=SIG(i),spk=speak[i];
  ctx.beginPath();
  for(let x=0;x<=w;x+=2){
    const env=Math.sin(x/w*Math.PI);
    const y=h/2+env*(Math.sin(x*s.f+t*s.sp+s.j)*s.a*(1+spk*1.7)+Math.sin(x*s.f*2.7-t*s.sp*1.7)*s.a*.35*(1+spk));
    x===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  }
  ctx.strokeStyle=i===sel?'rgba(233,228,218,.92)':'rgba(163,154,142,.5)';
  ctx.lineWidth=i===sel?2:1.3;ctx.stroke();
}
if(RM){cvs.forEach((cv,i)=>drawSig(cv,i,4200))}
else{(function loop(t){cvs.forEach((cv,i)=>drawSig(cv,i,t));__raf(loop)})(0)}
function selectVoice(i){
  sel=i;
  [...grid.children].forEach((c,j)=>c.setAttribute('aria-checked',j===i?'true':'false'));
  document.getElementById('vpVoice').textContent=VOICES[i].name;
  clearInterval(vInt);speak.fill(0);speak[i]=1;
  vInt=__iv(()=>{speak[i]=Math.max(0,speak[i]-.03);if(speak[i]<=0)clearInterval(vInt)},60);
  typeInto(document.getElementById('vpLine'),'\u201C'+VOICES[i].line+'\u201D',120,30);
}
})();

/* ---------- three.js scenes ---------- */
/* ═══════════════════════════════════════════════════
   Echo Sarathi · 3D layer (Three.js)
   B — "Orbital Voice Core": closing flourish in CTA
   C — "Signal → Structure": speech ribbon → grid
   D — "Barge-in Theater": interruption demo
   E — "Language Field": multilingual roadmap
   ═══════════════════════════════════════════════════ */
const RM=matchMedia('(prefers-reduced-motion: reduce)').matches;
const DPR=Math.min(devicePixelRatio||1,1.75);
const PEARL=0xe9e4da,STONE=0xa39a8e;
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
/* ── Scene C · Signal → Structure (flow band) ── */
(function(){
  const cv=document.getElementById('flowGl');if(!cv)return;
  let renderer;try{renderer=makeRenderer(cv)}catch(e){return}
  const scene=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(50,2.8,.1,60);
  cam.position.set(0,.3,11);

  /* stream: organic speech ribbon feeding the grid */
  const SN=1500;
  const su=new Float32Array(SN),ss=new Float32Array(SN),sp=new Float32Array(SN*3);
  for(let i=0;i<SN;i++){su[i]=Math.random();ss[i]=Math.random()*6.283}
  const sg=new THREE.BufferGeometry();
  sg.setAttribute('position',new THREE.BufferAttribute(sp,3));
  sg.setAttribute('u',new THREE.BufferAttribute(su,1));
  sg.setAttribute('seed',new THREE.BufferAttribute(ss,1));
  const smat=new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    uniforms:{t:{value:0},px:{value:DPR}},
    vertexShader:`attribute float u;attribute float seed;uniform float t;uniform float px;
      varying float vA;
      void main(){
        float uu=fract(u+t*.06);
        vec3 p;
        p.x=uu*10.9-9.6;
        float env=sin(min(uu/.62,1.)*3.1416);
        p.y=sin(uu*24.+t*2.4+seed)*.62*env+sin(uu*11.-t*1.5+seed*.7)*.34*env;
        p.z=sin(uu*17.-t*1.1+seed*2.1)*.85*env;
        vA=smoothstep(0.,.05,uu)*(1.-smoothstep(.78,.97,uu))*.8;
        vec4 mv=modelViewMatrix*vec4(p,1.);
        gl_Position=projectionMatrix*mv;
        gl_PointSize=1.9*(95.*px/-mv.z);
      }`,
    fragmentShader:`precision mediump float;varying float vA;
      void main(){
        float msk=smoothstep(.5,.12,length(gl_PointCoord-.5));
        float a=msk*vA;
        if(a<.004)discard;
        gl_FragColor=vec4(vec3(.64,.604,.557),a);
      }`
  });
  scene.add(new THREE.Points(sg,smat));

  /* grid: 16×6 living spreadsheet, columns light up as data lands */
  const GC=16,GR=6,GD=5,GN=GC*GR*GD;
  const gp=new Float32Array(GN*3),gc=new Float32Array(GN),gs=new Float32Array(GN);
  let k=0;
  for(let c=0;c<GC;c++)for(let r=0;r<GR;r++)for(let d=0;d<GD;d++,k++){
    gp[k*3]=.9+c*.56+(Math.random()-.5)*.36;
    gp[k*3+1]=(r-2.5)*.62+(Math.random()-.5)*.42;
    gp[k*3+2]=(Math.random()-.5)*.25;
    gc[k]=c;gs[k]=Math.random()*6.283;
  }
  const gg2=new THREE.BufferGeometry();
  gg2.setAttribute('position',new THREE.BufferAttribute(gp,3));
  gg2.setAttribute('col',new THREE.BufferAttribute(gc,1));
  gg2.setAttribute('seed',new THREE.BufferAttribute(gs,1));
  const gmat=new THREE.ShaderMaterial({
    transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,
    uniforms:{t:{value:0},px:{value:DPR}},
    vertexShader:`attribute float col;attribute float seed;uniform float t;uniform float px;
      varying float vB;
      void main(){
        float sweep=fract(t*.13)*17.5-1.;
        float pulse=exp(-pow(col-sweep,2.)*1.4);
        float shim=.82+.18*sin(t*2.1+seed*3.);
        vB=clamp(.16+pulse*.95,0.,1.)*shim;
        vec4 mv=modelViewMatrix*vec4(position,1.);
        gl_Position=projectionMatrix*mv;
        gl_PointSize=(1.5+vB*1.7)*(95.*px/-mv.z);
      }`,
    fragmentShader:`precision mediump float;varying float vB;
      void main(){
        float msk=smoothstep(.5,.12,length(gl_PointCoord-.5));
        float a=msk*vB;
        if(a<.004)discard;
        vec3 c=mix(vec3(.42,.394,.362),vec3(.914,.894,.855),vB);
        gl_FragColor=vec4(c,a*.9);
      }`
  });
  scene.add(new THREE.Points(gg2,gmat));

  const clock=new THREE.Clock();
  function size(){
    const w=cv.clientWidth||innerWidth,h=cv.clientHeight||380;
    renderer.setSize(w,h,false);cam.aspect=w/h;cam.updateProjectionMatrix();
  }
  size();__on(window, 'resize',size);
  let vis=true,raf=null;
  function frame(){
    const t=clock.getElapsedTime();
    smat.uniforms.t.value=t;gmat.uniforms.t.value=t;
    cam.position.x+=(mx*.55-cam.position.x)*.03;
    cam.position.y+=((.3-my*.35)-cam.position.y)*.03;
    cam.lookAt(-.4,0,0);
    renderer.render(scene,cam);
    raf=(vis&&!document.hidden)?__raf(frame):null;
  }
  if(RM){smat.uniforms.t.value=6;gmat.uniforms.t.value=6;renderer.render(scene,cam)}
  else{
    new IntersectionObserver(es=>es.forEach(e=>{
      const was=!!raf;vis=e.isIntersecting;
      if(vis&&!was){clock.getDelta();if(!raf)frame()}
    }),{threshold:.02}).observe(cv);
    __on(document, 'visibilitychange',()=>{
      if(!document.hidden&&vis&&!raf){clock.getDelta();frame()}
    });
    frame();
  }
})();

/* ── Scene D · Barge-in theater (interruption) ── */
(function(){
  const cv=document.getElementById('bargeGl');if(!cv)return;
  let renderer;try{renderer=makeRenderer(cv)}catch(e){return}
  const scene=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(46,3.5,.1,40);
  cam.position.set(0,.5,10.8);

  const gc=document.createElement('canvas');gc.width=gc.height=128;
  const gx=gc.getContext('2d');
  const gr=gx.createRadialGradient(64,64,0,64,64,64);
  gr.addColorStop(0,'rgba(233,228,218,.5)');gr.addColorStop(.4,'rgba(233,228,218,.12)');gr.addColorStop(1,'rgba(233,228,218,0)');
  gx.fillStyle=gr;gx.fillRect(0,0,128,128);
  const glowTex=new THREE.CanvasTexture(gc);
  function nodeGlow(x,scale,op){
    const s=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex,transparent:true,depthWrite:false,opacity:op}));
    s.position.x=x;s.scale.setScalar(scale);scene.add(s);return s;
  }
  const gHuman=nodeGlow(-6.7,1.5,.75),gAgent=nodeGlow(6.7,1.7,.9);

  const NP=210,SPAN=13.2,DX=SPAN/(NP-1);
  function makeRibbon(color,size,op){
    const g=new THREE.BufferGeometry();
    const arr=new Float32Array(NP*3);
    g.setAttribute('position',new THREE.BufferAttribute(arr,3));
    const pts=new THREE.Points(g,new THREE.PointsMaterial({color,size,sizeAttenuation:true,transparent:true,opacity:op,depthWrite:false}));
    scene.add(pts);
    return {g,arr,hist:new Float32Array(NP),headX:0,amp:.6,frozen:false,alpha:op};
  }
  const human=makeRibbon(STONE,.085,.85),agent=makeRibbon(PEARL,.1,.95);

  const flash=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex,transparent:true,depthWrite:false,opacity:0}));
  flash.scale.setScalar(.1);scene.add(flash);

  let phase='speaking',phaseT=0,timers=[];
  const cap=document.getElementById('bargeCap'),st=document.getElementById('bargeState');
  function setCap(c,s){if(cap)cap.textContent=c;if(st)st.textContent=s}
  function clearTimers(){timers.forEach(clearTimeout);timers=[]}
  function later(fn,ms){timers.push(__to(fn,ms))}

  function barge(){
    clearTimers();
    phase='surge';phaseT=perfNow();
    human.frozen=false;
    setCap('Caller barges in —','Sarathi stops instantly · 180 ms');
    later(()=>{phase='absorb';setCap('Absorbing: “actually, move it to Friday.”','Understanding the new instruction…')},1100);
    later(()=>{phase='resume';agent.frozen=false;setCap('Resumes mid-thought — nothing lost.','Turn continued · context intact')},2400);
    later(()=>{if(phase==='resume'){phase='speaking';setCap('Sarathi is speaking…','Live turn · response 240 ms')}},5600);
  }
  function perfNow(){return performance.now()}

  const clock=new THREE.Clock();
  let emitAcc=0;
  function writeRibbon(rb,dir,t){
    for(let i=0;i<NP;i++){
      const y=rb.hist[(NP+ (headIdx[dir>0?0:1]) -i)%NP];
      rb.arr[i*3]=rb.headX-dir*i*DX;
      rb.arr[i*3+1]=y;
      rb.arr[i*3+2]=Math.sin(i*.24+t*.9)*.05*i/NP;
    }
    rb.g.attributes.position.needsUpdate=true;
  }
  const headIdx=[0,0];
  function size(){
    const w=cv.clientWidth||1060,h=cv.clientHeight||300;
    renderer.setSize(w,h,false);cam.aspect=w/h;cam.updateProjectionMatrix();
  }
  size();__on(window, 'resize',size);
  let vis=true,raf=null;
  function frame(){
    const dt=Math.min(clock.getDelta(),.05),t=clock.elapsedTime;
    emitAcc+=dt*90;
    const steps=Math.floor(emitAcc);emitAcc-=steps;
    for(let s=0;s<steps;s++){
      headIdx[0]=(headIdx[0]+1)%NP;
      headIdx[1]=(headIdx[1]+1)%NP;
      const surge=phase==='surge';
      human.hist[headIdx[0]]=Math.sin(perfNow()*.011)* .5*(surge?1.5:1)+Math.sin(perfNow()*.004)*.22*(surge?1.6:1);
      if(agent.frozen){agent.hist[headIdx[1]]=agent.hist[(headIdx[1]+NP-1)%NP]*.86}
      else{agent.hist[headIdx[1]]=Math.sin(perfNow()*.007)*.62+Math.sin(perfNow()*.0027)*.28}
    }
    const collide=human.headX>=-.45&&human.headX<=.45;
    human.headX+=dt*(phase==='surge'?9:2.6);
    if(human.headX>6.6){human.headX=-6.6;human.hist.fill(0)}
    agent.headX-=dt*(agent.frozen?0:(phase==='resume'?2.2:2.6));
    if(agent.headX<-6.6){agent.headX=6.6;agent.hist.fill(0)}
    if(phase==='surge'&&collide&&!agent.frozen){
      agent.frozen=true;flash.position.set(human.headX,0,0);
      flash.material.opacity=.95;
    }
    flash.material.opacity*= .92;
    flash.scale.setScalar(.4+(1-flash.material.opacity)*2.4);
    writeRibbon(human,1,t);writeRibbon(agent,-1,t);
    gHuman.material.opacity=.6+Math.sin(t*3.1)*.15;
    gAgent.material.opacity=agent.frozen?.3:.75+Math.sin(t*2.6)*.15;
    cam.position.x+=(mx*.4-cam.position.x)*.04;
    cam.position.y+=((.5-my*.3)-cam.position.y)*.04;
    cam.lookAt(0,0,0);
    renderer.render(scene,cam);
    raf=(vis&&!document.hidden)?__raf(frame):null;
  }
  const bb=document.getElementById('bargeBtn');
  if(bb)__on(bb, 'click',barge);
  if(RM){
    for(let i=0;i<NP;i++){
      human.arr[i*3]=-6.6+i*DX;human.arr[i*3+1]=Math.sin(i*.3)*.4;
      agent.arr[i*3]=6.6-i*DX;agent.arr[i*3+1]=Math.sin(i*.27)*.5;
    }
    human.g.attributes.position.needsUpdate=true;agent.g.attributes.position.needsUpdate=true;
    renderer.render(scene,cam);
  }else{
    new IntersectionObserver((es,ob)=>es.forEach(e=>{
      const was=!!raf;vis=e.isIntersecting;
      if(vis&&!was){clock.getDelta();if(!raf)frame()}
      if(vis&&!ob._ran){ob._ran=true;__to(barge,900)}
    }),{threshold:.45}).observe(cv);
    __on(document, 'visibilitychange',()=>{
      if(!document.hidden&&vis&&!raf){clock.getDelta();frame()}
    });
    frame();
  }
})();

/* ── Scene E · Language field (roadmap tie-in) ── */
(function(){
  const cv=document.getElementById('langGl');if(!cv)return;
  let renderer;try{renderer=makeRenderer(cv)}catch(e){return}
  const scene=new THREE.Scene();
  const cam=new THREE.PerspectiveCamera(42,2.6,.1,40);
  cam.position.set(0,1.6,7.6);cam.lookAt(0,0,0);
  const tilt=new THREE.Group();tilt.rotation.x=-.52;scene.add(tilt);
  const spin=new THREE.Group();tilt.add(spin);

  const DN=850,dp=new Float32Array(DN*3);
  for(let i=0;i<DN;i++){
    const a=Math.random()*6.283,r=1.15+Math.pow(Math.random(),.7)*2.05;
    dp[i*3]=Math.cos(a)*r;dp[i*3+1]=(Math.random()-.5)*.16;dp[i*3+2]=Math.sin(a)*r;
  }
  const dg=new THREE.BufferGeometry();
  dg.setAttribute('position',new THREE.BufferAttribute(dp,3));
  spin.add(new THREE.Points(dg,new THREE.PointsMaterial({color:STONE,size:.03,sizeAttenuation:true,transparent:true,opacity:.5,depthWrite:false})));

  function label(text,live){
    const cw=384,ch=88,c=document.createElement('canvas');c.width=cw;c.height=ch;
    const x=c.getContext('2d');
    x.font=(live?'600 ':'500 ')+'40px "DM Sans","Nirmala UI","Segoe UI",sans-serif';
    x.textAlign='center';x.textBaseline='middle';
    x.fillStyle=live?'rgba(233,228,218,.96)':'rgba(163,154,142,.78)';
    x.fillText(text,cw/2,ch/2);
    const tx=new THREE.CanvasTexture(c);
    const s=new THREE.Sprite(new THREE.SpriteMaterial({map:tx,transparent:true,depthWrite:false}));
    s.scale.set(1.55,.355,1);return s;
  }
  const LANGS=[
    {t:'English',r:1.35,a:0,live:true},
    {t:'తెలుగు',r:2.1,a:2.3},
    {t:'తెలుగు + English',r:2.5,a:4.1},
    {t:'हिन्दी',r:2.85,a:1.15},
    {t:'தமிழ்',r:2.65,a:5.2},
    {t:'ಕನ್ನಡ',r:3.0,a:3.3}];
  LANGS.forEach(L=>{
    const x=Math.cos(L.a)*L.r,z=Math.sin(L.a)*L.r;
    const dot=new THREE.Points(
      new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(new Float32Array([x,0,z]),3)),
      new THREE.PointsMaterial({color:L.live?PEARL:STONE,size:L.live?.13:.09,sizeAttenuation:true,transparent:true,opacity:L.live?1:.85,depthWrite:false}));
    spin.add(dot);
    const lb=label(L.t,L.live);lb.position.set(x,.3,z);spin.add(lb);
    if(L.live){
      const RN=72,rp=new Float32Array(RN*3);
      for(let i=0;i<RN;i++){const a=i/RN*6.283;rp[i*3]=Math.cos(a)*L.r;rp[i*3+2]=Math.sin(a)*L.r}
      const rg=new THREE.BufferGeometry();rg.setAttribute('position',new THREE.BufferAttribute(rp,3));
      L.ringMat=new THREE.PointsMaterial({color:PEARL,size:.035,sizeAttenuation:true,transparent:true,opacity:.4,depthWrite:false});
      spin.add(new THREE.Points(rg,L.ringMat));
    }
  });

  const clock=new THREE.Clock();
  function size(){
    const w=cv.clientWidth||880,h=cv.clientHeight||340;
    renderer.setSize(w,h,false);cam.aspect=w/h;cam.updateProjectionMatrix();
  }
  size();__on(window, 'resize',size);
  let vis=true,raf=null;
  function frame(){
    const t=clock.getElapsedTime();
    spin.rotation.y=t*.14;
    dg.attributes.position.needsUpdate=false;
    LANGS.forEach(L=>{if(L.ringMat)L.ringMat.opacity=.26+.18*Math.sin(t*2.3)});
    cam.position.x+=(mx*.45-cam.position.x)*.04;
    cam.position.y+=((1.6-my*.3)-cam.position.y)*.04;
    cam.lookAt(0,-.1,0);
    renderer.render(scene,cam);
    raf=(vis&&!document.hidden)?__raf(frame):null;
  }
  if(RM){spin.rotation.y=1.2;renderer.render(scene,cam)}
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
    document.body.classList.remove('custom-cursor');
    document.querySelectorAll('.cursor-dot,.cursor-ring').forEach((el) => el.remove());
  };
}
