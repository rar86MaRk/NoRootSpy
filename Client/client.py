import asyncio
import json
import os
import platform
import signal
import struct
import subprocess
import sys
import threading
import time
import traceback
from collections import deque
from contextlib import ExitStack

import av
import cv2
import mss
import numpy as np
import websockets

sd = None
try:
    import sounddevice as sd
except Exception as e:
    print(f"[AUDIO][DIAG] Failed to import sounddevice: {type(e).__name__}: {e}")
    print(f"[AUDIO][DIAG] Interpreter: {sys.executable} ({struct.calcsize('P') * 8}-bit)")

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
# FEATURE FLAGS
# ======================================================================
ENABLE_SCREEN = True   # Screen capture
ENABLE_WEBCAM = True   # Webcam (overlay on screen or main source)
ENABLE_AUDIO  = True   # Sound
# ======================================================================

SERVER_IP = "IP_YOUR_SERVER"
PORT = 8765
BROADCAST_TOKEN = "super_token_123"
SERVER_URI = f"ws://{SERVER_IP}:{PORT}/ws/broadcast?t={BROADCAST_TOKEN}"

TARGET_WIDTH = 1280
TARGET_HEIGHT = 720
TARGET_FPS = 30
AUDIO_SOURCE = "system"   # "system" | "mic" | "off"

SEND_QUEUE_MAX = 8        # fragment buffer before sending
RECONNECT_DELAY = 3.0     # pause before reconnecting, seconds

container_ref = None
stream_ref = None
audio_stream_ref = None
sink_global = None
sd_stream = None
audio_enabled = False
need_reinit = False
pending_audio_restart = False
video_pts = 0
audio_pts = 0
loop_start = 0.0
first_audio_packet = False
audio_queue = deque()
audio_acc = np.empty((0, 2), dtype=np.float32)

cam_lock = threading.Lock()
cam_frame = None
cam_running = False


class BoxSink:
    def __init__(self):
        self.chunks = deque()
        self._buf = bytearray()

    def write(self, data):
        self._buf += data
        while len(self._buf) >= 8:
            size = int.from_bytes(self._buf[0:4], "big")
            if size < 8:
                del self._buf[0:4]
                continue
            if len(self._buf) < size:
                break
            self.chunks.append(bytes(self._buf[:size]))
            del self._buf[:size]
        return len(data)

    def flush(self): pass
    def close(self): pass


def open_webcam():
    backend = cv2.CAP_V4L2 if platform.system() == "Linux" else cv2.CAP_DSHOW
    cap = cv2.VideoCapture(0, backend)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if cap.isOpened():
        return cap
    cap.release()
    return None


def camera_reader(cap):
    global cam_frame, cam_running
    cam_running = True
    while cam_running:
        ret, f = cap.read()
        if ret:
            with cam_lock:
                cam_frame = f
        else:
            time.sleep(0.03)


def fit_to_size(img, w, h):
    ih, iw = img.shape[:2]
    scale = min(w / iw, h / ih)
    nw, nh = max(2, int(iw * scale)), max(2, int(ih * scale))
    resized = cv2.resize(img, (nw, nh))
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    x, y = (w - nw) // 2, (h - nh) // 2
    canvas[y:y+nh, x:x+nw] = resized
    return canvas


def pick_audio_device(source):
    if sd is None or source == "off":
        return None, ""
    keywords = (
        ["microphone", "mic"]
        if source == "mic"
        else ["stereo mix", "loopback", "system", "vad", "virtual",
              "what u hear", "wave out mix", "mixer"]
    )
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            name = d.get("name", "").lower()
            if any(k in name for k in keywords):
                return i, d.get("name", "")
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            return i, d.get("name", "")
    return None, ""


def audio_callback(indata, frames, time_info, status):
    audio_queue.append(indata.copy())


def stop_audio():
    global sd_stream, audio_enabled
    if sd_stream is not None:
        try:
            sd_stream.stop(); sd_stream.close()
        except Exception:
            pass
        sd_stream = None
    audio_enabled = False


def start_audio():
    global sd_stream, audio_enabled
    stop_audio()
    if sd is None:
        print("[AUDIO] sounddevice unavailable — sound disabled.")
        return
    dev_idx, dev_name = pick_audio_device(AUDIO_SOURCE)
    if dev_idx is None:
        print(f"[AUDIO] No device for '{AUDIO_SOURCE}' — sound disabled.")
        return
    try:
        sd_stream = sd.InputStream(samplerate=44100, channels=2, dtype="float32",
                                   blocksize=1024, device=dev_idx,
                                   callback=audio_callback)
        sd_stream.start()
        audio_enabled = True
        print(f"[AUDIO] Capture: {dev_idx} ({dev_name}) [{AUDIO_SOURCE}]")
    except Exception as e:
        print(f"[AUDIO] Start error: {type(e).__name__}: {e} — sound disabled.")
        stop_audio()


def build_container():
    global container_ref, stream_ref, audio_stream_ref, sink_global
    global video_pts, audio_pts, loop_start, audio_acc, first_audio_packet
    if container_ref is not None:
        try:
            container_ref.close()
        except Exception:
            pass
    sink_global = BoxSink()
    container_ref = av.open(sink_global, mode="w", format="mp4",
                            container_options={"movflags": "frag_keyframe+empty_moov+default_base_moof"})
    stream_ref = container_ref.add_stream("libx264", rate=TARGET_FPS)
    stream_ref.width = TARGET_WIDTH
    stream_ref.height = TARGET_HEIGHT
    stream_ref.pix_fmt = "yuv420p"
    stream_ref.gop_size = max(1, TARGET_FPS)
    stream_ref.options = {"preset": "ultrafast", "tune": "zerolatency",
                          "profile": "baseline", "level": "3.1"}
    if audio_enabled:
        audio_stream_ref = container_ref.add_stream("aac", rate=44100)
        audio_stream_ref.sample_rate = 44100
        audio_stream_ref.layout = "stereo"
    else:
        audio_stream_ref = None
    video_pts = 0
    audio_pts = 0
    loop_start = time.perf_counter()
    audio_queue.clear()
    audio_acc = np.empty((0, 2), dtype=np.float32)
    first_audio_packet = False
    print(f"[RESTART] Stream rebuilt: {TARGET_WIDTH}x{TARGET_HEIGHT}@{TARGET_FPS}, "
          f"audio={'on' if audio_enabled else 'off'}")


async def cmd_listener(ws):
    global TARGET_WIDTH, TARGET_HEIGHT, TARGET_FPS, AUDIO_SOURCE
    global need_reinit, pending_audio_restart
    try:
        async for msg in ws:
            if isinstance(msg, str):
                try:
                    cmd = json.loads(msg)
                    if cmd.get("type") == "quality_change":
                        q = cmd.get("quality", {})
                        nw = int(q.get("width", TARGET_WIDTH))
                        nh = int(q.get("height", TARGET_HEIGHT))
                        nf = int(q.get("fps", TARGET_FPS))
                        if (nw, nh, nf) != (TARGET_WIDTH, TARGET_HEIGHT, TARGET_FPS):
                            TARGET_WIDTH, TARGET_HEIGHT, TARGET_FPS = nw, nh, nf
                            need_reinit = True
                            print(f"[CMD] Quality: {TARGET_WIDTH}x{TARGET_HEIGHT}@{TARGET_FPS}")
                    elif cmd.get("type") == "audio_change":
                        if not ENABLE_AUDIO:
                            print("[CMD] Audio source change requested but ENABLE_AUDIO=False — ignoring.")
                            continue
                        src = cmd.get("source", AUDIO_SOURCE)
                        if src != AUDIO_SOURCE:
                            AUDIO_SOURCE = src
                            pending_audio_restart = True
                            print(f"[CMD] Audio source: {AUDIO_SOURCE}")
                except Exception:
                    pass
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def sender_task(ws, send_q):
    """The only place where ws.send() is called.
    No wait_for/cancellation: cancelling send mid-write broke the connection."""
    while True:
        box = await send_q.get()
        await ws.send(box)


async def run_session():
    global need_reinit, pending_audio_restart
    global video_pts, audio_pts, loop_start, audio_acc, first_audio_packet

    async with websockets.connect(SERVER_URI, max_size=16*1024*1024,
                                  compression=None, ping_interval=20,
                                  ping_timeout=20, close_timeout=5) as ws:
        print("[OK] Connected, streaming started.")
        await ws.send(json.dumps({"type": "stream_reset", "audio": audio_enabled}))

        send_q = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
        listener = asyncio.create_task(cmd_listener(ws))
        sender = asyncio.create_task(sender_task(ws, send_q))
        try:
            with ExitStack() as stack:
                sct = stack.enter_context(mss.MSS()) if ENABLE_SCREEN else None
                monitor = sct.monitors[1] if sct is not None else None

                while True:
                    t0 = time.perf_counter()

                    if pending_audio_restart:
                        pending_audio_restart = False
                        was_enabled = audio_enabled
                        start_audio()
                        if was_enabled != audio_enabled:
                            need_reinit = True

                    if need_reinit:
                        need_reinit = False
                        try:
                            await ws.send(json.dumps({"type": "stream_reset",
                                                      "audio": audio_enabled}))
                        except Exception:
                            pass
                        build_container()

                    # --- frame creation ---
                    if sct is not None:
                        img = np.array(sct.grab(monitor))
                        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        frame = cv2.resize(frame, (TARGET_WIDTH, TARGET_HEIGHT))
                        if ENABLE_WEBCAM:
                            with cam_lock:
                                cf = cam_frame
                            if cf is not None:
                                cam = cv2.resize(cf, (320, 240))
                                h, w = frame.shape[:2]
                                if h > 250 and w > 330:
                                    frame[h-250:h-10, w-330:w-10] = cam
                    else:
                        with cam_lock:
                            cf = cam_frame
                        if cf is None:
                            frame = np.zeros((TARGET_HEIGHT, TARGET_WIDTH, 3), dtype=np.uint8)
                        else:
                            frame = fit_to_size(cf, TARGET_WIDTH, TARGET_HEIGHT)

                    elapsed = time.perf_counter() - loop_start
                    target_pts = int(elapsed * TARGET_FPS)
                    if target_pts <= video_pts:
                        target_pts = video_pts + 1
                    video_pts = target_pts

                    vframe = av.VideoFrame.from_ndarray(frame, format="bgr24")
                    vframe.pts = video_pts
                    for packet in stream_ref.encode(vframe):
                        container_ref.mux(packet)

                    # --- audio: AAC frames exactly 1024 samples ---
                    if audio_stream_ref is not None:
                        if audio_queue:
                            blocks = []
                            if len(audio_acc):
                                blocks.append(audio_acc)
                            while audio_queue:
                                blocks.append(audio_queue.popleft())
                            audio_acc = np.concatenate(blocks)
                        max_samples = 22050
                        if len(audio_acc) > max_samples:
                            dropped = len(audio_acc) - max_samples
                            audio_acc = audio_acc[dropped:]
                            audio_pts += dropped
                        while len(audio_acc) >= 1024:
                            chunk = audio_acc[:1024]
                            audio_acc = audio_acc[1024:]
                            try:
                                aframe = av.AudioFrame.from_ndarray(
                                    np.ascontiguousarray(chunk.T), format="fltp", layout="stereo")
                                aframe.sample_rate = 44100
                                aframe.pts = audio_pts
                                audio_pts += 1024
                                for apacket in audio_stream_ref.encode(aframe):
                                    container_ref.mux(apacket)
                                    if not first_audio_packet:
                                        first_audio_packet = True
                                        print("[AUDIO] First AAC packet encoded and sent.")
                            except Exception as e:
                                print(f"[AUDIO][ENCODE] {type(e).__name__}: {e}")
                    else:
                        if audio_queue:
                            audio_queue.clear()

                    # --- fragments to send queue (drop oldest) ---
                    while sink_global.chunks:
                        box = sink_global.chunks.popleft()
                        if box[4:8] == b"moof" and sink_global.chunks and sink_global.chunks[0][4:8] == b"mdat":
                            box += sink_global.chunks.popleft()
                        if send_q.full():
                            try:
                                send_q.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        send_q.put_nowait(box)

                    dt = time.perf_counter() - t0
                    await asyncio.sleep(max(0.0, 1.0 / TARGET_FPS - dt))
        finally:
            listener.cancel()
            sender.cancel()


async def main():
    global audio_enabled, cam_running

    print("[CFG] Feature flags:")
    print(f"[CFG]   Screen: {'on' if ENABLE_SCREEN else 'off'}")
    print(f"[CFG]   Webcam: {'on' if ENABLE_WEBCAM else 'off'}")
    print(f"[CFG]   Audio : {'on' if ENABLE_AUDIO else 'off'}")

    if not ENABLE_SCREEN and not ENABLE_WEBCAM:
        print("[FATAL] ENABLE_SCREEN and ENABLE_WEBCAM both disabled — nothing to stream.")
        return

    cap = None
    if ENABLE_WEBCAM:
        cap = open_webcam()
        print("Webcam OK" if cap else "Webcam not found — working without it.")
        if cap is not None:
            threading.Thread(target=camera_reader, args=(cap,), daemon=True).start()
        elif not ENABLE_SCREEN:
            print("[FATAL] ENABLE_SCREEN=False and webcam unavailable — nothing to stream.")
            return
    else:
        print("[CFG] Webcam disabled (ENABLE_WEBCAM=False).")

    if ENABLE_AUDIO:
        start_audio()
    else:
        print("[CFG] Audio disabled (ENABLE_AUDIO=False) — sounddevice not used.")
        audio_enabled = False

    build_container()

    while True:
        try:
            await run_session()
            break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[NET] Session dropped: {type(e).__name__}: {e}")
            print(f"[NET] Reconnecting in {RECONNECT_DELAY} seconds...")
            await asyncio.sleep(RECONNECT_DELAY)
            build_container()

    cam_running = False
    stop_audio()
    if cap is not None:
        cap.release()


if __name__ == "__main__":
    stop_if_requested("client.pid")
    daemonize_if_requested("client.pid")
    signal.signal(signal.SIGTERM, _sigterm_handler)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Shutdown.")
