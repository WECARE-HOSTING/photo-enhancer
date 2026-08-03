#!/usr/bin/env python3
"""The little server that lets a review page write its own file and run the
next command.

    import serve
    serve.run(root=job, page="review-edit.html", actions=..., title=job.name)

Every gate in this pipeline used to end the same way: a button put text on your
clipboard, you opened `picks.txt` or `gate.txt` by hand, pasted over it, saved,
went back to the terminal and typed the next command. Three gates, three times,
every job. The reason was real — a page opened as `file://` cannot write to
disk — but the reason is about `file://`, not about the design.

**The page still composes nothing.** It sends the exact bytes its clipboard
button already produces, and this module writes them into the exact file you
would have pasted into. One writer per format, formats untouched, and the
clipboard button stays right where it is: open the same page from the disk and
it behaves as it always has. What goes away is the typing in between.

## What it is not

It is **not a shell**. A request names an *action*; the argv is built here, from
a registry the stage script hands over at startup. There is no path from
anything a browser sends to anything a shell sees. The filename written comes
from `Action.writes`, never from the request.

It binds `127.0.0.1` on a port the OS picks, mints a fresh token per run and
requires it on every POST. Static GETs are open: they serve a folder you can
already read, and requiring a token there would mean a cookie, which is a
failure mode bought for nothing.

## Two guards against a second server

An action re-invokes the very script that is serving — `batch.py --rework` is
launched by a `batch.py` that is sitting in `serve_forever()`. The child must
not serve as well, or you get a second port, a second browser tab, and a parent
blocked forever on a pipe that will never close. So: the action passes
`--no-serve`, **and** `enabled()` refuses when it finds `CHILD_ENV` in the
environment. Either alone would be enough on a good day. One forgotten argument
in a registry row is not a good day.

`enabled()` also refuses when stdout is not a terminal, which is what keeps an
agent from hanging on a server it cannot see or stop. Do not remove that check.

## Who redraws the page

The child does, exactly as it does from the terminal — `batch.py --rework` ends
by calling `write_review()` like it always did. This module never learns how to
build a page; when the child exits 0 it tells the browser to reload, and the
same server hands over the file the child just wrote.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

CHILD_ENV = "PHOTO_ENHANCER_CHILD"

MAX_BODY = 4 * 1024 * 1024      # an ambientes.md for 300 photographs is ~60 KB
MAX_LINES = 4000                # per run, kept so a reopened tab can catch up
HEARTBEAT = 15.0                # seconds between SSE pings
API = "/_gate/"                 # every endpoint lives under here, so a photo
                                # named `state.jpg` can never collide with one


@dataclass(frozen=True)
class Action:
    """One button. The registry of these is the whole vocabulary of a session."""
    name: str                           # what the browser sends, and all it sends
    label: str                          # what the button says
    writes: str = ""                    # file written first; "" writes nothing
    script: "Path | None" = None        # what to run; None runs nothing
    args: "tuple[str, ...]" = ()
    outcome: str = "reload"             # "reload" | "ends_session" | "none"
    danger: str = ""                    # the extra line in the confirm dialog
    note: str = ""                      # one line of plain explanation
    tone: str = ""                      # "go" | "bad" | "" — the button's colour
    needs_clean: bool = False           # greyed out while anything is ticked

    def cmd(self) -> str:
        """The command as you would type it — `paths.cmd` stays the only speller."""
        return paths.cmd(self.script, *self.args) if self.script else ""

    def as_json(self) -> dict:
        return {"name": self.name, "label": self.label, "writes": self.writes,
                "cmd": self.cmd(), "outcome": self.outcome if self.script else "none",
                "danger": self.danger, "note": self.note, "tone": self.tone,
                "needsClean": self.needs_clean}


@dataclass
class Run:
    """A child process, its output so far, and how it ended."""
    id: int
    action: str
    cmd: str
    started: float
    lines: "list[str]" = field(default_factory=list)
    code: "int | None" = None
    outcome: str = "none"
    proc: "subprocess.Popen | None" = None
    done: "threading.Event" = field(default_factory=threading.Event)
    waiters: "list[queue.Queue]" = field(default_factory=list)


# ------------------------------------------------------------------ the disk

RTF_HEAD = "{\\rtf"


def safe_join(root: Path, name: str) -> Path:
    """`root / name`, or a refusal. Defence in depth behind `Action.writes`:
    the name never comes from a request, and this makes sure it cannot start."""
    if not name or name != Path(name).name or name in {".", ".."}:
        raise ValueError(f"não é um nome de arquivo: {name!r}")
    dest = (Path(root) / name).resolve()
    if dest.parent != Path(root).resolve():
        raise ValueError(f"{name!r} sairia da pasta servida")
    return dest


def write_file(root: Path, name: str, text: str) -> int:
    """Write one gate file. Returns bytes written.

    Through a temporary and `os.replace`, so a half-written `gate.txt` cannot
    exist even for an instant — the next command reads this file, and a
    truncated one parses as fewer photographs rather than as an error.
    """
    dest = safe_join(root, name)
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if body.lstrip().startswith(RTF_HEAD):
        raise ValueError("isso é Rich Text, não texto simples")
    if body and not body.endswith("\n"):
        body += "\n"
    scratch = dest.with_suffix(dest.suffix + ".new")
    try:
        scratch.write_text(body, encoding="utf-8")
        os.replace(scratch, dest)
    finally:
        scratch.unlink(missing_ok=True)
    return len(body.encode("utf-8"))


# --------------------------------------------------------------- the session

class Session:
    """One folder, one page, one registry of actions, one live run at a time."""

    def __init__(self, root: Path, page: str, actions: "dict[str, Action]",
                 title: str = "", counts: "dict | None" = None):
        self.root = Path(root).resolve()
        self.page = page
        self.actions = actions
        self.title = title or self.root.name
        self.counts = counts or {}
        self.token = secrets.token_urlsafe(16)
        self.gen = 1
        self.closed = False
        self.runs: "dict[int, Run]" = {}
        self.live: "Run | None" = None
        self.lock = threading.Lock()
        self.httpd: "ThreadingHTTPServer | None" = None

    # ---- state a page asks about

    @property
    def url(self) -> str:
        port = self.httpd.server_address[1] if self.httpd else 0
        return f"http://127.0.0.1:{port}/{self.page}?t={self.token}"

    def state(self) -> dict:
        live = self.live
        return {
            "sid": self.token[:8], "gen": self.gen, "page": self.page,
            "title": self.title, "counts": self.counts, "closed": self.closed,
            "actions": [a.as_json() for a in self.actions.values()],
            "running": None if not live or live.done.is_set() else
                       {"id": live.id, "action": live.action,
                        "since": round(time.time() - live.started)},
        }

    # ---- running a child

    def start(self, action: Action) -> Run:
        """Spawn the action's script. Caller holds no lock; this takes it."""
        with self.lock:
            if self.live and not self.live.done.is_set():
                raise RuntimeError(f"'{self.live.action}' ainda está rodando")
            run = Run(id=len(self.runs) + 1, action=action.name,
                      cmd=action.cmd(), started=time.time())
            run.outcome = action.outcome
            self.runs[run.id] = run
            self.live = run

        env = {**os.environ, CHILD_ENV: "1", "PYTHONUNBUFFERED": "1"}
        argv = [str(paths.VENV_PY_ABS), str(action.script), *action.args]
        try:
            run.proc = subprocess.Popen(
                argv, cwd=str(paths.ROOT), env=env, text=True, bufsize=1,
                encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True)
        except OSError as e:
            self._emit(run, f"error: não consegui rodar: {e}")
            self._finish(run, 127)
            return run

        threading.Thread(target=self._pump, args=(run,), daemon=True).start()
        return run

    def _pump(self, run: Run) -> None:
        """Read the child, line by line, to the page and to our own terminal."""
        try:
            for line in run.proc.stdout:                 # type: ignore[union-attr]
                self._emit(run, line.rstrip("\n"))
        except Exception as e:                           # noqa: BLE001
            self._emit(run, f"error: leitura interrompida: {type(e).__name__}: {e}")
        finally:
            try:
                run.proc.stdout.close()                  # type: ignore[union-attr]
            except Exception:                            # noqa: BLE001
                pass
            self._finish(run, run.proc.wait() if run.proc else 1)

    def _emit(self, run: Run, line: str) -> None:
        # Printed here too, deliberately: close the tab mid-run and the terminal
        # that started this is still a complete log of what happened.
        print(line, flush=True)
        with self.lock:
            run.lines.append(line)
            if len(run.lines) > MAX_LINES:
                del run.lines[:len(run.lines) - MAX_LINES]
            for q in run.waiters:
                q.put(("line", line))

    def _finish(self, run: Run, code: int) -> None:
        with self.lock:
            run.code = code
            if code != 0:
                # A failed child changed nothing the page has to catch up with,
                # and its output is what the human needs to read. Leave the page
                # alone: reloading would wipe the error off the screen.
                run.outcome = "none"
            elif run.outcome == "reload":
                self.gen += 1
            elif run.outcome == "ends_session":
                self.closed = True
            payload = {"code": code, "outcome": run.outcome, "gen": self.gen}
            for q in run.waiters:
                q.put(("end", json.dumps(payload, ensure_ascii=False)))
        run.done.set()
        if run.outcome == "ends_session":
            # One second so the browser has the `end` event before we stop
            # answering, and never from a handler thread — `shutdown()` called
            # from inside a request waits for that request to finish, forever.
            threading.Timer(1.0, self.stop).start()

    def cancel(self, run: Run) -> str:
        proc = run.proc
        if not proc or run.done.is_set():
            return "já terminou"
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            proc.terminate()
        try:
            proc.wait(timeout=5)
            return "encerrado"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            return "morto à força"

    # ---- the loop

    def serve(self, open_browser: bool = True) -> None:
        self.httpd = _Server(("127.0.0.1", 0), _handler_for(self))

        print(f"\npágina      {self.url}")
        print("            os botões dela gravam o arquivo e rodam o passo "
              "seguinte;\n            Ctrl-C aqui quando terminar de revisar.",
              flush=True)
        if open_browser:
            webbrowser.open(self.url)
        try:
            self.httpd.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            print("\nservidor encerrado. A página parou de funcionar; "
                  "os arquivos estão todos no disco.")
        finally:
            self.httpd.server_close()

    def stop(self) -> None:
        if self.httpd:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()


# --------------------------------------------------------------- the handler

class _Server(ThreadingHTTPServer):
    daemon_threads = True       # an SSE stream holds a thread for minutes

    def handle_error(self, request, client_address):
        """A browser that walks away is not an error.

        Closing the tab, pressing Escape on a loading page, or scrolling past a
        lazy image mid-transfer all reset the connection, and the default prints
        a twenty-line traceback for each one — on the same terminal where the
        run's own output is the thing worth reading. Anything else still shows.
        """
        if sys.exc_info()[0] in (ConnectionResetError, BrokenPipeError,
                                 ConnectionAbortedError, TimeoutError):
            return
        super().handle_error(request, client_address)


def _handler_for(session: Session):
    class Handler(SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(session.root), **kw)

        # The default logs every request to stderr, which would bury the child's
        # output — the one thing on this terminal worth reading.
        def log_message(self, *a):      # noqa: A003
            pass

        # ---- plumbing

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _text(self, code: int, text: str) -> None:
            self._send(code, text.encode("utf-8"), "text/plain; charset=utf-8")

        def _authorised(self) -> "dict | None":
            """Token, origin and generation. Returns the parsed body, or None
            after having already answered with why not."""
            if self.headers.get("X-Gate-Token") != session.token:
                self._json(403, {"error": "token inválido — abra a URL que o "
                                          "terminal imprimiu, não uma antiga"})
                return None
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self.server.server_address[1]}":
                self._json(403, {"error": "origem inesperada"})
                return None
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self._json(413, {"error": "corpo grande demais"})
                return None
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                self._json(400, {"error": "corpo ilegível"})
                return None
            if not isinstance(body, dict):
                self._json(400, {"error": "corpo ilegível"})
                return None

            sent = self.headers.get("X-Gate-Gen")
            if sent is not None and sent != str(session.gen):
                self._json(409, {"error": "esta página é de uma rodada anterior "
                                          "— recarregue (⌘R) antes de gravar",
                                 "gen": session.gen})
                return None
            return body

        def _action(self, body: dict) -> "Action | None":
            found = session.actions.get(str(body.get("action", "")))
            if not found:
                self._json(404, {"error": f"ação desconhecida: "
                                          f"{body.get('action')!r}"})
            return found

        # ---- GET

        def do_GET(self):               # noqa: N802
            path = self.path.split("?", 1)[0]
            if path.startswith(API):
                return self._api_get(path[len(API):])
            if session.closed:
                return self._text(410,
                    "Este trabalho já saiu desta pasta — a revisão terminou.\n"
                    "O servidor está encerrando. Nada aqui responde mais.\n")
            return super().do_GET()

        def _api_get(self, what: str):
            if what == "state":
                return self._json(200, session.state())
            if what == "stream":
                return self._stream()
            return self._json(404, {"error": "não existe"})

        def _stream(self):
            """Server-sent events for one run, replayed from `from` onwards."""
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            run = session.runs.get(int((q.get("run") or ["0"])[0] or 0))
            if not run:
                return self._json(404, {"error": "essa rodada não existe"})
            start = int((q.get("from") or ["0"])[0] or 0)

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()

            mine: "queue.Queue" = queue.Queue()
            with session.lock:
                backlog = run.lines[start:]
                ended = run.code if run.done.is_set() else None
                if ended is None:
                    run.waiters.append(mine)
            try:
                for line in backlog:
                    if not self._event("line", line):
                        return
                if ended is not None:
                    self._event("end", json.dumps(
                        {"code": ended, "outcome": run.outcome,
                         "gen": session.gen}, ensure_ascii=False))
                    return
                while True:
                    try:
                        kind, data = mine.get(timeout=HEARTBEAT)
                    except queue.Empty:
                        if not self._raw(": ping\n\n"):
                            return
                        continue
                    if not self._event(kind, data):
                        return
                    if kind == "end":
                        return
            finally:
                with session.lock:
                    if mine in run.waiters:
                        run.waiters.remove(mine)

        def _raw(self, text: str) -> bool:
            try:
                self.wfile.write(text.encode("utf-8"))
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError, ValueError):
                return False        # the tab closed; the child carries on

        def _event(self, kind: str, data: str) -> bool:
            payload = "".join(f"data: {ln}\n" for ln in data.split("\n"))
            return self._raw(f"event: {kind}\n{payload}\n")

        # ---- POST

        def do_POST(self):              # noqa: N802
            path = self.path.split("?", 1)[0]
            if not path.startswith(API):
                return self._json(404, {"error": "não existe"})
            body = self._authorised()
            if body is None:
                return
            what = path[len(API):]
            if what == "save":
                return self._save(body)
            if what == "run":
                return self._run(body)
            if what == "cancel":
                return self._cancel(body)
            return self._json(404, {"error": "não existe"})

        def _write(self, action: Action, body: dict) -> "str | None":
            """Returns an error message, or None having written the file."""
            if not action.writes:
                return None
            text = body.get("text")
            if not isinstance(text, str):
                return "essa ação precisa do texto e ele não veio"
            try:
                wrote = write_file(session.root, action.writes, text)
            except (ValueError, OSError) as e:
                return str(e)
            print(f"gravado     {paths.rel(session.root / action.writes)} "
                  f"· {wrote} bytes · pela página")
            return None

        def _save(self, body: dict):
            action = self._action(body)
            if not action:
                return
            problem = self._write(action, body)
            if problem:
                return self._json(400, {"error": problem})
            return self._json(200, {"ok": True, "wrote": action.writes,
                                    "gen": session.gen})

        def _run(self, body: dict):
            action = self._action(body)
            if not action:
                return
            if session.closed:
                return self._json(410, {"error": "esta sessão já terminou"})
            if session.live and not session.live.done.is_set():
                return self._json(409, {
                    "error": f"'{session.live.action}' ainda está rodando",
                    "run": session.live.id})
            # The file first, in the same request: one confirmation, and what you
            # wrote is on disk even if the command then refuses to run.
            problem = self._write(action, body)
            if problem:
                return self._json(400, {"error": problem})
            if not action.script:
                return self._json(200, {"ok": True, "wrote": action.writes,
                                        "gen": session.gen})
            try:
                run = session.start(action)
            except RuntimeError as e:
                return self._json(409, {"error": str(e)})
            print(f"\nrodando     {run.cmd}\n")
            return self._json(200, {"ok": True, "run": run.id, "cmd": run.cmd})

        def _cancel(self, body: dict):
            run = session.runs.get(int(body.get("run") or 0))
            if not run:
                return self._json(404, {"error": "essa rodada não existe"})
            return self._json(200, {"ok": True, "how": session.cancel(run)})

    return Handler


# ------------------------------------------------------------- the front door

def enabled(flag: bool = True) -> bool:
    """Whether this process may serve. Three ways to say no, all of them real."""
    if not flag:
        return False
    if os.environ.get(CHILD_ENV):
        # Reachable only through a registry row that forgot `--no-serve`. Loud,
        # because the failure it prevents is a parent blocked forever.
        print("nota        já existe um servidor; este processo não abre outro "
              f"({CHILD_ENV})")
        return False
    if not sys.stdout.isatty():
        # No terminal means nobody can see the URL or press Ctrl-C — an agent, a
        # cron job, a pipe. Serving there is a hang, not a feature.
        return False
    return True


def run(root: Path, page: str, actions: "dict[str, Action]", title: str = "",
        counts: "dict | None" = None, open_browser: bool = True) -> None:
    """Serve one folder until Ctrl-C. Assumes `enabled()` already said yes."""
    Session(root, page, actions, title, counts).serve(open_browser=open_browser)


# ------------------------------------------------------------------ self-test

DEMO_LINES = 8


def _demo_child() -> None:
    for i in range(1, DEMO_LINES + 1):
        print(f"foto {i}/{DEMO_LINES}   trabalhando…")
        time.sleep(0.7)
    print("pronto")


def _demo(folder: str) -> None:
    """`serve.py <pasta>` — the module on its own, with a pretend action."""
    here = Path(__file__).resolve()
    root = Path(folder).resolve()
    page = next((p.name for p in sorted(root.glob("*.html"))), "")
    if not page:
        sys.exit(f"error: {root} não tem nenhum .html para servir")
    actions = {
        "save": Action("save", "Salvar", writes="demo.txt",
                       outcome="none", note="grava demo.txt e mais nada"),
        "echo": Action("echo", "Rodar (de mentira)", writes="demo.txt",
                       script=here, args=("--demo-child",),
                       danger="é de mentira, não gasta nada"),
        "bye": Action("bye", "Encerrar", script=here, args=("--demo-child",),
                      outcome="ends_session"),
    }
    Session(root, page, actions, title="demo", counts={"fotos": 0}).serve(
        open_browser="--quiet" not in sys.argv)


if __name__ == "__main__":
    if "--demo-child" in sys.argv:
        _demo_child()
    elif len(sys.argv) > 1:
        _demo(sys.argv[1])
    else:
        sys.exit(f"uso: {Path(__file__).name} <pasta com um .html>  "
                 "(auto-teste; o pipeline importa este módulo)")
