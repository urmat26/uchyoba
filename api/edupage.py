# Импорт оценок из Edupage. Вход делает неофициальная библиотека edupage-api,
# а оценки читаются своим терпимым разбором: одна странная запись не ломает всё.
# Данные для входа берутся из тела запроса (форма на сайте) или из переменных окружения.
import json
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path


def read_grades(ep):
    url = "https://%s.edupage.org/znamky/" % ep.subdomain
    html = ep.session.get(url).content.decode("utf-8", "replace")
    marker = ".znamkyStudentViewer("
    if marker not in html:
        raise ValueError("На странице оценок нет данных (возможно, нужен другой вход)")
    rest = html.split(marker, 1)[1].lstrip()
    data, _ = json.JSONDecoder().raw_decode(rest)

    events = ((data.get("vsetkyUdalosti") or {}).get("edupage")) or {}
    names, out = {}, []
    # skip — сколько записей пропущено и по какой причине, чтобы можно было понять, что не импортировалось
    skip = {"bad": 0, "no_subject": 0, "no_data": 0, "not_number": 0}
    for g in data.get("vsetkyZnamky") or []:
        try:
            eid = str(g.get("udalostid") or "")
            if not eid:
                skip["bad"] += 1
                continue
            det = events.get(eid) or {}
            pid = det.get("PredmetID")
            if pid is None or pid == "vsetky":
                skip["no_subject"] += 1
                continue
            if pid not in names:
                try:
                    from edupage_api.dbi import DbiHelper
                    names[pid] = DbiHelper(ep).fetch_subject_name(int(pid)) or ""
                except Exception:
                    names[pid] = ""
            raw = (g.get("data") or "").strip()
            if not raw:
                skip["no_data"] += 1
                continue
            raw, _, tail = raw.partition(" (")
            comment = tail.rsplit(")", 1)[0] if tail else ""
            # Оценка бывает вида "0.44/1", "12", "12,5" — дробь "x/y" надёжнее всего,
            # из неё берём и балл, и максимум. Иначе максимум ищем в данных события.
            v, mx = None, None
            m = re.match(r"^([\d.,]+)\s*/\s*([\d.,]+)$", raw.strip())
            if m:
                v = m.group(1).replace(",", ".")
                mx = float(m.group(2).replace(",", "."))
            else:
                v = raw.strip().replace(",", ".")
            if mx is None:
                try:
                    t = str(det.get("p_typ_udalosti"))
                    if t == "2":
                        mx = float(det.get("p_vaha"))
                    elif t == "3":
                        mx = float(det.get("p_vaha_body"))
                except Exception:
                    mx = None
            if not re.match(r"^[\d.]+$", v):
                skip["not_number"] += 1
                continue
            mm = re.search(r"Модуль\s*(\d)", json.dumps([det, g], ensure_ascii=False))
            out.append({
                "eid": eid,
                "subject": names[pid] or ("Предмет " + str(pid)),
                "v": v,
                "max": mx,
                "mod": int(mm.group(1)) if mm else 0,
                "date": str(g.get("datum") or "")[:10],
                "note": det.get("p_meno") or comment or "",
            })
        except Exception:
            skip["bad"] += 1
    return out, skip


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
        grades, skip = read_grades(ep)
        # Лог для отладки: видно, сколько оценок прочиталось и как они выглядят
        print("Edupage: прочитано %d оценок, пропуски %s" % (len(grades), skip), flush=True)
        for g in grades[:6]:
            print("  пример: v=%r max=%r дата=%s предмет=%r заметка=%r" % (g["v"], g["max"], g["date"], g["subject"], g["note"]), flush=True)
        # Полная копия последнего импорта рядом с файлом (для отладки; на Vercel молча пропускается)
        try:
            (Path(__file__).parent / "_last_grades.json").write_text(
                json.dumps(grades, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass
        return 200, {"grades": grades, "skip": skip}
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
