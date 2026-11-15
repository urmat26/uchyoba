# Импорт оценок из Edupage. Вход делает неофициальная библиотека edupage-api,
# а оценки читаются своим терпимым разбором: одна странная запись не ломает всё.
# Данные для входа берутся из тела запроса (форма на сайте) или из переменных окружения.
import json
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler


def read_grades(ep):
    url = "https://%s.edupage.org/znamky/" % ep.subdomain
    html = ep.session.get(url).content.decode("utf-8", "replace")
    marker = ".znamkyStudentViewer("
    if marker not in html:
        raise ValueError("На странице оценок нет данных (возможно, нужен другой вход)")
    rest = html.split(marker, 1)[1].lstrip()
    data, _ = json.JSONDecoder().raw_decode(rest)

    events = ((data.get("vsetkyUdalosti") or {}).get("edupage")) or {}
    names, out, bad = {}, [], 0
    for g in data.get("vsetkyZnamky") or []:
        try:
            eid = str(g.get("udalostid") or "")
            if not eid:
                continue
            det = events.get(eid) or {}
            pid = det.get("PredmetID")
            if pid is None or pid == "vsetky":
                continue
            if pid not in names:
                try:
                    from edupage_api.dbi import DbiHelper
                    names[pid] = DbiHelper(ep).fetch_subject_name(int(pid)) or ""
                except Exception:
                    names[pid] = ""
            raw = (g.get("data") or "").split(" (", 1)
            comment = raw[1].rsplit(")", 1)[0] if len(raw) > 1 else ""
            mx = None
            try:
                t = str(det.get("p_typ_udalosti"))
                if t == "2":
                    mx = float(det.get("p_vaha"))
                elif t == "3":
                    mx = float(det.get("p_vaha_body"))
            except Exception:
                mx = None
            m = re.search(r"Модуль\s*(\d)", json.dumps([det, g], ensure_ascii=False))
            out.append({
                "eid": eid,
                "subject": names[pid] or ("Предмет " + str(pid)),
                "v": raw[0].strip().replace(",", "."),
                "max": mx,
                "mod": int(m.group(1)) if m else 0,
                "date": str(g.get("datum") or "")[:10],
                "note": det.get("p_meno") or comment or "",
            })
        except Exception:
            bad += 1
    return out, bad


def run(headers, body):
    need = os.environ.get("APP_PASSWORD")
    if need and headers.get("x-pass") != need:
        return 401, {"error": "Неверный пароль приложения"}
    school = (body.get("school") or os.environ.get("EDUPAGE_SCHOOL") or "").strip()
    user = (body.get("user") or os.environ.get("EDUPAGE_USER") or "").strip()
    pw = body.get("pass") or os.environ.get("EDUPAGE_PASS") or ""
    if not (school and user and pw):
        return 400, {"error": "Нужны поддомен школы, логин и пароль"}
    try:
        from edupage_api import Edupage
        ep = Edupage()
        two_factor = ep.login(user, pw, school)
    except Exception as e:
        traceback.print_exc()
        return 502, {"error": "Вход не удался: %s: %s" % (type(e).__name__, str(e)[:200])}
    if two_factor is not None:
        return 502, {"error": "Для этого аккаунта включён двухфакторный вход, библиотека его не поддерживает"}
    try:
        grades, bad = read_grades(ep)
        return 200, {"grades": grades, "bad": bad}
    except Exception as e:
        traceback.print_exc()
        return 502, {"error": "Не удалось прочитать оценки: %s: %s" % (type(e).__name__, str(e)[:200])}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            body = {}
        code, obj = run(self.headers, body)
        out = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
