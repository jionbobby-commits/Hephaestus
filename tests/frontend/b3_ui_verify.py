"""B3.5 real-copy UI acceptance for the V2 DataPort migration.

The harness never opens the user's database. It copies one already-migrated
SQLite file into a temporary directory, starts uvicorn against that copy and
drives the real pywebview/WebView2 UI.

Main phase:
  python tests/frontend/b3_ui_verify.py --db data/b3-drill/drill.db --root <temp>

Reopen phase (same root, after the main phase closed its window):
  python tests/frontend/b3_ui_verify.py --db data/b3-drill/drill.db --root <temp> --phase reopen

Output is JSON on stdout. Personal note titles are used only inside the process
and never included in the output.
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
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REAL_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "Hephaestus" / "hephaestus.db"
EDIT_MARK = " · B3验收"
TAG_NAME = "B3验收标签"
NEW_TITLE = "B3 验收新建"
PURGE_TITLE = "B3 永久删除验证"


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def start_server(db: Path, log_path: Path) -> tuple[subprocess.Popen[bytes], str]:
    port = free_port()
    url = "http://127.0.0.1:" + str(port)
    env = os.environ.copy()
    env["HEPHAESTUS_DATABASE_URL"] = "sqlite:///" + db.resolve().as_posix()
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
            proc.wait(timeout=8)
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


def db_check(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect("file:" + path.resolve().as_posix() + "?mode=ro", uri=True)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        notes = conn.execute("SELECT COUNT(*) FROM v2_notes").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM v2_notes WHERE is_trashed = 0").fetchone()[0]
        trashed = conn.execute("SELECT COUNT(*) FROM v2_notes WHERE is_trashed = 1").fetchone()[0]
        tags = conn.execute("SELECT COUNT(*) FROM v2_tags").fetchone()[0]
        note_tags = conn.execute("SELECT COUNT(*) FROM v2_note_tags").fetchone()[0]
        favorites = conn.execute("SELECT COUNT(*) FROM v2_notes WHERE is_favorite = 1").fetchone()[0]
        legacy_notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        state_rows = conn.execute("SELECT COUNT(*) FROM frontend_state").fetchone()[0]
        payload = conn.execute("SELECT payload FROM frontend_state WHERE id = 1").fetchone()
        raw_payload = payload[0] if payload and payload[0] is not None else b""
        if isinstance(raw_payload, str):
            raw_payload = raw_payload.encode("utf-8")
        payload_hash = hashlib.sha256(bytes(raw_payload)).hexdigest()
        return {
            "tables": tables,
            "integrity": integrity,
            "v2_notes": notes,
            "v2_active": active,
            "v2_trashed": trashed,
            "v2_tags": tags,
            "v2_note_tags": note_tags,
            "v2_favorites": favorites,
            "legacy_notes": legacy_notes,
            "frontend_state_rows": state_rows,
            "frontend_state_payload_sha256": payload_hash,
        }
    finally:
        conn.close()


def list_notes(url: str, trashed: bool) -> dict[str, Any]:
    status, payload = api(url, "/api/v2/notes?page=1&page_size=100&trashed=" + ("true" if trashed else "false"))
    return payload if status == 200 and isinstance(payload, dict) else {}


def get_note(url: str, note_id: str) -> dict[str, Any] | None:
    status, payload = api(url, "/api/v2/notes/" + urllib.parse.quote(note_id, safe=""))
    return payload if status == 200 and isinstance(payload, dict) else None


def get_tags(url: str) -> list[dict[str, Any]]:
    status, payload = api(url, "/api/v2/tags")
    return payload if status == 200 and isinstance(payload, list) else []


def find_note(url: str, title: str) -> dict[str, Any] | None:
    for trashed in (False, True):
        for note in list_notes(url, trashed).get("items", []):
            if note.get("title") == title:
                return note
    return None


def run_ui(url: str, db: Path, phase: str) -> dict[str, Any]:
    import webview

    window = webview.create_window("Hephaestus B3 UI acceptance", url + "/?desktop=1", width=1280, height=900, hidden=True)
    result: dict[str, Any] = {"phase": phase, "steps": [], "checks": {}, "ui": {}, "http": {}}

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

    def snapshot() -> dict[str, Any]:
        raw = js("""JSON.stringify({
          mode: window.HephaestusStore ? HephaestusStore.mode : null,
          status: window.HephaestusStore && HephaestusStore.status ? HephaestusStore.status.data_mode : null,
          label: window.HephaestusStore ? HephaestusStore.label : null,
          saving: window.HephaestusStore ? HephaestusStore.saving : null,
          error: window.HephaestusStore && HephaestusStore.lastError ? String(HephaestusStore.lastError.message || HephaestusStore.lastError) : null,
          selected: window.HephaestusStore ? HephaestusStore.selected : null,
          notes: window.HephaestusStore ? HephaestusStore.data.notes.map(n => ({id:n.id,title:n.title,fav:!!n.fav,trashed:!!n.trashed,tags:n.tags,revision:n.revision||0})) : [],
          tags: window.HephaestusStore ? HephaestusStore.data.tags : [],
          modal: document.querySelector('.modal') ? document.querySelector('.modal').innerText : null,
          list: document.querySelector('#list') ? document.querySelector('#list').innerText : null,
          saveState: document.querySelector('#saveState') ? document.querySelector('#saveState').textContent : null
        })""")
        data = json.loads(raw)
        data["active"] = [n for n in data["notes"] if not n.get("trashed")]
        data["trashed"] = [n for n in data["notes"] if n.get("trashed")]
        return data

    def record(name: str) -> dict[str, Any]:
        snap = snapshot()
        result["ui"][name] = {
            "mode": snap["mode"], "status": snap["status"], "label": snap["label"],
            "active": len(snap["active"]), "trashed": len(snap["trashed"]),
            "tags": len(snap["tags"]), "saving": snap["saving"], "error": snap["error"],
        }
        step(name, result["ui"][name])
        return snap

    def click(selector: str) -> bool:
        return bool(js("(() => { const el = document.querySelector(" + json.dumps(selector) + "); if (!el) return false; el.click(); return true; })()"))

    def set_value(selector: str, value: str) -> bool:
        return bool(js("(() => { const el = document.querySelector(" + json.dumps(selector) + "); if (!el) return false; el.value = " + json.dumps(value) + "; el.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"))

    def set_html(selector: str, html: str) -> bool:
        return bool(js("(() => { const el = document.querySelector(" + json.dumps(selector) + "); if (!el) return false; el.innerHTML = " + json.dumps(html) + "; el.dispatchEvent(new Event('input', {bubbles:true})); return true; })()"))

    def click_modal(label: str) -> bool:
        return bool(js("(() => { const m = document.querySelector('.modal'); if (!m) return false; const b = [...m.querySelectorAll('footer button')].find(x => x.textContent.trim() === " + json.dumps(label) + "); if (!b) return false; b.click(); return true; })()"))

    def wait_idle(extra: float = 1.4) -> None:
        time.sleep(extra)
        wait_for("window.HephaestusStore && !HephaestusStore.saving", 60)
        time.sleep(0.35)

    def select_id(note_id: str) -> bool:
        click("#backBtn")
        click("[data-view='all']")
        time.sleep(0.3)
        return bool(js("(() => { const c = document.querySelector('.note-card[data-id=' + JSON.stringify(" + json.dumps(note_id) + ") + ']'); if (!c) return false; c.click(); return true; })()"))

    def click_card_action(note_id: str, action: str) -> bool:
        return bool(js("(() => { const c = document.querySelector('.note-card[data-id=' + JSON.stringify(" + json.dumps(note_id) + ") + ']'); if (!c) return false; const b = c.querySelector('[data-act=" + json.dumps(action) + "]'); if (!b) return false; b.click(); return true; })()"))

    def select_by_title(title: str) -> str | None:
        ids = [n["id"] for n in snapshot()["notes"] if (n.get("title") or "") == title]
        if not ids:
            return None
        return ids[0] if select_id(ids[0]) else None

    def create_note(title: str, html: str) -> None:
        click("#newBar")
        set_value("#title", title)
        set_html("#content", html)
        wait_idle()

    def driver() -> None:
        try:
            if not wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60):
                result["error"] = "UI did not initialize"
                return
            time.sleep(0.5)
            wait_idle(0.4)
            initial = record("initial")
            check("initial_mode_v2_ready", initial["mode"] == "v2_ready", initial["mode"])
            check("initial_status_v2_ready", initial["status"] == "v2_ready", initial["status"])
            check("initial_trashed_1", len(initial["trashed"]) == 1, len(initial["trashed"]))
            check("initial_label_saved", initial["label"] == "已保存", initial["label"])
            if phase == "main":
                check("initial_active_6", len(initial["active"]) == 6, len(initial["active"]))
                check("initial_tags_4", len(initial["tags"]) == 4, len(initial["tags"]))
            else:
                check("initial_reopen_active_7", len(initial["active"]) == 7, len(initial["active"]))
                check("initial_reopen_tags_5", len(initial["tags"]) == 5, len(initial["tags"]))

            if phase == "reopen":
                edited = [n for n in initial["active"] if (n.get("title") or "").endswith(EDIT_MARK)]
                new_note = [n for n in initial["notes"] if (n.get("title") or "") == NEW_TITLE]
                purged = [n for n in initial["notes"] if (n.get("title") or "") == PURGE_TITLE]
                tag_names = [t.get("name") for t in initial["tags"]]
                check("reopen_edited_note_present", len(edited) == 1, len(edited))
                check("reopen_new_note_present", len(new_note) == 1, len(new_note))
                check("reopen_purged_note_absent", len(purged) == 0, len(purged))
                check("reopen_tag_present", TAG_NAME in tag_names, tag_names)
                check("reopen_active_7", len(initial["active"]) == 7, len(initial["active"]))
                check("reopen_trashed_1", len(initial["trashed"]) == 1, len(initial["trashed"]))
                check("reopen_tags_5", len(initial["tags"]) == 5, len(initial["tags"]))
                if edited:
                    note = get_note(url, edited[0]["id"]) or {}
                    check("reopen_favorite_persisted", bool(note.get("is_favorite")), note.get("is_favorite"))
                    check("reopen_tag_assignment_persisted", any(t.get("name") == TAG_NAME for t in note.get("tags", [])), len(note.get("tags", [])))
                return

            active = list_notes(url, False).get("items", [])
            if not active:
                result["error"] = "no active notes in migrated copy"
                return
            target = active[0]
            target_id = target["id"]
            original_title = target.get("title") or ""
            if not select_id(target_id):
                result["error"] = "could not select the first migrated note"
                return
            time.sleep(0.4)
            edited_title = original_title + EDIT_MARK
            set_value("#title", edited_title)
            wait_idle()
            after_edit = record("after_edit")
            server_edited = get_note(url, target_id) or {}
            check("edit_title_saved", server_edited.get("title") == edited_title, bool(server_edited.get("title")))
            check("edit_label_saved", after_edit["label"] == "已保存", after_edit["label"])

            before_favorite = bool(server_edited.get("is_favorite"))
            if not before_favorite:
                click("#favBtn")
                wait_idle()
            after_favorite = record("after_favorite")
            server_favorite = get_note(url, target_id) or {}
            check("favorite_saved", bool(server_favorite.get("is_favorite")), before_favorite)
            check("favorite_label_saved", after_favorite["label"] == "已保存", after_favorite["label"])

            click("#editTagsBtn")
            if wait_for("document.querySelector('#nn')", 6):
                set_value("#nn", TAG_NAME)
                click("#nnAdd")
                time.sleep(0.4)
                click_modal("完成")
            wait_idle()
            after_tag = record("after_tag")
            server_tagged = get_note(url, target_id) or {}
            tag_names = [t.get("name") for t in server_tagged.get("tags", [])]
            all_tags = get_tags(url)
            check("tag_created", any(t.get("name") == TAG_NAME for t in all_tags), len(all_tags))
            check("tag_assigned", TAG_NAME in tag_names, len(tag_names))
            check("tag_label_saved", after_tag["label"] == "已保存", after_tag["label"])

            create_note(NEW_TITLE, "<p>B3 副本环境验收内容</p>")
            after_create = record("after_create")
            created = find_note(url, NEW_TITLE)
            check("create_saved", created is not None, len(after_create["active"]))
            check("create_active_7", len(after_create["active"]) == 7, len(after_create["active"]))

            if created:
                if not select_id(created["id"]):
                    result["error"] = "could not select the created note"
                    return
                click("#delBtn")
                wait_idle()
                after_trash = record("after_trash")
                trashed = get_note(url, created["id"]) or {}
                check("trash_saved", bool(trashed.get("is_trashed")), trashed.get("is_trashed"))
                check("trash_active_6", len(after_trash["active"]) == 6, len(after_trash["active"]))
                check("trash_trashed_2", len(after_trash["trashed"]) == 2, len(after_trash["trashed"]))

                click("[data-view='trash']")
                time.sleep(0.4)
                restored = click_card_action(created["id"], "restore")
                wait_idle()
                after_restore = record("after_restore")
                restored_note = get_note(url, created["id"]) or {}
                check("restore_clicked", restored, restored)
                check("restore_saved", not bool(restored_note.get("is_trashed")), restored_note.get("is_trashed"))
                check("restore_active_7", len(after_restore["active"]) == 7, len(after_restore["active"]))
                click("[data-view='all']")
                time.sleep(0.3)

            create_note(PURGE_TITLE, "<p>仅用于永久删除验收</p>")
            wait_idle()
            purge_note = find_note(url, PURGE_TITLE)
            check("purge_note_created", purge_note is not None, bool(purge_note))
            if purge_note:
                if not select_id(purge_note["id"]):
                    result["error"] = "could not select the purge note"
                    return
                click("#delBtn")
                wait_idle()
                click("[data-view='trash']")
                time.sleep(0.4)
                if not click_card_action(purge_note["id"], "purge"):
                    result["error"] = "could not click permanent delete in trash"
                    return
                wait_for("document.querySelector('.modal')", 8)
                confirmed = click_modal("永久删除")
                wait_idle()
                after_purge = record("after_purge")
                status, _ = api(url, "/api/v2/notes/" + urllib.parse.quote(purge_note["id"], safe=""))
                check("purge_confirmed", confirmed, confirmed)
                check("purge_server_404", status == 404, status)
                check("purge_active_7", len(after_purge["active"]) == 7, len(after_purge["active"]))
                check("purge_trashed_1", len(after_purge["trashed"]) == 1, len(after_purge["trashed"]))
                click("[data-view='all']")
                time.sleep(0.3)

            js("location.reload(); true")
            time.sleep(2.6)
            wait_for("document.readyState === 'complete' && window.HephaestusStore && HephaestusStore.status", 60)
            wait_idle(0.8)
            refreshed = record("after_refresh")
            check("refresh_mode", refreshed["mode"] == "v2_ready", refreshed["mode"])
            check("refresh_active_7", len(refreshed["active"]) == 7, len(refreshed["active"]))
            check("refresh_edited_present", any((n.get("title") or "").endswith(EDIT_MARK) for n in refreshed["active"]), len(refreshed["active"]))
            check("refresh_new_present", any((n.get("title") or "") == NEW_TITLE for n in refreshed["notes"]), len(refreshed["notes"]))
            check("refresh_purged_absent", all((n.get("title") or "") != PURGE_TITLE for n in refreshed["notes"]), len(refreshed["notes"]))
            check("refresh_label_saved", refreshed["label"] == "已保存", refreshed["label"])
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
    parser.add_argument("--db", required=True)
    parser.add_argument("--root", default=None)
    parser.add_argument("--phase", choices=["main", "reopen"], default="main")
    args = parser.parse_args()

    source = Path(args.db).resolve()
    root = Path(args.root).resolve() if args.root else Path(tempfile.mkdtemp(prefix="heph-b3-ui-"))
    root.mkdir(parents=True, exist_ok=True)
    target = root / "b3-ui.db"
    log_path = root / "server-b3.log"

    source_hash_before = digest(source)
    real_hash_before = digest(REAL_DB)
    if args.phase == "main":
        copy_sqlite(source, target)
    elif not target.exists():
        raise SystemExit("reopen requires the main phase database: " + str(target))

    proc, url = start_server(target, log_path)
    try:
        result = run_ui(url, target, args.phase)
    finally:
        stop_server(proc)

    result["root"] = str(root)
    result["db"] = str(target)
    result["log"] = str(log_path)
    result["source_sha256_before"] = source_hash_before
    result["source_sha256_after"] = digest(source)
    result["source_unchanged"] = source_hash_before == result["source_sha256_after"]
    result["real_db_sha256_before"] = real_hash_before
    result["real_db_sha256_after"] = digest(REAL_DB)
    result["real_db_unchanged"] = real_hash_before == result["real_db_sha256_after"]
    result["db_check"] = db_check(target)
    failed = [name for name, value in result.get("checks", {}).items() if not value.get("ok")]
    result["failed_checks"] = failed
    if failed and not result.get("error"):
        result["error"] = "failed checks: " + ", ".join(failed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
