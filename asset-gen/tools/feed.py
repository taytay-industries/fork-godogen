#!/usr/bin/env python3
"""Asset feed: a live page of everything generated for a project, as it happens.

    feed.py serve [--port 8765]                       # the page, plus a watcher on assets/ refs/ screenshots/
    feed.py run [--title T] [--prompt P] [--from F] [--out F] [--cost "30 Tripo cr"] -- tripo make ref.png ...
    feed.py add FILE... [--title T] [--prompt P] [--from F] [--cost C] [--at-mtime]
    feed.py note "text" [--file F...]
    feed.py mark FILE rejected|kept ["reason"]

Everything appends to .feed/events.jsonl at the project root; every file is snapshotted into .feed/blobs/ by
content hash, so overwritten and rejected versions stay viewable. `run` shows a pending card while the command
works, links it to any input files named on its command line, and records its outputs and cost (read from the
command's JSON). The watcher catches files that appear without an event. asset_gen.py and audio_prep.py log
themselves. Stdlib only; ffmpeg converts videos browsers can't play (.ogv, .avi, .mov) to MP4.
"""
import argparse
import fcntl
import hashlib
import json
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KINDS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif"},
    "model": {".glb"},
    "audio": {".mp3", ".wav", ".ogg", ".flac", ".m4a"},
    "video": {".mp4", ".webm", ".ogv", ".mov", ".avi"},
}
TRANSCODE = {".ogv", ".mov", ".avi"}
WATCH_DEFAULT = ["assets", "src/assets", "refs", "screenshots"]
SKIP_DIRS = {".git", ".godot", ".feed", "node_modules", "__pycache__", "bin", "obj"}
SEQUENCE_MIN = 24          # this many new images in one folder at once is a frame dump: log it as one sequence
MAX_BYTES = 300 << 20


def kind_of(path) -> str | None:
    ext = Path(path).suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), None)


def project_root() -> Path:
    if os.environ.get("FEED_ROOT"):
        return Path(os.environ["FEED_ROOT"]).resolve()
    here = Path.cwd().resolve()
    for d in [here, *here.parents]:
        if (d / ".feed").is_dir():
            return d
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, cwd=here)
        if top.returncode == 0:
            return Path(top.stdout.strip())
    except OSError:
        pass
    return here


ROOT = project_root()
FEED = ROOT / ".feed"
EVENTS = FEED / "events.jsonl"
BLOBS = FEED / "blobs"


def rel(path) -> str:
    p = Path(path).resolve()
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def emit(ev: dict) -> dict:
    ev.setdefault("id", uuid.uuid4().hex[:12])
    ev.setdefault("t", round(time.time(), 3))
    FEED.mkdir(exist_ok=True)
    gi = FEED / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")
    with open(EVENTS, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(ev) + "\n")
    return ev


def snapshot(path) -> dict | None:
    """Copy a file into the blob store by content hash; returns the file entry an event carries."""
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_BYTES or not kind_of(p):
        return None
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    ext = p.suffix.lower()
    name = h.hexdigest()[:16] + ext
    BLOBS.mkdir(parents=True, exist_ok=True)
    blob = BLOBS / name
    if not blob.exists():
        tmp = blob.with_suffix(ext + ".part")
        shutil.copyfile(p, tmp)
        tmp.rename(blob)
    entry = {"path": rel(p), "blob": name, "kind": kind_of(p), "bytes": p.stat().st_size}
    if ext in TRANSCODE:
        view = BLOBS / (h.hexdigest()[:16] + ".mp4")
        if not view.exists():
            tmp = BLOBS / (view.name + ".part.mp4")
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(blob), "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "23", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                                "-c:a", "aac", "-movflags", "+faststart", str(tmp)], capture_output=True)
            if r.returncode == 0:
                tmp.rename(view)
        if view.exists():
            entry["view"] = view.name
    return entry


def safe(fn, *a, **kw):
    """Logging must never break the tool that logs: failures go to stderr and return None."""
    if os.environ.get("FEED") == "0":
        return None
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        print(f"feed: {e}", file=sys.stderr)
        return None


# --- API for tools -------------------------------------------------------------------------------------------

def start(title: str, tool: str = "", prompt: str | None = None, sources=(), eta: float | None = None,
          cmd: str | None = None) -> str | None:
    """Log a pending job; returns its id. Skipped when a `feed.py run` wrapper already logs this process."""
    if os.environ.get("FEED_JOB"):
        return None
    def go():
        job = uuid.uuid4().hex[:12]
        srcs = [e for e in (snapshot(s) for s in sources if s) if e]
        emit({"type": "start", "job": job, "title": title, "tool": tool, "prompt": prompt, "from": srcs,
              "eta": eta, "cmd": cmd})
        return job
    return safe(go)


def done(job: str | None, files=(), cost: list | None = None, ok: bool = True, error: str | None = None,
         log: str | None = None, info: dict | None = None):
    if not job:
        return
    def go():
        entries = [e for e in (snapshot(f) for f in files if f) if e]
        emit({"type": "done", "job": job, "ok": ok, "files": entries, "cost": cost or [], "error": error,
              "log": log, "info": info})
    safe(go)


def parse_cost(s: str) -> list:
    m = re.match(r"\s*([\d.]+)\s*(.*)", s)
    return [{"n": float(m.group(1)), "unit": m.group(2).strip() or "¢"}] if m else []


# --- run: wrap any generator CLI -----------------------------------------------------------------------------

OUT_KEYS = ("path", "output", "output_path", "model_file", "saved_file", "file", "preview")


def outputs_from_json(text: str) -> tuple[list, dict]:
    """Output paths and the last JSON object from a command's stdout (tripo, elevenlabs, qwen-image...)."""
    files, last = [], {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        last = d
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in OUT_KEYS and isinstance(v, str):
                        files.append(v)
                    elif k == "files" and isinstance(v, list):
                        files += [f for f in v if isinstance(f, str)]
                    elif isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(x, list):
                stack += x
    return files, last


def cmd_run(a):
    argv = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not argv:
        sys.exit("feed run: nothing to run (put the command after --)")
    tool = Path(argv[0]).name
    if tool.startswith("python") and len(argv) > 1:
        tool = Path(argv[1]).name
    # Existing files on the command line are the job's inputs (a reference image, the clip being processed),
    # except the ones it is told to write.
    out_flags = {"-o", "--output", "--out"}
    outs_argv = {argv[i + 1] for i in range(len(argv) - 1) if argv[i] in out_flags}
    sources = list(a.sources or [])
    sources += [t for t in argv[1:] if t not in outs_argv and kind_of(t) and Path(t).is_file()]
    prompt = a.prompt
    if prompt is None:
        for flag in ("--prompt", "--text"):
            if flag in argv[:-1]:
                prompt = argv[argv.index(flag) + 1]
                break
    words = []                          # leading subcommands: "tripo make", "elevenlabs text-to-speech convert"
    for t in argv[1 + (tool != Path(argv[0]).name):]:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,24}", t) or len(words) == 2:
            break
        words.append(t)
    title = a.title or " ".join([tool, *words])
    t0 = time.time()
    job = safe(lambda: emit({"type": "start", "job": uuid.uuid4().hex[:12], "title": title, "tool": tool,
                             "prompt": prompt, "from": [e for e in (snapshot(s) for s in sources) if e],
                             "eta": a.eta, "cmd": shlex.join(argv)[:600]})["job"])

    env = dict(os.environ, FEED_JOB=job or "-")
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    out_buf, err_tail = [], []

    def pump(src, dst, keep):
        for line in iter(src.readline, b""):
            dst.buffer.write(line)
            dst.flush()
            keep.append(line.decode(errors="replace"))
            if keep is err_tail and len(err_tail) > 40:
                del err_tail[0]
    threads = [threading.Thread(target=pump, args=(proc.stdout, sys.stdout, out_buf)),
               threading.Thread(target=pump, args=(proc.stderr, sys.stderr, err_tail))]
    for t in threads:
        t.start()
    code = proc.wait()
    for t in threads:
        t.join()

    stdout = "".join(out_buf)
    files, info = outputs_from_json(stdout)
    files += list(a.out or [])
    if not files:
        files = [o for o in outs_argv if Path(o).is_file()]
    if not files and code == 0:        # last resort: anything under the watched folders written during the run
        for d in watch_dirs(None):
            for p in d.rglob("*"):
                if p.is_file() and kind_of(p) and p.stat().st_mtime >= t0 - 1:
                    files.append(str(p))
    cost = parse_cost(a.cost) if a.cost else []
    if not cost and isinstance(info, dict):
        if info.get("cost_cents"):
            cost = [{"n": info["cost_cents"], "unit": "¢"}]
        elif info.get("credits_consumed"):
            cost = [{"n": info["credits_consumed"], "unit": f"{tool.capitalize()} cr"}]
    ok = code == 0 and (not isinstance(info, dict) or info.get("ok", True) is not False)
    err = None
    if not ok:
        err = (isinstance(info, dict) and (info.get("error") and json.dumps(info["error"])[:600])) or \
              "".join(err_tail[-6:]).strip()[-600:] or f"exit {code}"
    log = ("".join(err_tail[-12:]) + ("\n" + stdout[-1500:] if stdout.strip() else "")).strip()[-3000:]
    done(job, files=list(dict.fromkeys(files)), cost=cost, ok=ok, error=err, log=log,
         info=info if isinstance(info, dict) else None)
    sys.exit(code)


def cmd_add(a):
    entries = [e for e in (snapshot(f) for f in a.files) if e]
    if not entries:
        sys.exit("feed add: no viewable files")
    ev = {"type": "file", "title": a.title, "prompt": a.prompt, "tool": a.tool, "files": entries,
          "from": [e for e in (snapshot(s) for s in a.sources or []) if e],
          "cost": parse_cost(a.cost) if a.cost else []}
    if a.at_mtime:
        ev["t"] = min(Path(f).stat().st_mtime for f in a.files)
    emit(ev)


def cmd_note(a):
    emit({"type": "note", "text": a.text, "files": [e for e in (snapshot(f) for f in a.file or []) if e]})


def cmd_mark(a):
    e = snapshot(a.file)
    emit({"type": "mark", "path": rel(a.file), "blob": e and e["blob"], "status": a.status, "reason": a.reason})


# --- serve: the page, the event stream, and the watcher ------------------------------------------------------

def watch_dirs(arg) -> list[Path]:
    return [ROOT / d for d in (arg or WATCH_DEFAULT) if (ROOT / d).is_dir()]


class Watcher(threading.Thread):
    """Polls the watched folders and logs files that changed without anyone logging them. New files wait until
    their size is stable, and while a job is running (its done event usually claims them) for up to 30 s."""

    def __init__(self, dirs, backfill: bool):
        super().__init__(daemon=True)
        self.dirs, self.backfill = dirs, backfill
        self.state_file = FEED / "seen.json"
        self.seen = json.loads(self.state_file.read_text()) if self.state_file.exists() else None
        self.known: dict[str, set] = {}   # blob -> paths already logged
        self.open_jobs: dict[str, float] = {}
        self.job_dirs: dict[str, tuple] = {}   # folder -> (job, finish time) of the latest job that wrote there
        self.offset = 0
        self.pending: dict[str, tuple] = {}

    def scan(self) -> dict:
        found = {}
        for d in self.dirs:
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames[:] = [n for n in dirnames if n not in SKIP_DIRS and not n.startswith(".")]
                # Engines unpack a GLB's textures next to it on import (car.glb -> car_Color_<id>.jpg): not new art.
                glbs = tuple(n[:-4] + "_" for n in filenames if n.endswith(".glb"))
                for n in filenames:
                    if kind_of(n) and not (glbs and kind_of(n) == "image" and n.startswith(glbs)):
                        p = os.path.join(dirpath, n)
                        try:
                            st = os.stat(p)
                        except OSError:
                            continue
                        found[rel(p)] = [st.st_mtime, st.st_size]
        return found

    def read_events(self):
        if not EVENTS.exists():
            return
        with open(EVENTS) as f:
            f.seek(self.offset)
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "start":
                    self.open_jobs[ev["job"]] = ev["t"]
                if ev.get("type") == "done":
                    self.open_jobs.pop(ev.get("job"), None)
                    for e in ev.get("files", []):
                        self.job_dirs[str(Path(e["path"]).parent)] = (ev["job"], ev["t"])
                for e in ev.get("files", []) + ev.get("from", []):
                    self.known.setdefault(e.get("blob"), set()).add(e["path"])
            self.offset = f.tell()

    def run(self):
        first = self.seen is None
        self.read_events()
        now = self.scan()
        if first and not self.backfill:
            self.seen = now
        elif first:
            self.seen = {}
        self.save()
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                print(f"watcher: {e}", file=sys.stderr)
            time.sleep(1.0)

    def save(self):
        self.state_file.write_text(json.dumps(self.seen))

    def tick(self):
        self.read_events()
        now = self.scan()
        changed = [p for p, st in now.items() if self.seen.get(p) != st]
        t = time.time()
        busy = any(t - s < 3600 for s in self.open_jobs.values())
        ready = []
        for p in changed:
            prev = self.pending.get(p)
            if not prev or prev[0] != now[p]:
                self.pending[p] = (now[p], t)
                continue
            if busy and t - prev[1] < 30:
                continue
            ready.append(p)
        for p in list(self.pending):
            if p not in now:
                del self.pending[p]
        # A folder still being written (a capture dumping frames) waits until all of it has settled.
        settling = {str(Path(p).parent) for p in self.pending if p not in ready}
        ready = [p for p in ready if str(Path(p).parent) not in settling]
        if not ready:
            return
        groups: dict[str, list] = {}
        for p in ready:
            groups.setdefault(str(Path(p).parent), []).append(p)
            self.seen[p] = now[p]
            del self.pending[p]
        for folder, paths in groups.items():
            self.log_group(folder, sorted(paths))
        self.save()

    def log_group(self, folder, paths):
        images = [p for p in paths if kind_of(p) == "image"]
        if len(images) >= SEQUENCE_MIN:
            pick = [images[0], images[len(images) // 2], images[-1]]
            emit({"type": "file", "title": f"{folder}/ ({len(images)} frames)", "sequence": len(images),
                  "files": [e for e in (snapshot(ROOT / p) for p in pick) if e]})
            paths = [p for p in paths if p not in images]
        # A capture writes a browser-ready .mp4 next to its .ogv: the .ogv adds nothing.
        if any(p.endswith(".mp4") for p in self.seen if str(Path(p).parent) == folder):
            paths = [p for p in paths if not p.endswith(".ogv")]
        entries, copies = [], []
        for p in paths:
            e = snapshot(ROOT / p)
            if not e:
                continue
            paths_for_blob = self.known.get(e["blob"], set())
            if p in paths_for_blob:
                continue                      # already logged by the tool that wrote it
            (copies if paths_for_blob else entries).append(e)
            self.known.setdefault(e["blob"], set()).add(p)
        for e in copies:
            emit({"type": "copy", "files": [e]})
        job = self.job_dirs.get(folder)
        if entries and job and time.time() - job[1] < 120:     # the rest of what a job just wrote (a capture's sheets)
            emit({"type": "attach", "job": job[0], "files": entries})
        elif entries:
            emit({"type": "file", "title": entries[0]["path"] if len(entries) == 1 else f"{folder}/",
                  "files": entries, "watched": True})


IS_WSL = "microsoft" in Path("/proc/version").read_text().lower() if Path("/proc/version").exists() else False


def win_path(p: Path) -> str | None:
    if not IS_WSL:
        return None
    r = subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True)
    return r.stdout.strip() or None


def host_info() -> dict:
    """What the page needs to build full paths and label the reveal button for this machine."""
    return {"root": str(ROOT), "win_root": win_path(ROOT), "win_slash": win_path(Path("/")), "host": os.uname().nodename,
            "reveal": "Explorer" if IS_WSL or sys.platform == "win32" else "Finder" if sys.platform == "darwin" else "folder"}


def reveal(target: Path):
    """Show the file selected in the file manager of the machine running the feed."""
    if IS_WSL:
        subprocess.Popen(["explorer.exe", f"/select,{win_path(target)}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Handler(BaseHTTPRequestHandler):
    page = Path(__file__).with_name("feed.html")
    timeout = 60     # a client that stops reading (a proxy wedged mid-download) frees its thread; streams ping every 15 s

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = self.page.read_bytes().replace(b"{{PROJECT}}", ROOT.name.encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/info":
            self.json(host_info())
        elif path == "/events":
            self.stream(once="once" in self.path)
        elif m := re.fullmatch(r"/blob/([0-9a-f]{16}\.[a-z0-9]+)", path):
            self.blob(BLOBS / m.group(1))
        else:
            self.send_error(404)

    def json(self, d: dict, code: int = 200):
        body = json.dumps(d).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.split("?")[0] != "/reveal":
            return self.send_error(404)
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.send_error(400)
        # Only files inside the project (or the feed's own snapshot of one that has since changed or gone).
        target = (ROOT / d.get("path", "")).resolve()
        if not (target.is_relative_to(ROOT) and target.is_file()):
            blob = BLOBS / str(d.get("blob", ""))
            if not (re.fullmatch(r"[0-9a-f]{16}\.[a-z0-9]+", str(d.get("blob", ""))) and blob.is_file()):
                return self.json({"ok": False, "error": "file not found"}, 404)
            target = blob
        reveal(target)
        self.json({"ok": True, "path": str(target), "snapshot": target.parent == BLOBS})

    def stream(self, once=False):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        # Every connection replays the log from the top; the page dedupes by event id.
        offset, idle = 0, 0.0
        try:
            while True:
                lines = []
                if EVENTS.exists():
                    with open(EVENTS) as f:
                        f.seek(offset)
                        chunk = f.read()
                    cut = chunk.rfind("\n") + 1
                    lines = chunk[:cut].splitlines()
                    offset += len(chunk[:cut].encode())
                for line in lines:
                    self.wfile.write(f"data: {line}\n\n".encode())
                if lines or once:
                    self.wfile.write(b"data: {\"type\":\"synced\"}\n\n")
                    idle = 0
                if once:            # ?once: history only, then close (headless screenshots never finish on a live stream)
                    self.wfile.flush()
                    return
                elif (idle := idle + 0.4) > 15:
                    self.wfile.write(b": ping\n\n")
                    idle = 0
                self.wfile.flush()
                time.sleep(0.4)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def blob(self, p: Path):
        if not p.is_file():
            return self.send_error(404)
        size = p.stat().st_size
        ctype = "model/gltf-binary" if p.suffix == ".glb" else mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            else:
                start = size - int(m.group(2))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        try:
            with open(p, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0 and (chunk := f.read(min(left, 1 << 20))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


def cmd_serve(a):
    FEED.mkdir(exist_ok=True)
    dirs = watch_dirs(a.watch)
    if not a.no_watch:
        Watcher(dirs, a.backfill).start()
    ThreadingHTTPServer.request_queue_size = 64      # each open page holds a stream; the default backlog is 5
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"feed: http://{a.host}:{a.port}/  project {ROOT}  watching {', '.join(rel(d) for d in dirs) or 'nothing'}",
          flush=True)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="serve the feed page and watch for new files")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--watch", nargs="+", help=f"folders to watch (default: {' '.join(WATCH_DEFAULT)})")
    s.add_argument("--no-watch", action="store_true")
    s.add_argument("--backfill", action="store_true", help="first run only: log files that already exist")
    s.set_defaults(func=cmd_serve)

    r = sub.add_parser("run", help="run a generator command and log it as one job")
    r.add_argument("--title")
    r.add_argument("--prompt")
    r.add_argument("--from", dest="sources", action="append", help="input file (repeatable)")
    r.add_argument("--out", action="append", help="output file, when the command's JSON doesn't name it")
    r.add_argument("--cost", help='e.g. "30 Tripo cr", "120 ElevenLabs cr", "7¢"')
    r.add_argument("--eta", type=float, help="expected seconds, for the progress bar")
    r.add_argument("cmd", nargs=argparse.REMAINDER)
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("add", help="log existing files")
    d.add_argument("files", nargs="+")
    d.add_argument("--title")
    d.add_argument("--prompt")
    d.add_argument("--tool")
    d.add_argument("--from", dest="sources", action="append")
    d.add_argument("--cost")
    d.add_argument("--at-mtime", action="store_true", help="date the entry by the files' mtime (backfilling)")
    d.set_defaults(func=cmd_add)

    n = sub.add_parser("note", help="log a note: a decision, the user's feedback, a milestone")
    n.add_argument("text")
    n.add_argument("--file", action="append")
    n.set_defaults(func=cmd_note)

    m = sub.add_parser("mark", help="mark the current version of a file kept or rejected")
    m.add_argument("file")
    m.add_argument("status", choices=["kept", "rejected"])
    m.add_argument("reason", nargs="?")
    m.set_defaults(func=cmd_mark)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
