#!/usr/bin/env python3
import os
import sys
import re
import html
import glob
import fcntl
import urllib.parse
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks_m1.parser import parse_dump as parse_dump_m1
from tasks_m1.evidence import find_evidence as find_evidence_m1
from variants_m1.loader import list_variants as list_variants_m1, VARIANTS_DIR as VAR_DIR_M1

from tasks_m2.parser import parse_dump as parse_dump_m2
from tasks_m2.evidence import find_evidence as find_evidence_m2
from variants_m2.loader import list_variants as list_variants_m2, VARIANTS_DIR as VAR_DIR_M2

PORT = 8080
ROOT = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = "/tmp/collector.lock"

lock = threading.Lock()
state = {"running": False, "mod": "m1", "pool": None, "variant": "default", "html": None}

JS_MAIN = """
function collapseOk(){
  document.querySelectorAll('details.sub').forEach(function(d){
    var s=d.querySelector('summary');
    if(s&&s.classList.contains('ln-ok'))d.open=false;
  });
}
function scrollBottom(){window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'});}
function toggleVarMenu(e){
  e.stopPropagation();
  var m=document.getElementById('varMenu');
  m.style.display=(m.style.display==='block')?'none':'block';
}
function selectVariant(name){
  document.getElementById('varInput').value=name;
  document.getElementById('varLabel').textContent=name;
  document.getElementById('varMenu').style.display='none';
}
document.addEventListener('click',function(){
  var m=document.getElementById('varMenu');
  if(m)m.style.display='none';
});
var btn=document.getElementById('checkBtn');
if(btn){btn.addEventListener('click',function(){this.disabled=true;this.textContent='Проверка...'});}
"""

JS_COUNTDOWN = """
let t=30;
setInterval(function(){t--;if(t>=0)document.getElementById('countdown').textContent=t},1000);
"""


def get_mod_cfg(mod):
    if mod == "m2":
        return {
            "label": "Модуль 2", "collector": "collector_m2.py", "checker": "check_m2.py",
            "list_vars": list_variants_m2, "var_dir": VAR_DIR_M2,
            "parser": parse_dump_m2, "evidence": find_evidence_m2,
        }
    return {
        "label": "Модуль 1", "collector": "collector_m1.py", "checker": "check_m1.py",
        "list_vars": list_variants_m1, "var_dir": VAR_DIR_M1,
        "parser": parse_dump_m1, "evidence": find_evidence_m1,
    }


def render_variant_dropdown(mod, selected):
    variants = get_mod_cfg(mod)["list_vars"]()
    if selected not in variants:
        selected = variants[0]
    items = []
    for v in variants:
        ev = html.escape(v)
        active = ' style="background:#1e293b"' if v == selected else ""
        items.append(
            f'<div class="v-item"{active}>'
            f'<span class="v-name" onclick="selectVariant(\'{ev}\')">{ev}</span>'
            f'<a class="v-edit" href="/edit?mod={mod}&v={urllib.parse.quote(v)}" onclick="event.stopPropagation()">edit</a>'
            f'</div>'
        )
    items.append(f'<div class="v-item v-new"><a class="v-new-link" href="/new?mod={mod}" onclick="event.stopPropagation()">+ Создать новый вариант</a></div>')
    return (
        f'<input type="hidden" name="variant" id="varInput" value="{html.escape(selected)}">'
        f'<div class="v-wrap"><div class="v-btn" onclick="toggleVarMenu(event)">'
        f'<span>Вариант ({mod.upper()}): <b id="varLabel">{html.escape(selected)}</b></span><span>▾</span></div>'
        f'<div class="v-menu" id="varMenu">{"".join(items)}</div></div>'
    )


def page(body, mod="m1", pool="", variant="default", meta=""):
    m1_cls = "mod-tab active" if mod == "m1" else "mod-tab"
    m2_cls = "mod-tab active" if mod == "m2" else "mod-tab"
    tabs = (
        f'<div class="mod-tabs">'
        f'<a href="/?mod=m1" class="{m1_cls}">Модуль 1 (Сеть и базовые службы)</a>'
        f'<a href="/?mod=m2" class="{m2_cls}">Модуль 2 (Домен, хранилище и сервисы)</a></div>'
    )
    return (TPL.replace("__META__", meta).replace("__TABS__", tabs).replace("__MOD__", html.escape(mod))
            .replace("__POOL__", html.escape(pool)).replace("__VAR_DROPDOWN__", render_variant_dropdown(mod, variant))
            .replace("__BODY__", body).replace("__JS__", JS_MAIN))


TPL = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">__META__
<title>Проверка стенда de2027</title>
<style>
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}
h1{color:#7eb8ff;margin-bottom:6px}.sub{color:#8a8f98;margin-bottom:18px;font-size:14px}
.mod-tabs{display:flex;gap:10px;margin-bottom:16px}
.mod-tab{padding:9px 18px;border-radius:6px;background:#1a1d24;color:#9ca3af;text-decoration:none;font-weight:600;font-size:14px;border:1px solid #2a2d35}
.mod-tab:hover{color:#fff;border-color:#3b82f6}.mod-tab.active{background:#1e3a8a;color:#fff;border-color:#3b82f6}
.form{background:#1a1d24;padding:18px;border-radius:8px;margin-bottom:22px;border:1px solid #2a2d35}
.form-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
input[type=text]{background:#0f1115;color:#e6e6e6;border:1px solid #2a2d35;padding:10px 14px;border-radius:6px;font-size:15px;width:240px}
button,.btn{background:#2563eb;color:#fff;border:0;padding:10px 20px;border-radius:6px;font-size:15px;cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
button:hover,.btn:hover{background:#1d4ed8}button:disabled{background:#374151;cursor:not-allowed}
.btn-sec{background:#374151;color:#e6e6e6}.btn-sec:hover{background:#4b5563}
.v-wrap{position:relative;display:inline-block;min-width:230px}
.v-btn{background:#0f1115;color:#e6e6e6;border:1px solid #2a2d35;padding:10px 14px;border-radius:6px;font-size:15px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:14px;user-select:none}
.v-btn:hover{border-color:#3b82f6}
.v-menu{display:none;position:absolute;top:calc(100% + 4px);left:0;min-width:100%;background:#161920;border:1px solid #2a2d35;border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,.6);z-index:1000;overflow:hidden}
.v-item{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid #232730}
.v-item:last-child{border-bottom:0}.v-item:hover{background:#222630}
.v-name{cursor:pointer;flex:1;color:#e6e6e6;font-size:14px}
.v-edit{color:#7eb8ff;font-size:12px;text-decoration:none;padding:2px 8px;border:1px solid #2563eb;border-radius:4px;margin-left:10px}
.v-edit:hover{background:#2563eb;color:#fff}.v-new-link{color:#6ee7b7;font-size:13px;text-decoration:none;width:100%}
.editor-box{background:#1a1d24;padding:20px;border-radius:8px;border:1px solid #2a2d35;max-width:860px}
textarea.nano{width:100%;height:420px;background:#0b0d11;color:#d1d5db;border:1px solid #2a2d35;border-radius:6px;padding:14px;font-family:Menlo,Consolas,monospace;font-size:13px;line-height:1.5;box-sizing:border-box;resize:vertical}
details{background:#1a1d24;border-radius:8px;margin-bottom:12px;border:1px solid #2a2d35}
summary{padding:13px 16px;cursor:pointer;font-weight:600;list-style:none;display:flex;justify-content:space-between;align-items:center}
summary::-webkit-details-marker{display:none}summary:hover{background:#22252d}
.badge{padding:3px 10px;border-radius:12px;font-size:12px;font-weight:700}
.b-ok{background:#065f46;color:#6ee7b7}.b-fail{background:#7f1d1d;color:#fca5a5}.b-mix{background:#78350f;color:#fcd34d}
.content{padding:4px 14px 12px}.ln-ok{color:#6ee7b7}.ln-fail{color:#fca5a5}.ln-info{color:#9ca3af}
details.sub{background:#12151b;border:1px solid #232730;border-radius:6px;margin:4px 0}
details.sub summary{padding:6px 10px;font-family:Menlo,Consolas,monospace;font-size:12px;font-weight:400;list-style:none;display:block}
details.sub summary::-webkit-details-marker{display:none}details.sub summary::before{content:"▸ ";color:#4b5563}
details.sub[open] summary::before{content:"▾ ";color:#7eb8ff}details.sub summary:hover{background:#181c23}
details.sub pre{margin:0;padding:10px 12px;background:#0b0d11;color:#c9d1d9;font-size:12px;line-height:1.5;overflow-x:auto;white-space:pre;border-top:1px solid #232730}
.dump-pre{margin:0;padding:12px;background:#0b0d11;color:#c9d1d9;font-size:12px;line-height:1.45;overflow-x:auto;white-space:pre;border-radius:6px;border:1px solid #232730;max-height:600px;overflow-y:auto}
.total{background:#1a1d24;padding:16px 20px;border-radius:8px;margin-top:18px;font-size:16px;font-weight:600;border:1px solid #2a2d35}
.big-ok{color:#6ee7b7}.big-fail{color:#fca5a5}
.error{background:#7f1d1d;color:#fecaca;padding:16px;border-radius:8px;white-space:pre-wrap;font-family:monospace;margin-bottom:14px}
.wait{text-align:center;padding:40px;color:#8a8f98;font-size:16px}
.wait-msg{background:#1a1d24;padding:20px;border-radius:8px;margin:20px 0;border:1px solid #2a2d35}
.spin{display:inline-block;width:18px;height:18px;border:3px solid #2a2d35;border-top-color:#2563eb;border-radius:50%;animation:sp .8s linear infinite;vertical-align:middle;margin-right:10px}
@keyframes sp{to{transform:rotate(360deg)}}.timer{font-size:24px;color:#7eb8ff;font-weight:700;margin:10px 0}
footer{margin-top:36px;color:#4b5563;font-size:12px;text-align:center}
.fab{position:fixed;right:18px;bottom:18px;display:flex;gap:10px;z-index:999}
.fab button{background:#2563eb;color:#fff;border:0;border-radius:20px;padding:10px 16px;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.45)}
</style></head><body>
<h1>Проверка экзаменационного стенда</h1>
<div class="sub">de2027 · chkstset · клик по строке — раскроет доказательство из конфига</div>
__TABS__
<div class="form"><form method="POST" action="/check" class="form-row">
<input type="hidden" name="mod" value="__MOD__">
<input type="text" name="pool" placeholder="Имя пула" required value="__POOL__">
__VAR_DROPDOWN__
<button type="submit" id="checkBtn">Проверить</button></form></div>
__BODY__
<div class="fab"><button onclick="collapseOk()">▼ Свернуть [OK]</button><button onclick="scrollBottom()">↓ Вниз</button></div>
<script>__JS__</script>
<footer>Сбор данных ~2-3 мин · Python stdlib · localhost:8080</footer>
</body></html>"""


def is_collector_busy():
    try:
        lf = open(LOCK_FILE, "r")
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        lf.close()
        return False
    except BlockingIOError:
        return True
    except FileNotFoundError:
        return False


def run_check(mod, pool, variant):
    cfg = get_mod_cfg(mod)
    coll_cmd = [sys.executable, cfg["collector"], pool]
    if mod == "m1":
        coll_cmd.append("latest")
    coll_cmd.extend(["--variant", variant])
    coll = subprocess.run(coll_cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    if coll.returncode != 0:
        return f"[ОШИБКА СБОРА {cfg['collector']}]\n" + (coll.stderr or coll.stdout), "", coll.returncode
    chk = subprocess.run([sys.executable, cfg["checker"], pool, "--offline", "--variant", variant],
                         cwd=ROOT, capture_output=True, text=True, timeout=300)
    return chk.stdout, chk.stderr, chk.returncode


def parse_check_output(text):
    sections, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^\s*>>>\s+(.+?)\s+\[(\d+)/(\d+)\]", line)
        if m:
            if cur:
                sections.append(cur)
            cur = {"title": m.group(1), "ok": int(m.group(2)), "all": int(m.group(3)), "lines": []}
        elif cur and line.strip():
            cur["lines"].append(line.strip())
    if cur:
        sections.append(cur)
    return sections


def render_result(mod, pool, variant, stdout, stderr, rc, machines, dump_text=""):
    cfg = get_mod_cfg(mod)
    if rc != 0 or not stdout.strip():
        err = html.escape((stderr or stdout or "Неизвестная ошибка").strip())[:4000]
        return page('<div class="error">[ОШИБКА ПРОВЕРКИ]\n' + err + '</div>', mod=mod, pool=pool, variant=variant)
    sections = parse_check_output(stdout)
    if not sections:
        return page('<div class="error">Не удалось разобрать вывод проверки.</div>', mod=mod, pool=pool, variant=variant)
    total_ok = sum(s["ok"] for s in sections)
    total_all = sum(s["all"] for s in sections)
    parts = []
    for s in sections:
        b_cls = "b-ok" if s["ok"] == s["all"] else ("b-fail" if s["ok"] == 0 else "b-mix")
        badge = f'<span class="badge {b_cls}">{s["ok"]}/{s["all"]}</span>'
        rows = []
        for ln in s["lines"]:
            e = html.escape(ln)
            cls = "ln-ok" if "[OK]" in ln else ("ln-fail" if "[FAIL]" in ln else "ln-info")
            try:
                ev = cfg["evidence"](ln, machines)
            except Exception:
                ev = ""
            if ev:
                rows.append(f'<details class="sub"><summary class="{cls}">{e}</summary><pre>{ev}</pre></details>')
            else:
                rows.append(f'<div class="{cls}" style="padding:4px 10px;font-family:monospace;font-size:12px">{e}</div>')
        parts.append(f'<details open><summary>{html.escape(s["title"])} {badge}</summary><div class="content">{"".join(rows)}</div></details>')
    pct = (100 * total_ok // total_all) if total_all else 0
    parts.append(
        f'<div class="total"><b>{cfg["label"]}</b> · Пул <b>{html.escape(pool)}</b> (вариант <b>{html.escape(variant)}</b>): '
        f'<span class="big-ok">{total_ok} OK</span> / <span class="big-fail">{total_all - total_ok} FAIL</span> из {total_all} ({pct}%)</div>'
    )
    if dump_text:
        parts.append(
            f'<details style="margin-top:16px"><summary style="color:#7eb8ff">📄 Полный дамп (latest_{html.escape(pool)}.txt)'
            f'<span class="badge" style="background:#1f2937;color:#9ca3af">{len(dump_text.splitlines())} строк</span></summary>'
            f'<div class="content"><pre class="dump-pre">{html.escape(dump_text)}</pre></div></details>'
        )
    return page("".join(parts), mod=mod, pool=pool, variant=variant)


def render_editor(mod, vname, content, error_msg=""):
    err_html = f'<div class="error">{html.escape(error_msg)}</div>' if error_msg else ""
    body = (
        f'<div class="editor-box"><h2 style="margin-top:0;color:#7eb8ff">Редактирование ({mod.upper()}): {html.escape(vname)}.py</h2>{err_html}'
        f'<form method="POST" action="/save"><input type="hidden" name="mod" value="{html.escape(mod)}">'
        f'<input type="hidden" name="vname" value="{html.escape(vname)}">'
        f'<textarea name="content" class="nano" spellcheck="false">{html.escape(content)}</textarea>'
        f'<div style="margin-top:14px;display:flex;gap:12px"><button type="submit">Сохранить</button>'
        f'<a href="/?mod={html.escape(mod)}" class="btn btn-sec">Отмена</a></div></form></div>'
    )
    return page(body, mod=mod, pool=state["pool"] or "", variant=vname)


def worker(mod, pool, variant):
    cfg = get_mod_cfg(mod)
    try:
        out, err, rc = run_check(mod, pool, variant)
        dump_file = os.path.join(ROOT, "dumps", pool, f"latest_{pool}.txt")
        dump_text = ""
        if os.path.isfile(dump_file):
            with open(dump_file, "r", encoding="utf-8") as df:
                dump_text = df.read()
        machines = cfg["parser"](dump_file) if os.path.isfile(dump_file) else {}
        state["html"] = render_result(mod, pool, variant, out, err, rc, machines, dump_text=dump_text)
    except Exception as e:
        state["html"] = page('<div class="error">Исключение: ' + html.escape(str(e)) + '</div>', mod=mod, pool=pool, variant=variant)
    finally:
        state["running"] = False
        lock.release()


def busy_page(mod, pool, variant):
    body = (
        f'<div class="wait-msg"><div style="font-size:20px;color:#fca5a5;margin-bottom:10px">⏳ Проверка уже выполняется</div>'
        f'<div style="color:#9ca3af">Сейчас идёт проверка пула <b>{html.escape(pool or "неизвестно")}</b>.</div>'
        f'<div class="timer" id="countdown">30</div><div style="color:#9ca3af">Обновится автоматически через ~30 сек.</div>'
        f'</div><script>{JS_COUNTDOWN}</script>'
    )
    return page(body, mod=mod, pool=pool, variant=variant, meta='<meta http-equiv="refresh" content="30">')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        mod = "m2" if qs.get("mod", [state["mod"]])[0] == "m2" else "m1"
        cfg = get_mod_cfg(mod)

        if parsed.path in ("/", "", "/check"):
            self._send(page("", mod=mod, pool=state["pool"] or "", variant=qs.get("v", ["default"])[0]))
        elif parsed.path == "/edit":
            vname = re.sub(r"[^a-zA-Z0-9_-]", "", qs.get("v", ["default"])[0])
            fpath = os.path.join(cfg["var_dir"], f"{vname}.py")
            if not os.path.isfile(fpath):
                self._send("<h1>Вариант не найден</h1>", 404)
                return
            with open(fpath, "r", encoding="utf-8") as f:
                self._send(render_editor(mod, vname, f.read()))
        elif parsed.path == "/new":
            with open(os.path.join(cfg["var_dir"], "default.py"), "r", encoding="utf-8") as f:
                content = f.read()
            idx = len(cfg["list_vars"]()) + 1
            while os.path.exists(os.path.join(cfg["var_dir"], f"v{idx}.py")):
                idx += 1
            body = (
                f'<div class="editor-box"><h2 style="margin-top:0;color:#6ee7b7">Новый вариант ({mod.upper()})</h2>'
                f'<form method="POST" action="/save"><input type="hidden" name="mod" value="{mod}">'
                f'<div style="margin-bottom:12px"><label>Имя файла (без .py): </label>'
                f'<input type="text" name="vname" value="v{idx}" required></div>'
                f'<textarea name="content" class="nano" spellcheck="false">{html.escape(content)}</textarea>'
                f'<div style="margin-top:14px;display:flex;gap:12px"><button type="submit">Создать и сохранить</button>'
                f'<a href="/?mod={mod}" class="btn btn-sec">Отмена</a></div></form></div>'
            )
            self._send(page(body, mod=mod, pool=state["pool"] or "", variant="default"))
        elif parsed.path == "/status":
            if state["running"]:
                meta = '<meta http-equiv="refresh" content="2">'
                body = (f'<div class="wait"><span class="spin"></span>Идёт сбор данных и проверка ({state["mod"].upper()}) '
                        f'пула <b>{html.escape(state["pool"])}</b> (вариант <b>{html.escape(state["variant"])}</b>)...</div>')
                self._send(page(body, mod=state["mod"], pool=state["pool"], variant=state["variant"], meta=meta))
            elif state["html"]:
                self._send(state["html"])
            else:
                self._send(page("", mod=mod, pool=state["pool"] or "", variant=state["variant"]))
        else:
            self._send("<h1>404</h1>", 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", errors="ignore"))
        mod = "m2" if form.get("mod", ["m1"])[0] == "m2" else "m1"
        cfg = get_mod_cfg(mod)

        if self.path == "/save":
            vname = re.sub(r"[^a-zA-Z0-9_-]", "", form.get("vname", [""])[0])
            content = form.get("content", [""])[0].replace("\r\n", "\n")
            if not vname or vname in ("__init__", "loader"):
                self._send(render_editor(mod, vname or "invalid", content, "Недопустимое имя файла!"))
                return
            try:
                compile(content, f"{vname}.py", "exec")
            except SyntaxError as e:
                self._send(render_editor(mod, vname, content, f"Синтаксическая ошибка (строка {e.lineno}): {e.msg}"))
                return
            with open(os.path.join(cfg["var_dir"], f"{vname}.py"), "w", encoding="utf-8") as f:
                f.write(content)
            state["mod"], state["variant"] = mod, vname
            self.send_response(303)
            self.send_header("Location", f"/?mod={mod}&v={urllib.parse.quote(vname)}")
            self.end_headers()
            return

        if self.path != "/check":
            self._send("<h1>404</h1>", 404)
            return

        pool = form.get("pool", [""])[0].strip()
        variant = re.sub(r"[^a-zA-Z0-9_-]", "", form.get("variant", ["default"])[0]) or "default"
        if not pool:
            self._send("<h1>Пустое имя пула</h1>", 400)
            return
        if is_collector_busy() or not lock.acquire(blocking=False):
            self._send(busy_page(mod, pool, variant))
            return

        state.update({"running": True, "mod": mod, "pool": pool, "variant": variant, "html": None})
        threading.Thread(target=worker, args=(mod, pool, variant), daemon=True).start()
        meta = '<meta http-equiv="refresh" content="1; url=/status">'
        body = (f'<div class="wait"><span class="spin"></span>Запущена проверка ({mod.upper()}) пула '
                f'<b>{html.escape(pool)}</b> (вариант <b>{html.escape(variant)}</b>)...</div>')
        self._send(page(body, mod=mod, pool=pool, variant=variant, meta=meta))


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    print("Web server on http://0.0.0:" + str(PORT))
    Server(("0.0.0.0", PORT), Handler).serve_forever()
