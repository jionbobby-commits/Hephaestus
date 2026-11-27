"""Real WebView2 UI verification for Hephaestus V2 B2.

This script is deliberately separate from pytest: it opens the real pywebview
window (hidden) and drives the real frontend against a temporary SQLite file.
It never reads or writes %LOCALAPPDATA%\\Hephaestus.

Run one scenario:
  .venv\\Scripts\\python.exe tests/frontend/ui_verify.py --mode v2 --phase main

Output: JSON on stdout, with all HTTP/UI evidence in "steps".
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.frontend.ui_fixtures import build_failed, build_legacy, build_pending, build_v2  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def api(url: str, path: str, method: str = "GET", body: Any = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
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

def start_server(db: Path, log_path: Path, port: int | None = None, app_target: str = "app.main:app") -> tuple[subprocess.Popen[bytes], str]:
    port = port or free_port()
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["HEPHAESTUS_DATABASE_URL"] = "sqlite:///" + db.resolve().as_posix()
    log = log_path.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app_target, "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    if not wait_health(url):
        proc.terminate()
        raise RuntimeError(f"server did not become healthy; see {log_path}")
    return proc, url

def stop_server(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)


def run_ui(url: str, mode: str, phase: str, db: Path, proc_holder: dict[str, Any], log_path: Path) -> dict[str, Any]:
    import webview

    window = webview.create_window("Hephaestus B2 UI verification", url + "/?desktop=1", width=1280, height=900, hidden=True)
    result: dict[str, Any] = {"mode": mode, "phase": phase, "steps": [], "ui": {}, "http": {}}

    def js(script: str) -> Any:
        return window.evaluate_js(script)

    def step(name: str, value: Any = None) -> None:
        result["steps"].append({"name": name, "at": round(time.time(), 3), "value": value})

    def wait_for(expression: str, timeout: float = 45.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                value = js(f"Boolean({expression})")
                if value is True or value == "true":
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def snapshot() -> dict[str, Any]:
        raw = js("""JSON.stringify({
          mode: window.HephaestusStore ? HephaestusStore.mode : null,
          modeLabel: window.HephaestusStore ? HephaestusStore.modeLabel : null,
          label: window.HephaestusStore ? HephaestusStore.label : null,
          saving: window.HephaestusStore ? HephaestusStore.saving : null,
          error: window.HephaestusStore && HephaestusStore.lastError ? String(HephaestusStore.lastError.message || HephaestusStore.lastError) : null,
          conflict: window.HephaestusStore ? HephaestusStore.conflict : null,
          status: window.HephaestusStore && HephaestusStore.status ? HephaestusStore.status.data_mode : null,
          notes: window.HephaestusStore ? HephaestusStore.data.notes.map(n => ({id:n.id,title:n.title,html:n.html,fav:!!n.fav,trashed:!!n.trashed,tags:n.tags,revision:n.revision||0})) : [],
          tags: window.HephaestusStore ? HephaestusStore.data.tags : [],
          saveState: document.querySelector('#saveState') ? document.querySelector('#saveState').textContent : null,
          storage: document.querySelector('#storage') ? document.querySelector('#storage').innerText : null,
          modal: (() => { const back = [...document.querySelectorAll('.modal-back')].find(b => !b.hidden && b.querySelector('.modal')); return back ? back.querySelector('.modal').innerText : null; })(),
          list: document.querySelector('#list') ? document.querySelector('#list').innerText : null
        })""")
        return json.loads(raw)

    def record(name: str, extra: Any = None) -> dict[str, Any]:
        snap = snapshot()
        if extra is not None:
            snap["extra"] = extra
        result["ui"][name] = snap
        step(name, {"mode": snap["mode"], "label": snap["label"], "notes": len(snap["notes"]), "modal": bool(snap["modal"])})
        return snap

    def click(selector: str) -> bool:
        return bool(js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false; el.click(); return true; }})()"""))

    def set_value(selector: str, value: str) -> bool:
        return bool(js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false; el.value = {json.dumps(value)}; el.dispatchEvent(new Event('input', {{bubbles:true}})); return true; }})()"""))

    def set_html(selector: str, html: str) -> bool:
        return bool(js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return false; el.innerHTML = {json.dumps(html)}; el.dispatchEvent(new Event('input', {{bubbles:true}})); return true; }})()"""))

    def wait_idle(extra: float = 1.4) -> None:
        time.sleep(extra)
        wait_for("window.HephaestusStore && !HephaestusStore.saving", 60)
        time.sleep(0.35)

    def click_modal(label: str) -> bool:
        return bool(js(f"""(() => {{
          const modal = document.querySelector('.modal-back:not([hidden]) .modal'); if (!modal) return false;
          const button = [...modal.querySelectorAll('footer button')].find(b => b.textContent.trim() === {json.dumps(label)});
          if (!button) return false; button.click(); return true;
        }})()"""))

    def create_note(title: str, html: str) -> None:
        click("#newBar")
        set_value("#title", title)
        set_html("#content", html)
        wait_idle()

    def select_note(title: str) -> bool:
        click("#backBtn")
        return bool(js(f"""(() => {{
          const card = [...document.querySelectorAll('.note-card')].find(c => c.querySelector('h3') && c.querySelector('h3').textContent.includes({json.dumps(title)}));
          if (!card) return false; card.click(); return true;
        }})()"""))

    def server_notes() -> list[dict[str, Any]]:
        status, payload = api(url, "/api/v2/notes?page=1&page_size=100&trashed=false")
        if status != 200:
            return []
        return payload.get("items", []) if isinstance(payload, dict) else []

    def server_note(title: str) -> dict[str, Any] | None:
        for note in server_notes():
            if title in (note.get("title") or ""):
                return note
        return None

    def server_legacy_notes() -> list[dict[str, Any]]:
        status, payload = api(url, "/api/state")
        if status != 200 or not isinstance(payload, dict):
            return []
        state = payload.get("state") or {}
        return state.get("notes", []) if isinstance(state, dict) else []

    def driver() -> None:
        try:
            if not wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60):
                result["error"] = "UI did not initialize"
                return
            time.sleep(0.4)
            record("initial")

            if phase == "reopen":
                expected = "B2 v2 已编辑" if mode == "v2" else "B2 legacy 已编辑"
                found = any(expected in (n.get("title") or "") for n in snapshot()["notes"])
                result["reopen"] = {"expected": expected, "found": found}
                step("reopen_verify", found)
                return

            if mode in ("legacy", "pending", "failed"):
                create_note("B2 legacy 新建", "<p>legacy 内容</p>")
                edited = set_value("#title", "B2 legacy 已编辑")
                step("legacy_title_edited", edited)
                wait_idle()
                record("after_create_edit")
                click("#favBtn")
                wait_idle()
                record("after_favorite")
                click("#tagManageBtn")
                if wait_for("document.querySelector('#ntName')", 5):
                    set_value("#ntName", "旧版标签")
                    click("#ntAdd")
                    time.sleep(0.3)
                    click_modal("完成")
                wait_idle()
                record("after_tag")
                click("#delBtn")
                wait_idle()
                record("after_trash")
                click("[data-view='trash']")
                time.sleep(0.3)
                restored = bool(js("""(() => { const c = [...document.querySelectorAll('.note-card')].find(x => x.innerText.includes('B2 legacy 已编辑')); if (!c) return false; const b = c.querySelector('[data-act="restore"]'); if (!b) return false; b.click(); return true; })()"""))
                step("legacy_restore_clicked", restored)
                wait_idle()
                click("[data-view='all']")
                wait_idle()
                record("after_restore")
                result["http"]["legacy_state"] = api(url, "/api/state")
                result["http"]["v2_status"] = api(url, "/api/v2/status")
                result["http"]["v2_notes"] = api(url, "/api/v2/notes?page=1&page_size=100")
                result["http"]["legacy_note_present"] = any("B2 legacy 已编辑" in (n.get("title") or "") for n in server_legacy_notes())
                js("location.reload(); true")
                time.sleep(2.5)
                wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60)
                wait_idle(0.8)
                record("after_refresh")
                result["refresh_found"] = any("B2 legacy 已编辑" in (n.get("title") or "") for n in snapshot()["notes"])
                return

            # v2 mode: real CRUD through the UI.
            create_note("B2 v2 新建", "<p>v2 内容</p>")
            record("after_create")
            set_value("#title", "B2 v2 已编辑")
            wait_idle()
            record("after_edit")
            js("HephaestusStore.flush(); HephaestusStore.flush(); true")
            wait_idle()
            record("after_duplicate_submit")
            click("#favBtn")
            wait_idle()
            record("after_favorite")
            click("#tagManageBtn")
            if wait_for("document.querySelector('#ntName')", 5):
                set_value("#ntName", "B2标签")
                click("#ntAdd")
                time.sleep(0.3)
                click_modal("完成")
            wait_idle()
            if select_note("B2 v2 已编辑"):
                click("#editTagsBtn")
                if wait_for("document.querySelector('.modal-back:not([hidden]) .chip[data-t]')", 5):
                    js("""(() => { const b = [...document.querySelectorAll('.modal-back:not([hidden]) .chip[data-t]')].find(x => x.textContent.includes('B2标签')); if (b) b.click(); return true; })()""")
                    click_modal("完成")
            wait_idle()
            record("after_tag")
            result["http"]["v2_note_after_tag"] = server_note("B2 v2 已编辑")
            select_note("B2 v2 已编辑")
            click("#delBtn")
            wait_idle()
            record("after_trash")
            click("[data-view='trash']")
            time.sleep(0.3)
            restored = bool(js("""(() => { const c = [...document.querySelectorAll('.note-card')].find(x => x.innerText.includes('B2 v2 已编辑')); if (!c) return false; const b = c.querySelector('[data-act="restore"]'); if (!b) return false; b.click(); return true; })()"""))
            step("v2_restore_clicked", restored)
            wait_idle()
            click("[data-view='all']")
            wait_idle()
            record("after_restore")
            result["http"]["v2_note_after_restore"] = server_note("B2 v2 已编辑")

            # Conflict: change the selected note locally, then on the server, then again locally.
            if not select_note("本地优先测试"):
                result["conflict"] = {"skipped": "note not found"}
            else:
                set_value("#title", "B2 冲突本地")
                wait_idle()
                target = server_note("B2 冲突本地") or server_note("本地优先测试")
                if target:
                    server_body = {"title": "B2 服务器更新", "revision": target["revision"]}
                    status, payload = api(url, "/api/v2/notes/" + target["id"], method="PATCH", body=server_body)
                    step("server_conflict_patch", {"status": status, "revision": payload.get("revision") if isinstance(payload, dict) else None})
                    set_value("#title", "B2 冲突最终")
                    time.sleep(1.0)
                    modal_seen = wait_for("(() => { const m = document.querySelector('.modal-back:not([hidden]) .modal'); return !!m && m.innerText.includes('检测到编辑冲突'); })()", 20)
                    record("conflict_modal")
                    result["conflict"] = {"modal_seen": modal_seen, "modal_text": snapshot()["modal"]}
                    if modal_seen:
                        result["conflict"]["choose_mine"] = click_modal("保留我的修改")
                        wait_idle(0.8)
                        result["http"]["v2_note_after_conflict"] = server_note("B2 冲突最终")
                        record("after_conflict")

            # Save failure: stop the backend, edit, prove local content survives, restart, retry.
            before_failure = server_note("B2 v2 已编辑") or server_note("B2 冲突最终")
            original_proc = proc_holder["proc"]
            old_port = int(url.rsplit(":", 1)[1])
            stop_server(original_proc)
            step("server_stopped_for_failure", True)
            set_value("#title", "B2 断网本地保留")
            started = wait_for("HephaestusStore.saving === true", 8)
            failure_seen = wait_for("HephaestusStore.lastError != null && !HephaestusStore.saving", 30)
            step("save_failure_started", started)
            step("save_failure_observed", failure_seen)
            record("after_save_failure")
            result["save_failure"] = {
                "started": started,
                "failure_seen": failure_seen,
                "error": snapshot()["error"],
                "label": snapshot()["label"],
                "local_title": any("B2 断网本地保留" in (n.get("title") or "") for n in snapshot()["notes"]),
            }
            proc_holder["proc"], new_url = start_server(db, log_path, old_port)
            step("server_restarted", new_url)
            js("HephaestusStore.retry(); true")
            time.sleep(2.0)
            wait_idle(2.0)
            record("after_retry")
            result["http"]["v2_note_after_retry"] = server_note("B2 断网本地保留")
            result["http"]["v2_note_before_failure"] = before_failure

            window.load_url(url + "/?desktop=1&refresh=" + str(time.time()))
            time.sleep(2.5)
            wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60)
            wait_idle(0.8)
            record("after_refresh")
            result["refresh_found"] = any("B2 断网本地保留" in (n.get("title") or "") for n in snapshot()["notes"])
            result["http"]["v2_status"] = api(url, "/api/v2/status")

        except Exception as exc:
            result["error"] = repr(exc)
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    webview.start(driver, gui="edgechromium", debug=False, private_mode=False)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["legacy", "v2", "pending", "failed"], required=True)
    parser.add_argument("--phase", choices=["main", "reopen"], default="main")
    parser.add_argument("--root", default=None)
    args = parser.parse_args()

    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="heph-b2-ui-"))
    root.mkdir(parents=True, exist_ok=True)
    db = root / f"{args.mode}.db"
    builders = {"legacy": build_legacy, "v2": build_v2, "pending": build_pending, "failed": build_failed}
    if args.phase == "reopen":
        if not db.exists():
            raise SystemExit(f"reopen 需要一个已存在的数据库：{db}")
    else:
        builders[args.mode](db)
    log_path = root / f"server-{args.mode}.log"
    proc_holder: dict[str, Any] = {}
    proc_holder["proc"], url = start_server(db, log_path)
    try:
        result = run_ui(url, args.mode, args.phase, db, proc_holder, log_path)
    finally:
        stop_server(proc_holder["proc"])
    result["root"] = str(root)
    result["db"] = str(db)
    result["log"] = str(log_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
