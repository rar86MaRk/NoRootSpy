import asyncio
import json
import os
import platform
import signal
import subprocess
import sys
import threading
import websockets
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs

# ======================================================================
# BACKGROUND MODE: -fon (run in background) and -stop (stop via PID file)
# ======================================================================
BG_FLAG = "-fon"
STOP_FLAG = "-stop"

def _here(name):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

def _sigterm_handler(signum, frame):
    print("\n[BG] Received SIGTERM — graceful shutdown.")
    raise KeyboardInterrupt

def stop_if_requested(pid_name):
    """Flag -stop: read PID from file and send SIGTERM to process."""
    if STOP_FLAG not in sys.argv[1:]:
        return
    pid_path = _here(pid_name)
    try:
        with open(pid_path) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"[BG] Process PID {pid} terminated via SIGTERM.")
    except FileNotFoundError:
        print(f"[BG] PID file {pid_name} not found — process not running in background?")
    except ProcessLookupError:
        print(f"[BG] PID from {pid_name} no longer exists.")
    except ValueError:
        print(f"[BG] Failed to read PID from {pid_name}.")
    sys.exit(0)

def daemonize_if_requested(pid_name):
    """Flag -fon: restart script as detached process.
    Output (stdout/stderr) discarded to DEVNULL — NO log files created.
    Child PID saved to pid_name (needed for -stop). Parent exits immediately."""
    if BG_FLAG not in sys.argv[1:]:
        return
    script = os.path.abspath(__file__)
    pid_path = _here(pid_name)
    # remove -fon from child args to avoid infinite restart loop
    args = [sys.executable, "-u", script] + [a for a in sys.argv[1:] if a != BG_FLAG]
    kwargs = {}
    if platform.system() == "Windows":
        CREATE_NO_WINDOW         = 0x08000000
        DETACHED_PROCESS         = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        kwargs["creationflags"] = (CREATE_NO_WINDOW | DETACHED_PROCESS |
                                   CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True   # setsid(): detach from terminal
    proc = subprocess.Popen(args,
                            stdout=subprocess.DEVNULL,   # <-- instead of log file
                            stderr=subprocess.DEVNULL,   # <-- instead of log file
                            stdin=subprocess.DEVNULL,
                            **kwargs)
    with open(pid_path, "w") as f:
        f.write(str(proc.pid))
    print(f"[BG] Launched in background: PID {proc.pid} (output discarded)")
    print(f"[BG] Stop: python {os.path.basename(script)} -stop   (or kill {proc.pid})")
    sys.exit(0)

# ======================================================================
# CONFIGURATION
# ======================================================================
HTTP_PORT = 8081
WS_PORT = 8765
ADMIN_USER = "admin"
ADMIN_PASS = "mysecretpassword"
BROADCAST_TOKEN = "super_token_123"

# Multiple broadcasters support: each gets unique ID based on IP
broadcasters = {}   # id -> {ws, init_segment, init_ready, stream_audio, current_quality, name}
viewers = {}        # ws -> {broadcaster_id: str, sync: bool}
viewer_sync = {}    # ws -> bool (legacy, kept for sync tracking)

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Live Video Stream</title>
<style>
body{font-family:Arial,sans-serif;background:#121212;color:#e0e0e0;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0}
.container{background:#1e1e1e;padding:2rem;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.4);text-align:center;width:90%;max-width:1280px}
video{width:100%;border-radius:8px;background:#000;margin-top:15px}
.status{margin-top:15px;color:#888;font-size:14px}
button{padding:8px 16px;background:#dc3545;color:#fff;border:none;border-radius:6px;cursor:pointer}
select{padding:8px;background:#2d2d2d;color:#fff;border:1px solid #333;border-radius:4px}
input{padding:10px;width:100%;margin:5px 0;background:#2d2d2d;color:#fff;border:1px solid #333;border-radius:4px;box-sizing:border-box}
.row{margin-top:12px;display:flex;gap:12px;justify-content:center;align-items:center;flex-wrap:wrap}
</style>
</head>
<body>
<div class="container" id="loginBox">
<h2>🔒 Authentication</h2>
<input type="text" id="username" placeholder="Username" value="admin">
<input type="password" id="password" placeholder="Password">
<button onclick="connect()" style="background:#007bff;width:100%;padding:12px;margin-top:10px;">Login</button>
<p id="errorMsg" style="color:#ff5252;display:none;">Invalid username or password</p>
</div>
<div class="container" id="streamBox" style="display:none;">
<h2>📹 Live Stream (H.264)</h2>
<p class="status" id="statusText">Waiting for video stream...</p>
<video id="videoPlayer" autoplay muted playsinline></video>
<div class="row">
  <button id="soundBtn" onclick="toggleSound()" style="background:#28a745;display:none;">🔇 Enable Sound</button>
  <label>Quality:
    <select id="qualitySel" onchange="sendQuality()">
      <option value="1280,720,30">1280x720@30</option>
      <option value="960,540,24">960x540@24</option>
      <option value="640,360,15">640x360@15</option>
    </select>
  </label>
  <label>Sound:
    <select id="audioSel" onchange="sendAudio()">
      <option value="system">System</option>
      <option value="mic">Microphone</option>
      <option value="off">Off</option>
    </select>
  </label>
  <button onclick="location.reload()">Exit</button>
</div>
</div>
</div>
<script>
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
    el('streamBox').style.display='block';
    status('🟢 Connected...','#4caf50');
    hookPlaying();
    attachMedia();
  };
  ws.onmessage=(e)=>{
    if(typeof e.data==='string'){
      try{
        const cmd=JSON.parse(e.data);
        if(cmd.type==='stream_reset'){hasAudio=!!cmd.audio;resetPlayer();updateSoundUI();}
        else if(cmd.type==='stream_info'){
          const a=!!cmd.audio;
          if(a!==hasAudio&&sourceBuffer){hasAudio=a;resetPlayer();}
          else hasAudio=a;
          updateSoundUI();
        }
        else if(cmd.type==='stream_end'){status('⚠️ Broadcaster disconnected, waiting for reconnection...','#ffb74d');}
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
      el('loginBox').style.display='block';
    }
  };
}
</script>
</body>
</html>
"""

class HTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        site_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "website-source")
        super().__init__(*args, directory=site_dir, **kwargs)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.path = "/server.html"
        return super().do_GET()

    def log_message(self, *a): pass

class ReuseAddrHTTPServer(HTTPServer):
    allow_reuse_address = True

def run_http_server():
    ReuseAddrHTTPServer(("0.0.0.0", HTTP_PORT), HTTPRequestHandler).serve_forever()

async def safe_send(viewer, data):
    try:
        await asyncio.wait_for(viewer.send(data), timeout=0.2)
    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
        pass

async def ws_handler(websocket):
    global init_ready, stream_audio, current_quality

    path = websocket.request.path if hasattr(websocket, 'request') else getattr(websocket, 'path', '/')
    query = parse_qs(path.split('?')[1]) if '?' in path else {}

    # --- BROADCASTER ---
    if path.startswith("/ws/broadcast"):
        if query.get("t", [""])[0] != BROADCAST_TOKEN:
            await websocket.close(4003, "Invalid token"); return
        print("📡 [Broadcaster] connected.")
        # Generate broadcaster ID from IP + random
        bc_id = f"bc_{len(broadcasters)}"
        try:
            client_host = websocket.remote_address[0]
            bc_id = f"bc_{client_host}_{len(broadcasters)}"
        except Exception:
            pass
        bc_name = f"{client_host} (ID: {bc_id})" if 'client_host' in locals() else f"BC_{bc_id}"
        broadcasters[bc_id] = {
            'ws': websocket,
            'init_segment': bytearray(),
            'init_ready': False,
            'stream_audio': False,
            'current_quality': {"width": 1280, "height": 720, "fps": 30},
            'name': bc_name,
            'chunks': bytearray()
        }
        try:
            await websocket.send(json.dumps({"type":"registered","id":bc_id,"name":bc_name}))
        except Exception:
            pass
        try:
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        cmd = json.loads(message)
                        if cmd.get("type") == "stream_reset":
                            # Find which broadcaster this websocket belongs to
                            bc_id = None
                            for k,v in broadcasters.items():
                                if v['ws'] == websocket:
                                    bc_id = k
                                    break
                            if bc_id and bc_id in broadcasters:
                                bc = broadcasters[bc_id]
                                bc['stream_audio'] = bool(cmd.get("audio", False))
                                bc['init_segment'] = bytearray()
                                bc['init_ready'] = False
                                print(f"🔄 stream_reset (audio={'on' if bc['stream_audio'] else 'off'}) from {bc['name']}")
                                for viewer_ws, viewer_info in viewers.items():
                                    if viewer_info.get('broadcaster_id') == bc_id:
                                        viewer_sync[viewer_ws] = False
                                        await safe_send(viewer_ws, json.dumps({"type":"stream_reset","audio":bc['stream_audio'],"broadcaster_id":bc_id}))
                        elif cmd.get("type") == "quality_change":
                            current_quality = cmd["quality"]
                            print(f"🎬 Quality changed: {current_quality}")
                            for v in list(viewers):
                                await safe_send(v, json.dumps({"type": "quality_update",
                                                                "quality": current_quality}))
                        elif cmd.get("type") == "skip":
                            for v in list(viewers):
                                viewer_sync[v] = False
                            await asyncio.gather(*(safe_send(v, json.dumps({"type": "skip_ack"}))
                                                   for v in list(viewers)))
                    except json.JSONDecodeError:
                        pass
                    continue

                # Find broadcaster for this websocket
                bc_id = None
                for k,v in broadcasters.items():
                    if v['ws'] == websocket:
                        bc_id = k
                        break
                if not bc_id or bc_id not in broadcasters:
                    continue
                bc = broadcasters[bc_id]
                if not isinstance(message, bytes) or len(message) < 8:
                    continue
                btype = message[4:8]
                if not bc['init_ready']:
                    if btype in (b"ftyp", b"moov"):
                        bc['init_segment'].extend(message)
                        if btype == b"moov":
                            bc['init_ready'] = True
                            print("🎬 Video header received (ftyp+moov).")
                            for viewer_ws, viewer_info in viewers.items():
                                if viewer_info.get('broadcaster_id') == bc_id:
                                    await safe_send(viewer_ws, bytes(bc['init_segment']))
                    continue
                targets = []
                for viewer_ws, viewer_info in viewers.items():
                    if viewer_info.get('broadcaster_id') == bc_id:
                        if not viewer_sync.get(viewer_ws, False):
                            if btype == b"moof":
                                viewer_sync[viewer_ws] = True
                                targets.append(viewer_ws)
                        else:
                            targets.append(viewer_ws)
                if targets:
                    await asyncio.gather(*(safe_send(v, message) for v in targets))
        except websockets.exceptions.ConnectionClosed:
            print("📡 [Broadcaster] disconnected.")
        finally:
            bc_id = None
            for k,v in list(broadcasters.items()):
                if v.get('ws') == websocket:
                    bc_id = k
                    break
            if bc_id:
                del broadcasters[bc_id]
            if not broadcasters:
                print("📡 No broadcasters remain.")
                for v in list(viewers):
                    await safe_send(v, json.dumps({"type": "stream_end"}))
        return

    # --- VIEWER ---
    if path.startswith("/ws/view"):
        user = query.get("u", [""])[0].strip()
        password = query.get("p", [""])[0].strip()
        if user != ADMIN_USER or password != ADMIN_PASS:
            await websocket.close(4001, "Unauthorized"); return

        viewers[websocket] = {"broadcaster_id": None, "sync": False}
        viewer_sync[websocket] = False
        print(f"👁️ [Viewer] connected. Viewers: {len(viewers)}")
        # Send broadcaster list
        bc_list = [{"id":k,"name":v['name']} for k,v in broadcasters.items()]
        await websocket.send(json.dumps({"type":"broadcaster_list","broadcasters":bc_list}))
        # Default: bind to first broadcaster if available
        if broadcasters:
            first_bc = list(broadcasters.keys())[0]
            viewers[websocket]["broadcaster_id"] = first_bc
            bc = broadcasters[first_bc]
            await websocket.send(json.dumps({"type":"stream_info","audio":bc['stream_audio']}))
            if bc['init_ready']:
                await websocket.send(bytes(bc['init_segment']))
        try:
            async for message in websocket:
                if isinstance(message, str):
                    try:
                        cmd = json.loads(message)
                        if cmd.get("type") == "quality":
                            quality = cmd["quality"]
                            print(f"👁️ Viewer requests quality: {quality}")
                            for b_info in broadcasters.values():
                                await safe_send(b_info['ws'], json.dumps({"type": "quality_change",
                                                                "quality": quality}))
                        elif cmd.get("type") == "switch_broadcaster":
                            target = cmd.get("broadcaster_id")
                            if target and target in broadcasters:
                                viewers[websocket]["broadcaster_id"] = target
                                bc = broadcasters[target]
                                await websocket.send(json.dumps({"type":"stream_reset","audio":bc['stream_audio'],"broadcaster_id":target}))
                                if bc['init_ready']:
                                    await websocket.send(bytes(bc['init_segment']))
                                bc_list = [{"id":k,"name":v['name']} for k,v in broadcasters.items()]
                                await websocket.send(json.dumps({"type":"broadcaster_list","broadcasters":bc_list}))
                        elif cmd.get("type") == "audio_source":
                            source = cmd.get("source", "system")
                            print(f"👁️ Viewer requests sound: {source}")
                            for b_info in broadcasters.values():
                                await safe_send(b_info['ws'], json.dumps({"type": "audio_change",
                                                                "source": source}))
                    except json.JSONDecodeError:
                        pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            viewers.pop(websocket, None)
            viewer_sync.pop(websocket, None)
            print(f"👁️ [Viewer] disconnected. Viewers: {len(viewers)}")
        return

    await websocket.close(4004, "Unknown path")

async def main():
    print(f"🚀 HTTP: http://0.0.0.0:{HTTP_PORT} | WS: ws://0.0.0.0:{WS_PORT}")
    print(f"👤 {ADMIN_USER} / {ADMIN_PASS} | token: {BROADCAST_TOKEN}")
    threading.Thread(target=run_http_server, daemon=True).start()
    async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT,
                                max_size=16*1024*1024, compression=None):
        await asyncio.Future()

if __name__ == "__main__":
    stop_if_requested("server.pid")
    daemonize_if_requested("server.pid")
    signal.signal(signal.SIGTERM, _sigterm_handler)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")
