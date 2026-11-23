"""Real-WebView2 check: edits made when data mode cannot be detected survive a refresh.

Scenario: the page is served, /api/v2/status returns 503, the user edits, then
the service recovers and the page is reloaded. The recovery journal must merge
the edit into v2_ready instead of the server snapshot silently replacing it.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.frontend.ui_fixtures import build_v2
from tests.frontend.ui_verify import api, free_port, start_server, stop_server


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None)
    args = parser.parse_args()
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="heph-b2-recovery-"))
    root.mkdir(parents=True, exist_ok=True)
    db = root / "recovery.db"
    build_v2(db)
    log_path = root / "server.log"
    proc_holder: dict[str, Any] = {}
    proc_holder["proc"], url = start_server(
        db, log_path, app_target="tests.frontend.status_fail_app:app"
    )
    result: dict[str, Any] = {"url": url, "steps": [], "ui": {}, "http": {}}

    import webview

    window = webview.create_window(
        "Hephaestus B2 recovery verification", url + "/?desktop=1",
        width=1280, height=900, hidden=True,
    )

    def js(script: str) -> Any:
        return window.evaluate_js(script)

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
          error: window.HephaestusStore && HephaestusStore.lastError ? String(HephaestusStore.lastError.message || HephaestusStore.lastError) : null,
          conflict: window.HephaestusStore ? HephaestusStore.conflict : null,
          initialized: window.HephaestusStore ? Boolean(HephaestusStore.status) : null,
          notes: window.HephaestusStore ? HephaestusStore.data.notes.map(n => ({id:n.id,title:n.title})) : [],
          journal: (() => { try { const raw = JSON.parse(localStorage.getItem('hephaestus.v2.pending')); return raw ? {reason: raw.reason, notes: raw.notes.length, base: Object.keys(raw.base || {}).length} : null; } catch { return null; } })()
        })""")
        return json.loads(raw)

    def record(name: str) -> dict[str, Any]:
        snap = snapshot()
        result["ui"][name] = snap
        result["steps"].append({"name": name, "at": round(time.time(), 3), "value": {
            "mode": snap["mode"], "label": snap["label"], "notes": len(snap["notes"]), "journal": snap["journal"],
        }})
        return snap

    def server_count() -> int:
        status, payload = api(url, "/api/v2/notes?page=1&page_size=100")
        return len(payload.get("items", [])) if status == 200 and isinstance(payload, dict) else -1

    def server_title(title: str) -> bool:
        status, payload = api(url, "/api/v2/notes?page=1&page_size=100")
        if status != 200 or not isinstance(payload, dict):
            return False
        return any(title in (n.get("title") or "") for n in payload.get("items", []))

    def driver() -> None:
        try:
            if not wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.mode === 'unknown'", 60):
                result["error"] = "UI did not initialize"
                return
            time.sleep(0.5)
            initial = record("initial_status_failed")
            result["initial_mode"] = initial["mode"]

            js("""(() => { const b = document.querySelector('#newBar'); if (b) b.click(); return true; })()""")
            js("""(() => {
              const title = document.querySelector('#title');
              title.value = 'B2 初始化失败恢复';
              title.dispatchEvent(new Event('input', {bubbles:true}));
              const content = document.querySelector('#content');
              content.innerHTML = '<p>状态接口失败期间写入，不能丢。</p>';
              content.dispatchEvent(new Event('input', {bubbles:true}));
              return true;
            })()""")
            time.sleep(0.8)
            js("HephaestusStore.flush(); true")
            time.sleep(0.4)
            after_edit = record("after_edit_while_unknown")
            result["edited_note_local"] = any("B2 初始化失败恢复" in n["title"] for n in after_edit["notes"])
            result["journal_written"] = after_edit["journal"]
            result["server_count_before_recovery"] = server_count()

            old_port = int(url.rsplit(":", 1)[1])
            stop_server(proc_holder["proc"])
            proc_holder["proc"], new_url = start_server(db, log_path, old_port)
            result["server_restarted_normal"] = new_url
            window.load_url(url + "/?desktop=1&recovery=" + str(time.time()))
            time.sleep(2.5)
            wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.mode === 'v2_ready'", 60)
            time.sleep(1.5)
            after_recovery = record("after_recovery_reload")
            result["recovered_mode"] = after_recovery["mode"]
            result["note_present_after_reload"] = any("B2 初始化失败恢复" in n["title"] for n in after_recovery["notes"])
            wait_for("!HephaestusStore.saving", 30)
            time.sleep(0.5)
            result["server_count_after_recovery"] = server_count()
            result["server_title_after_recovery"] = server_title("B2 初始化失败恢复")
            wait_for("!HephaestusStore.saving", 60)
            time.sleep(0.5)
            result["journal_after_sync"] = snapshot()["journal"]

            window.load_url(url + "/?desktop=1&recovery2=" + str(time.time()))
            time.sleep(2.5)
            wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.mode === 'v2_ready'", 60)
            time.sleep(1.0)
            final = record("after_second_reload")
            result["note_present_after_second_reload"] = any("B2 初始化失败恢复" in n["title"] for n in final["notes"])
            result["final_label"] = final["label"]
        except Exception as exc:
            result["error"] = repr(exc)
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    webview.start(driver, gui="edgechromium", debug=False, private_mode=False)
    stop_server(proc_holder["proc"])
    result["root"] = str(root)
    result["db"] = str(db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
