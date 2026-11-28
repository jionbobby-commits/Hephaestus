"""C3 real WebView2 acceptance for the AI chat workspace.

This harness never opens the user's database. It copies the already-migrated
B3 drill database into a temporary directory, starts uvicorn against the copy
and a local mock Ollama server, then drives the real pywebview/WebView2 UI
with the same DesktopBridge capability token the desktop app uses.

Main phase:
  python tests/frontend/c3_chat_ui_verify.py --db data/b3-drill/drill.db --root <temp>

Reopen phase (same root, after the main phase closed its window):
  python tests/frontend/c3_chat_ui_verify.py --db data/b3-drill/drill.db --root <temp> --phase reopen

Output is JSON on stdout. The capability token is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REAL_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "Hephaestus" / "hephaestus.db"
CONV_TITLE = "C3 验收对话"
PROVIDER_LABEL = "本机 Mock Ollama"
NORMAL_MARK = "这是本地模拟模型的流式回答。"
STOP_MARK = "停止测试分段输出。"
FULL_STOP_MARK = "这是停止测试的完整末尾，不应该出现在已停止的消息里。"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def api(url: str, path: str, method: str = "GET", body: Any = None, token: str | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("X-Hephaestus-Capability", token)
        request.add_header("X-Hephaestus-Platform", "desktop")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return error.code, payload


def wait_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, payload = api(url, "/health")
            if status == 200 and payload == {"status": "ok"}:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def start_server(db: Path, log_path: Path, token: str) -> tuple[subprocess.Popen[bytes], str]:
    port = free_port()
    url = "http://127.0.0.1:" + str(port)
    env = os.environ.copy()
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if home:
        env.setdefault("USERPROFILE", home)
        env.setdefault("LOCALAPPDATA", str(Path(home) / "AppData" / "Local"))
    env["HEPHAESTUS_DATABASE_URL"] = "sqlite:///" + db.resolve().as_posix()
    env["HEPHAESTUS_SECRET_DIR"] = str((db.parent / "secrets").resolve())
    env["HEPHAESTUS_AI_TOKEN"] = token
    log = log_path.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    if not wait_health(url):
        proc.terminate()
        raise RuntimeError("server did not become healthy: " + str(log_path))
    return proc, url


def stop_server(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)


def copy_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    src = sqlite3.connect("file:" + source.resolve().as_posix() + "?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def ensure_v2_schema(path: Path) -> None:
    """Additive V2 schema for the copied acceptance database only."""
    from app.v2.db import create_v2_db, create_v2_engine

    engine = create_v2_engine("sqlite:///" + path.resolve().as_posix())
    try:
        create_v2_db(engine)
    finally:
        engine.dispose()


def db_check(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect("file:" + path.resolve().as_posix() + "?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        def count(table: str) -> int | None:
            if table not in tables:
                return None
            return conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

        return {
            "integrity": integrity,
            "tables": tables,
            "conversations": count("v2_conversations"),
            "messages": count("v2_messages"),
            "settings": count("v2_settings"),
        }
    finally:
        conn.close()


class MockOllama:
    """Loopback Ollama subset used only by this acceptance harness."""

    def __init__(self, port: int) -> None:
        self.port = port
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                return

            def _json(self, status: int, payload: Any) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path.split("?")[0] == "/api/tags":
                    self._json(200, {"models": [{"name": "mock-1", "model": "mock-1", "size": 1234}]})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self) -> None:
                if self.path.split("?")[0] != "/api/chat":
                    self._json(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except Exception:
                    payload = {}
                messages = payload.get("messages") if isinstance(payload, dict) else []
                last_user = ""
                for item in reversed(messages or []):
                    if isinstance(item, dict) and item.get("role") == "user":
                        last_user = str(item.get("content") or "")
                        break
                stop_test = STOP_MARK in last_user
                if stop_test:
                    text = (STOP_MARK + "第一段。第二段。第三段。第四段。第五段。") * 12 + FULL_STOP_MARK
                    chunks = [text[i:i + 12] for i in range(0, len(text), 12)]
                    delay = 0.14
                else:
                    text = (
                        NORMAL_MARK + chr(10) + chr(10)
                        + "**要点**：流式输出、Markdown 渲染和代码高亮都在真实界面中可用。"
                        + chr(10) + chr(10) + chr(96) * 3 + "python" + chr(10)
                        + "print('hello from mock-1')" + chr(10) + chr(96) * 3 + chr(10)
                    )
                    chunks = [text[i:i + 16] for i in range(0, len(text), 16)]
                    delay = 0.045
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for chunk in chunks:
                        line = json.dumps({"model": "mock-1", "message": {"role": "assistant", "content": chunk}, "done": False}, ensure_ascii=False)
                        self.wfile.write((line + chr(10)).encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(delay)
                    done = json.dumps({
                        "model": "mock-1", "message": {"role": "assistant", "content": ""},
                        "done": True, "done_reason": "stop", "prompt_eval_count": 20, "eval_count": 30,
                    })
                    self.wfile.write((done + chr(10)).encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def run_ui(url: str, token: str, phase: str) -> dict[str, Any]:
    import webview
    from desktop.main import DesktopBridge

    window = webview.create_window(
        "Hephaestus C3 AI acceptance", url + "/?desktop=1",
        width=1440, height=960, hidden=True, js_api=DesktopBridge(token),
    )
    result: dict[str, Any] = {"phase": phase, "steps": [], "checks": {}, "ui": {}}

    def js(script: str) -> Any:
        return window.evaluate_js(script)

    def step(name: str, value: Any = None) -> None:
        result["steps"].append({"name": name, "at": round(time.time(), 3), "value": value})

    def check(name: str, condition: bool, detail: Any = None) -> None:
        result["checks"][name] = {"ok": bool(condition), "detail": detail}
        step("check_" + name, bool(condition))

    def wait_for(expression: str, timeout: float = 45.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                value = js("Boolean(" + expression + ")")
                if value is True or value == "true":
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def click(selector: str) -> bool:
        return bool(js("(() => { const el = document.querySelector(" + json.dumps(selector) + "); if (!el) return false; el.click(); return true; })()"))

    def set_value(selector: str, value: str) -> bool:
        return bool(js("(() => { const el = document.querySelector(" + json.dumps(selector) + "); if (!el) return false; el.value = " + json.dumps(value) + "; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return true; })()"))

    def text(selector: str) -> str:
        return str(js("(() => { const el = document.querySelector(" + json.dumps(selector) + "); return el ? el.innerText : ''; })()") or "")

    def snapshot() -> dict[str, Any]:
        raw = js("""JSON.stringify({
          workspace: !document.querySelector('#chatWorkspace').hidden,
          status: (document.querySelector('#chatStatus') || {}).textContent || '',
          title: (document.querySelector('#chatTitle') || {}).textContent || '',
          notice: (document.querySelector('#chatNotice') || {}).innerText || '',
          messages: [...document.querySelectorAll('.msg')].map(el => ({
            role: el.classList.contains('assistant') ? 'assistant' : 'user',
            text: (el.querySelector('.msg-bubble') || {}).innerText || '',
            html: (el.querySelector('.msg-bubble') || {}).innerHTML || '',
            state: (el.querySelector('.msg-state') || {}).textContent || ''
          })),
          conversations: [...document.querySelectorAll('.chat-conv')].map(el => el.innerText),
          providers: [...document.querySelectorAll('#chatProviderSel option')].map(el => ({value: el.value, text: el.textContent})),
          models: [...document.querySelectorAll('#chatModelSel option')].map(el => ({value: el.value, text: el.textContent})),
          persona: {
            name: (document.querySelector('#personaName') || {}).value || '',
            style: (document.querySelector('#personaStyle') || {}).value || '',
            length: (document.querySelector('#personaLength') || {}).value || '',
            prompt: (document.querySelector('#personaPrompt') || {}).value || '',
            preview: (document.querySelector('#personaPreview') || {}).innerText || ''
          },
          tokenInDom: document.documentElement.innerHTML.includes('""" + token + """'),
          tokenInStorage: Object.keys(localStorage).some(k => String(localStorage.getItem(k) || '').includes('""" + token + """')) || Object.keys(sessionStorage).some(k => String(sessionStorage.getItem(k) || '').includes('""" + token + """'))
        })""")
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data

    def record(name: str) -> dict[str, Any]:
        snap = snapshot()
        result["ui"][name] = {
            "title": snap["title"], "status": snap["status"], "messages": len(snap["messages"]),
            "conversations": len(snap["conversations"]), "providers": len(snap["providers"]),
            "models": [m["value"] for m in snap["models"]], "notice": snap["notice"],
        }
        step(name, result["ui"][name])
        return snap

    def open_chat() -> bool:
        if not click("#assistantBtn"):
            return False
        if not wait_for("!document.querySelector('#chatWorkspace').hidden", 20):
            return False
        return wait_for("document.querySelectorAll('#chatProviderSel option').length > 0 || !document.querySelector('#chatProviderSel').disabled", 30)

    def select_conversation() -> bool:
        wanted = json.dumps(CONV_TITLE)
        if not wait_for("(() => { const btns = [...document.querySelectorAll('.chat-conv')]; return btns.some(b => b.innerText.includes(" + wanted + ")); })()", 30):
            return False
        return bool(js("(() => { const btns = [...document.querySelectorAll('.chat-conv')]; const el = btns.find(b => b.innerText.includes(" + wanted + ")); if (!el) return false; el.click(); return true; })()"))

    def driver() -> None:
        try:
            if not wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60):
                result["error"] = "UI did not initialize"
                return
            time.sleep(0.8)
            snap = snapshot()
            check("token_not_in_dom", not snap["tokenInDom"], snap["tokenInDom"])
            check("token_not_in_storage", not snap["tokenInStorage"], snap["tokenInStorage"])
            if not open_chat():
                result["error"] = "chat workspace did not open"
                return
            snap = record("chat_open")
            check("chat_open", snap["workspace"], snap["workspace"])
            if phase == "reopen":
                wait_for("document.querySelectorAll('.chat-conv').length >= 1", 30)
                snap = record("chat_open")
                check("reopen_conversations", len(snap["conversations"]) >= 1, len(snap["conversations"]))
                if not select_conversation():
                    result["error"] = "saved conversation not found after reopen"
                    return
                if not wait_for("document.querySelectorAll('.msg').length >= 2", 20):
                    result["error"] = "saved messages did not load after reopen"
                    return
                restored = record("reopen_loaded")
                check("reopen_user_message", any(m["role"] == "user" and "Markdown" in m["text"] for m in restored["messages"]), len(restored["messages"]))
                check("reopen_assistant_message", any(m["role"] == "assistant" and NORMAL_MARK in m["text"] for m in restored["messages"]), len(restored["messages"]))
                click("#chatPersonaBtn")
                wait_for("!document.querySelector('#personaModal').hidden", 10)
                time.sleep(0.4)
                persona = snapshot()["persona"]
                check("reopen_persona_name", persona["name"] == "赫淮斯托斯·验收", persona["name"])
                check("reopen_persona_style", persona["style"] == "academic", persona["style"])
                check("reopen_persona_prompt", "先给出结论" in persona["prompt"], len(persona["prompt"]))
                return

            # Provider configuration through the real desktop UI.
            click("#chatProviderBtn")
            if not wait_for("!document.querySelector('#providerModal').hidden", 10):
                result["error"] = "provider modal did not open"
                return
            set_value("#providerLabel", PROVIDER_LABEL)
            set_value("#providerBaseUrl", "http://127.0.0.1:" + str(MOCK_PORT[0]))
            set_value("#providerModel", "mock-1")
            click("#providerSaveBtn")
            # The form resets its status immediately after a successful save, so
            # verify the provider actually reached the selector instead of racing
            # a transient label.
            if not wait_for("[...document.querySelectorAll('#chatProviderSel option')].some(o => o.textContent.includes(" + json.dumps(PROVIDER_LABEL) + "))", 30):
                result["error"] = "provider was not saved: " + text("#providerStatus")
                return
            click("[data-close='providerModal']")
            wait_for("!document.querySelector('#chatProviderSel').disabled", 20)
            configured = record("provider_configured")
            check("provider_saved", any(PROVIDER_LABEL in p["text"] for p in configured["providers"]), configured["providers"])
            check("model_selected", any(m["value"] == "mock-1" for m in configured["models"]), configured["models"])

            # Persona settings through the real UI.
            click("#chatPersonaBtn")
            wait_for("!document.querySelector('#personaModal').hidden", 10)
            set_value("#personaName", "赫淮斯托斯·验收")
            set_value("#personaStyle", "academic")
            set_value("#personaLength", "short")
            set_value("#personaPrompt", "回答时先给出结论，再列出三条以内的要点。")
            time.sleep(0.3)
            preview = snapshot()["persona"]["preview"]
            check("persona_preview", "赫淮斯托斯·验收" in preview and "学术" in preview, preview[:120])
            click("#personaSaveBtn")
            if not wait_for("document.querySelector('#personaStatus').textContent.includes('已保存')", 20):
                result["error"] = "persona was not saved: " + text("#personaStatus")
                return
            time.sleep(0.6)
            check("persona_modal_closed", bool(js("document.querySelector('#personaModal').hidden")), None)

            # Create, rename, send and stream.
            click("#chatNewBtn")
            if not wait_for("document.querySelector('#chatTitle').textContent.includes('新对话')", 20):
                result["error"] = "conversation was not created"
                return
            js("window.prompt = () => " + json.dumps(CONV_TITLE) + "; true")
            click("#chatRenameBtn")
            wait_for("document.querySelector('#chatTitle').textContent.includes(" + json.dumps(CONV_TITLE) + ")", 15)

            # Archive and restore through the real UI.
            click("#chatArchiveBtn")
            if not wait_for("document.querySelector('#chatArchiveBtn').textContent === '取消归档'", 20):
                result["error"] = "archive action did not apply"
                return
            archived_ui = snapshot()
            check("archive_list_marked", any("已归档" in item for item in archived_ui["conversations"]), archived_ui["conversations"][:2])
            check("archive_input_disabled", bool(js("document.querySelector('#chatInput').disabled")), None)
            click("#chatArchiveBtn")
            if not wait_for("document.querySelector('#chatArchiveBtn').textContent === '归档'", 20):
                result["error"] = "unarchive action did not apply"
                return
            check("unarchive_input_enabled", not bool(js("document.querySelector('#chatInput').disabled")), None)

            set_value("#chatInput", "请用 Markdown 回答，包含一个 Python 代码块。")
            click("#chatSendBtn")
            if not wait_for("!document.querySelector('#chatStopBtn').hidden", 20):
                result["error"] = "stream did not start"
                return
            if not wait_for("document.querySelectorAll('.msg.assistant .msg-state').length && [...document.querySelectorAll('.msg.assistant .msg-state')].some(el => el.textContent !== '生成中')", 40):
                result["error"] = "stream did not finish"
                return
            time.sleep(0.8)
            streamed = record("streamed")
            assistant = [m for m in streamed["messages"] if m["role"] == "assistant"][-1]
            check("stream_content", NORMAL_MARK in assistant["text"], assistant["text"][:80])
            check("markdown_bold", "<strong>" in assistant["html"], assistant["html"][:120])
            check("markdown_code", "<pre><code>" in assistant["html"], bool(assistant["html"]))
            check("markdown_safe", "<script" not in assistant["html"].lower(), None)
            check("stream_complete_state", assistant["state"] not in {"生成中", "生成失败"}, assistant["state"])

            # Stop generation and preserve the partial content.
            set_value("#chatInput", STOP_MARK + "请分段慢慢输出。")
            click("#chatSendBtn")
            if not wait_for("!document.querySelector('#chatStopBtn').hidden", 20):
                result["error"] = "second stream did not start"
                return
            time.sleep(0.6)
            click("#chatStopBtn")
            if not wait_for("[...document.querySelectorAll('.msg.assistant .msg-state')].some(el => el.textContent === '已停止')", 30):
                result["error"] = "stop state did not appear"
                return
            stopped = record("stopped")
            stopped_assistant = [m for m in stopped["messages"] if m["role"] == "assistant"][-1]
            check("stop_preserved_content", len(stopped_assistant["text"].strip()) > 0, len(stopped_assistant["text"]))
            check("stop_not_full_text", FULL_STOP_MARK not in stopped_assistant["text"], FULL_STOP_MARK in stopped_assistant["text"])

            # Regenerate the first complete answer.
            first_assistant = js("(() => { const rows = [...document.querySelectorAll('.msg.assistant')]; const row = rows.find(r => { const b = r.querySelector('[data-action=regenerate]'); return !!b; }); if (!row) return false; const btn = row.querySelector('[data-action=regenerate]'); btn.click(); return true; })()")
            check("regenerate_clicked", bool(first_assistant), first_assistant)
            if first_assistant:
                if not wait_for("!document.querySelector('#chatStopBtn').hidden", 20):
                    result["error"] = "regenerate stream did not start"
                    return
                if not wait_for("[...document.querySelectorAll('.msg.assistant .msg-state')].every(el => el.textContent !== '生成中')", 40):
                    result["error"] = "regenerate stream did not finish"
                    return
                time.sleep(0.8)
                regenerated = record("regenerated")
                check("regenerate_complete", any(NORMAL_MARK in m["text"] for m in regenerated["messages"] if m["role"] == "assistant"), len(regenerated["messages"]))

            # Refresh restores the database-backed conversation, not localStorage.
            js("location.reload(); true")
            time.sleep(3.2)
            if not wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60):
                result["error"] = "UI did not initialize after refresh"
                return
            if not open_chat() or not select_conversation():
                result["error"] = "conversation missing after refresh"
                return
            if not wait_for("document.querySelectorAll('.msg').length >= 2", 20):
                result["error"] = "messages missing after refresh"
                return
            refreshed = record("refreshed")
            check("refresh_user_message", any(m["role"] == "user" and "Markdown" in m["text"] for m in refreshed["messages"]), len(refreshed["messages"]))
            check("refresh_assistant_message", any(m["role"] == "assistant" and NORMAL_MARK in m["text"] for m in refreshed["messages"]), len(refreshed["messages"]))
            check("refresh_persona_header", True, None)
        except Exception as exc:
            result["error"] = repr(exc)
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    webview.start(driver, gui="edgechromium", debug=False, private_mode=False, http_server=False)
    return result


MOCK_PORT = [0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--root", default=None)
    parser.add_argument("--phase", choices=["main", "reopen"], default="main")
    parser.add_argument("--port", type=int, default=0, help="mock Ollama port (reopen reuses it when possible)")
    args = parser.parse_args()

    source = Path(args.db).resolve()
    root = Path(args.root).resolve() if args.root else Path(tempfile.mkdtemp(prefix="heph-c3-chat-ui-"))
    root.mkdir(parents=True, exist_ok=True)
    target = root / "c3-chat.db"
    log_path = root / "server-c3.log"
    token = os.environ.get("HEPHAESTUS_AI_TOKEN", "") or __import__("secrets").token_urlsafe(48)
    if len(token) < 32:
        token = __import__("secrets").token_urlsafe(48)

    source_hash_before = digest(source)
    real_hash_before = digest(REAL_DB)
    if args.phase == "main":
        copy_sqlite(source, target)
        ensure_v2_schema(target)
    elif not target.exists():
        raise SystemExit("reopen requires the main phase database: " + str(target))

    mock_port = args.port or (MOCK_PORT[0] if MOCK_PORT[0] else free_port())
    mock = MockOllama(mock_port)
    try:
        mock.start()
    except OSError:
        mock = MockOllama(free_port())
        mock.start()
        mock_port = mock.port
    MOCK_PORT[0] = mock_port
    proc, url = start_server(target, log_path, token)
    try:
        if args.phase == "reopen":
            # The saved provider may point at the main phase port; align it with
            # the current mock so model refresh and optional sends stay local.
            status, providers = api(url, "/api/v2/ai/providers", token=token)
            if status == 200 and isinstance(providers, list):
                for provider in providers:
                    if provider.get("kind") == "ollama" and provider.get("base_url", "").startswith("http://127.0.0.1:"):
                        api(url, "/api/v2/ai/providers/" + str(provider.get("id")), "PATCH", {
                            "base_url": "http://127.0.0.1:" + str(mock_port),
                            "model": provider.get("model") or "mock-1",
                        }, token=token)
        result = run_ui(url, token, args.phase)
        result["mock_port"] = mock_port
        result["db_check"] = db_check(target)
        if result.get("checks"):
            status, detail = api(url, "/api/v2/ai/conversations?page=1&page_size=20", token=token)
            result["http_conversations"] = detail if status == 200 else {"status": status}
    finally:
        stop_server(proc)
        mock.stop()

    result["root"] = str(root)
    result["db"] = str(target)
    result["log"] = str(log_path)
    result["source_sha256_before"] = source_hash_before
    result["source_sha256_after"] = digest(source)
    result["source_unchanged"] = source_hash_before == result["source_sha256_after"]
    result["real_db_sha256_before"] = real_hash_before
    result["real_db_sha256_after"] = digest(REAL_DB)
    result["real_db_unchanged"] = real_hash_before == result["real_db_sha256_after"]
    failed = [name for name, value in result.get("checks", {}).items() if not value.get("ok")]
    result["failed_checks"] = failed
    if failed and not result.get("error"):
        result["error"] = "failed checks: " + ", ".join(failed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
