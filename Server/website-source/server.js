let ws, mediaSource=null, sourceBuffer=null, hasAudio=false;
const queue=[];
const el=id=>document.getElementById(id);

function status(t,c){const s=el('statusText');s.innerText=t;s.style.color=c||'#888';}
function codecStr(){return hasAudio?'video/mp4; codecs="avc1.42E01F, mp4a.40.2"':'video/mp4; codecs="avc1.42E01F"';}
function updateSoundUI(){
  const btn=el('soundBtn'), v=el('videoPlayer');
  if(!hasAudio){btn.style.display='none';return;}
  btn.style.display='inline-block';
  btn.innerText=v.muted?'🔇 Enable Sound':'🔊 Sound On';
}
function toggleSound(){
  const v=el('videoPlayer');
  v.muted=!v.muted;
  if(!v.muted)v.play().catch(e=>console.warn('play:',e));
  updateSoundUI();
}
function hookPlaying(){
  const v=el('videoPlayer');
  v.addEventListener('playing',()=>{
    if(hasAudio&&v.muted){v.muted=false;updateSoundUI();}
  });
}
function pump(){
  if(!sourceBuffer||sourceBuffer.updating||!queue.length)return;
  try{sourceBuffer.appendBuffer(queue.shift());}
  catch(e){
    console.error('appendBuffer:',e);
    if(e.name==='QuotaExceededError'){
      try{const b=sourceBuffer.buffered;if(b.length)sourceBuffer.remove(0,b.end(b.length-1)-2);}catch(_){}
    }
  }
}
function onSourceOpen(){
  try{sourceBuffer=mediaSource.addSourceBuffer(codecStr());}
  catch(e){status('Codec error: '+e,'#ff5252');return;}
  sourceBuffer.addEventListener('updateend',()=>{
    try{
      const b=sourceBuffer.buffered;
      if(b.length){
        const end=b.end(b.length-1);
        const v=el('videoPlayer');
        if(end-v.currentTime>3)v.currentTime=end-0.5;
        if(end-b.start(0)>10)sourceBuffer.remove(b.start(0),end-10);
      }
    }catch(e){}
    pump();
  });
  sourceBuffer.addEventListener('error',()=>status('SourceBuffer error','#ff5252'));
  status(hasAudio?'🟢 Playing (with audio)':'🟢 Playing (no audio)','#4caf50');
  updateSoundUI();
  pump();
}
function attachMedia(){
  const v=el('videoPlayer');
  mediaSource=new MediaSource();
  v.src=URL.createObjectURL(mediaSource);
  mediaSource.addEventListener('sourceopen',onSourceOpen);
}
function resetPlayer(){
  queue.length=0;sourceBuffer=null;
  if(mediaSource&&mediaSource.readyState==='open'){try{mediaSource.endOfStream();}catch(e){}}
  attachMedia();
  status('🔄 Stream reset, waiting for keyframe...','#ffb74d');
}
function switchBroadcaster(){
  const sel=el('broadcasterSelect');
  const bcId=sel.value;
  if(!bcId||!ws||ws.readyState!==1)return;
  ws.send(JSON.stringify({type:'switch_broadcaster',broadcaster_id:bcId}));
  // Full reset
  resetPlayer();
  el('broadcasterBox').style.display='none';
  el('streamBox').style.display='block';
}
function exitToBroadcasters(){
  el('streamBox').style.display='none';
  el('broadcasterBox').style.display='block';
  status('Select broadcaster','#ffb74d');
  if(mediaSource&&mediaSource.readyState==='open'){
    try{mediaSource.endOfStream();}catch(e){}
  }
  queue.length=0;sourceBuffer=null;mediaSource=null;
  if(ws&&ws.readyState===1){
    // Ask server for broadcaster list again
    ws.send(JSON.stringify({type:'switch_broadcaster',broadcaster_id:''}));
  }
}
function sendQuality(){
  const[w,h,f]=el('qualitySel').value.split(',').map(Number);
  if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'quality',quality:{width:w,height:h,fps:f}}));
}
function sendAudio(){
  if(ws&&ws.readyState===1)ws.send(JSON.stringify({type:'audio_source',source:el('audioSel').value}));
}
function connect(){
  const user=el('username').value.trim(),pass=el('password').value.trim();
  ws=new WebSocket(`ws://${window.location.hostname}:8765/ws/view?u=${encodeURIComponent(user)}&p=${encodeURIComponent(pass)}`);
  ws.binaryType='arraybuffer';
  ws.onopen=()=>{
    el('loginBox').style.display='none';
    el('broadcasterBox').style.display='block';
    status('🟢 Connected...','#4caf50');
  };
  ws.onmessage=(e)=>{
    if(typeof e.data==='string'){
      try{
        const cmd=JSON.parse(e.data);
        if(cmd.type==='stream_reset'){hasAudio=!!cmd.audio;resetPlayer();updateSoundUI();el('streamBox').style.display='block';hookPlaying();attachMedia();}
        else if(cmd.type==='stream_info'){
          const a=!!cmd.audio;
          if(a!==hasAudio&&sourceBuffer){hasAudio=a;resetPlayer();}
          else hasAudio=a;
          updateSoundUI();
        }
        else if(cmd.type==='stream_end'){status('⚠️ Вещатель отключился, жду переподключения...','#ffb74d');}
        else if(cmd.type==='broadcaster_list'){
          const list=cmd.broadcasters||[];
          const sel=el('broadcasterSelect');
          sel.innerHTML='<option value="">-- Select broadcaster --</option>';
          list.forEach(b=>{
            const opt=document.createElement('option');
            opt.value=b.id;
            opt.text=b.name||b.id;
            sel.appendChild(opt);
          });
          el('broadcasterBox').style.display='block';
        }
        else if(cmd.type==='quality_update'&&cmd.quality){
          const val=`${cmd.quality.width},${cmd.quality.height},${cmd.quality.fps}`;
          const s=el('qualitySel');if([...s.options].some(o=>o.value===val))s.value=val;
        }
      }catch(_){}
      return;
    }
    queue.push(new Uint8Array(e.data));
    pump();
  };
  ws.onclose=(e)=>{
    status('Disconnected','#ff5252');
    if(e.code===4001){
      el('errorMsg').style.display='block';
      el('streamBox').style.display='none';
      el('broadcasterBox').style.display='none';
      el('loginBox').style.display='block';
    }
  };
}