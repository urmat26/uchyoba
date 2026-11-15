# Фото конспекта/доски/учебника -> структурированный конспект на русском + картинки с Wikimedia Commons.
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

UA = "study-helper/0.2 (personal study project)"
PROMPT = """Ты помощник школьника. На фото тетрадь, доска или страница учебника (текст может быть на русском, кыргызском или английском).
Прочитай всё и составь чёткий конспект ПО-РУССКИ (английские и кыргызские термины переведи и дай оригинал в скобках).
Не выдумывай то, чего нет на фото, но можно коротко пояснить сложное.
Верни ТОЛЬКО JSON без пояснений и без ```:
{"title":"тема","sections":[{"h":"заголовок блока","points":["короткий пункт","..."],"img":"запрос на английском для поиска схемы или иллюстрации на Wikimedia Commons или null"}],"terms":[{"w":"термин","d":"определение"}],"check":["вопрос для самопроверки","..."]}
Правила: 3-6 блоков, в каждом 2-6 коротких пунктов; img только там, где схема реально помогает (не больше 3 на весь конспект), запрос из 2-4 слов; 3-8 терминов; 3-5 вопросов."""


def http_json(url, data=None, headers=None, timeout=40):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def find_image(q):
    qs = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
        "gsrsearch": q + " filetype:bitmap|drawing", "gsrlimit": 4, "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata", "iiurlwidth": 700})
    try:
        d = http_json("https://commons.wikimedia.org/w/api.php?" + qs, headers={"User-Agent": UA}, timeout=10)
        for pg in sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda x: x.get("index", 99)):
            ii = (pg.get("imageinfo") or [{}])[0]
            if ii.get("mime", "").startswith("image/") and ii.get("thumburl"):
                md = ii.get("extmetadata") or {}
                strip = lambda k: re.sub(r"<[^>]+>", "", (md.get(k) or {}).get("value", ""))[:80]
                return {"url": ii["thumburl"], "page": ii.get("descriptionurl", ""),
                        "license": strip("LicenseShortName"), "author": strip("Artist")}
    except Exception:
        pass
    return None


def run(headers, body):
    need = os.environ.get("APP_PASSWORD")
    if need and headers.get("x-pass") != need:
        return 401, {"error": "Неверный пароль приложения"}
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return 500, {"error": "Не задан GROQ_API_KEY"}
    imgs = [i for i in (body.get("images") or []) if isinstance(i, str) and i.startswith("data:image/")][:4]
    if not imgs:
        return 400, {"error": "Нет фото"}
    content = [{"type": "text", "text": PROMPT + "\nПредмет: " + str(body.get("subject", ""))[:80]}]
    content += [{"type": "image_url", "image_url": {"url": i}} for i in imgs]
    payload = json.dumps({"model": os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
                          "temperature": 0.3, "max_tokens": 2200,
                          "messages": [{"role": "user", "content": content}]}).encode("utf-8")
    try:
        d = http_json("https://api.groq.com/openai/v1/chat/completions", payload,
                      {"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": UA})
        txt = d["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        return 502, {"error": "Groq: " + (msg or str(e.code))[:200]}
    except Exception as e:
        return 502, {"error": "Не удалось связаться с Groq (%s)" % type(e).__name__}
    try:
        a, b = txt.index("{"), txt.rindex("}")
        note = json.loads(txt[a:b + 1])
    except Exception:
        return 502, {"error": "Модель вернула не тот формат, попробуй ещё раз или другое фото"}
    for sec in note.get("sections", [])[:3 + 3]:
        q = sec.get("img")
        sec["image"] = find_image(q) if q and isinstance(q, str) else None
    return 200, {"note": note}


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
