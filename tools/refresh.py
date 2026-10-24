#!/usr/bin/env python3
"""Family Activity Planner refresh script (Okinawa + Fukuoka–Beppu).

Fetches movie showtimes and events for Okinawa main island and writes
data/movies.json and data/events.json (plus a translation cache).

Never fabricates: every item comes from a source fetched in this run;
sources that fail are recorded with status "unavailable".

Usage (from repo root):  python3 tools/refresh.py
Requires: python3, requests, beautifulsoup4, and `node` (for Star Theaters payloads).
Optional env: MYMEMORY_EMAIL (raises free translation quota 5k->50k chars/day).
"""
import base64, datetime as dt, html, json, os, re, subprocess, sys, tempfile, time, traceback
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
JST = dt.timezone(dt.timedelta(hours=9))
NOW = dt.datetime.now(JST)
TODAY = NOW.date()
DAYS = [TODAY + dt.timedelta(days=i) for i in range(8)]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
S = requests.Session(); S.headers["User-Agent"] = UA

def log(*a): print(*a, file=sys.stderr, flush=True)
def iso(d): return d.isoformat()

# ---------------------------------------------------------------- translation
TCACHE_PATH = os.path.join(DATA, "translations.json")
try: TCACHE = json.load(open(TCACHE_PATH, encoding="utf-8"))
except Exception: TCACHE = {}
T_STATE = {"quota_hit": False, "chars": 0, "fails": 0}
T0 = time.time()
TR_BUDGET = float(os.environ.get("TRANSLATE_BUDGET_SEC", "330"))
def budget_ok(): return time.time() - T0 < TR_BUDGET and not T_STATE["quota_hit"]
JA_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

def _mm(chunk):
    params = {"q": chunk, "langpair": "ja|en"}
    if os.environ.get("MYMEMORY_EMAIL"): params["de"] = os.environ["MYMEMORY_EMAIL"]
    r = S.get("https://api.mymemory.translated.net/get", params=params, timeout=30)
    j = r.json()
    if j.get("quotaFinished") or "MYMEMORY WARNING" in str(j.get("responseData", {}).get("translatedText", "")):
        T_STATE["quota_hit"] = True; return None
    if str(j.get("responseStatus")) != "200": return None
    return html.unescape(j["responseData"]["translatedText"])

def tr(text):
    """Japanese -> English via MyMemory, cached. Returns None if unavailable."""
    if not text: return text
    text = text.strip()
    if not JA_RE.search(text): return text
    if text in TCACHE: return TCACHE[text]
    if T_STATE["quota_hit"] or T_STATE["fails"] > 5 or not budget_ok(): return None
    parts, cur = [], ""
    for sent in re.split(r"(?<=[。！？])", text):
        if len(cur) + len(sent) > 400 and cur: parts.append(cur); cur = ""
        while len(sent) > 400: parts.append(sent[:400]); sent = sent[400:]
        cur += sent
    if cur: parts.append(cur)
    out = []
    for p in parts:
        try: t = _mm(p)
        except Exception: t = None
        if t is None:
            T_STATE["fails"] += 1; return None
        out.append(t); T_STATE["chars"] += len(p); time.sleep(0.3)
    res = " ".join(out).strip()
    TCACHE[text] = res
    return res

# ---------------------------------------------------------------- helpers
SOURCES = []
def source(name, url, ok, note="", count=0):
    SOURCES.append({"name": name, "url": url, "status": "ok" if ok else "unavailable", "note": note, "items": count})

def fmt_note(ja_title, foreign=None):
    if "吹替" in ja_title or "（吹）" in ja_title: return "Japanese dub"
    if "日本語字幕" in ja_title: return "Japanese with Japanese subtitles"
    if "字幕" in ja_title or "《字》" in ja_title: return "Original language, Japanese subtitles (no English subs)"
    if foreign: return "Format not stated"
    return "Japanese (no English subtitles)"

def clean_title(t):
    t = re.sub(r"^\s*\d{1,2}/\d{1,2}（.）\s*", "", t)
    t = re.sub(r"[《（(〈][^》）)〉]*(字幕|吹替|字|吹)[^》）)〉]*[》）)〉]", "", t)
    t = re.sub(r"【[^】]*】", "", t)
    return t.strip(" ／/　")

# ---------------------------------------------------------------- Theater Donut
DONUT_URL = "https://theater-donut.com/"
def theater_donut():
    th = {"id": "donut", "name": "Theater Donut Okinawa", "name_ja": "シアタードーナツ・オキナワ",
          "area": "central", "city": "Okinawa City (Koza)", "featured": True, "url": DONUT_URL,
          "price": "¥1,500 adult / ¥1,100 students / ¥700 elementary; Wed ¥1,300",
          "notes": "Indie community cinema-café in Koza. Mostly Japanese films and documentaries (no English subtitles unless stated). Regular screenings are first-come, no reservations. Tel 070-5401-1072.",
          "movies": [], "status": "ok"}
    try:
        r = S.get(DONUT_URL, timeout=30); r.raise_for_status(); r.encoding = "utf-8"
        txt = re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser").get_text(" "))
        # grid: "11:00（10/22~11/4） 金子文子 何が私をこうさせたか（121分）"
        grid = re.findall(r"(\d{1,2}:\d{2})（(\d{1,2}/\d{1,2})[~〜～](\d{1,2}/\d{1,2})）\s*(.+?)（(\d+)分）", txt)
        blocks = {}
        for m in re.finditer(r"『([^』]+)』\s*【\s*上映期間\s*】(.*?)【\s*内容\s*】(.*?)(?=公式HP|本作は|宮島から君へ|$)", txt):
            title, periods, body = m.group(1).strip(), m.group(2), m.group(3).strip()
            pers = re.findall(r"(\d{1,2}/\d{1,2})\s*[~〜～]\s*(\d{1,2}/\d{1,2})\s*((?:[①②③④⑤]\s*\d{1,2}:\d{2}\s*)+)", periods)
            info = re.search(r"(\d{4})年(?:製作)?／(\d+)分(?:／([A-Z0-9+]+))?", body)
            blocks[title] = {"periods": [(a, b, re.findall(r"\d{1,2}:\d{2}", t)) for a, b, t in pers],
                             "synopsis": re.sub(r"\s*\d{4}年(?:製作)?／.*$", "", body).strip(),
                             "year": info.group(1) if info else None, "runtime": int(info.group(2)) if info else None,
                             "rating": info.group(3) if info and info.group(3) else None}
        def norm(s): return re.sub(r"（[^）]*）|[\s〜~～\-『』]", "", s).lower()
        def to_date(md):
            mth, d = map(int, md.split("/")); y = TODAY.year
            if mth < TODAY.month - 6: y += 1
            if mth > TODAY.month + 6: y -= 1
            return dt.date(y, mth, d)
        films = {}
        for t, a, b, title, mins in grid:
            f = films.setdefault(norm(title), {"title_ja": title.strip(), "runtime": int(mins), "slots": set()})
            f["slots"].add((a, b, t))
        for bt, bl in blocks.items():
            key = next((k for k in films if k == norm(bt) or k in norm(bt) or norm(bt) in k), None)
            f = films.setdefault(key or norm(bt), {"title_ja": bt, "runtime": bl["runtime"], "slots": set()})
            f["block"] = bl
            for a, b, times in bl["periods"]:
                for t in times: f["slots"].add((a, b, t))
        for f in films.values():
            shows = []
            for a, b, t in f["slots"]:
                try: d0, d1 = to_date(a), to_date(b)
                except Exception: continue
                for d in DAYS:
                    if d0 <= d <= d1:
                        h, mi = t.split(":"); shows.append({"date": iso(d), "time": f"{int(h):02d}:{mi}"})
            shows = sorted({(s["date"], s["time"]) for s in shows})
            if not shows: continue
            bl = f.get("block", {})
            syn_ja = bl.get("synopsis")
            th["movies"].append({
                "title": tr(f["title_ja"]) or f["title_ja"], "title_ja": f["title_ja"],
                "synopsis": tr(syn_ja) if syn_ja else None, "synopsis_ja": syn_ja,
                "runtime": f.get("runtime") or bl.get("runtime"), "rating": bl.get("rating"), "year": bl.get("year"),
                "format": "Japanese (no English subtitles unless stated)", "poster": None,
                "showtimes": [{"date": d, "time": t} for d, t in shows], "source": DONUT_URL})
        th["movies"].sort(key=lambda m: (m["showtimes"][0]["date"] + m["showtimes"][0]["time"]) if m["showtimes"] else "9")
        source("Theater Donut (theater-donut.com)", DONUT_URL, bool(th["movies"]), f"{len(blocks)} synopsis blocks parsed", len(th["movies"]))
        if not th["movies"]: th["status"] = "unavailable"
    except Exception as e:
        th["status"] = "unavailable"; th["error"] = str(e)
        source("Theater Donut (theater-donut.com)", DONUT_URL, False, str(e))
    return th

# ---------------------------------------------------------------- Star Theaters (Cinema Q, Rycom, Mihama, Southern, Palette, Plaza House)
STAR = "https://startheaters.jp"
STAR_META = {  # smart_theater_no -> metadata
    "p001": ("cinemaq", "Cinema Q", "Naha (Omoromachi, Naha Main Place area)", "south"),
    "p002": ("palette", "Cinema Palette", "Naha (Kumoji, Palette Kumoji 9F)", "south"),
    "p003": ("plazahouse", "Cinema Plaza House", "Okinawa City (Plaza House Shopping Center 3F)", "central"),
    "p004": ("southern", "Southern Plex", "Haebaru", "south"),
    "p005": ("mihama", "Mihama 7plex", "Chatan (American Village)", "central"),
    "p006": ("rycom", "Cinema Rycom", "Kitanakagusuku (AEON Mall Okinawa Rycom 4F)", "central"),
}
NODE_JS = r"""
const fs=require('fs');let out=null;
global.__NUXT_JSONP__=(p,f)=>{out=f.data?f.data[0]:f};
eval(fs.readFileSync(process.argv[2],'utf8'));
const d=out||{};const ms=(d.movies||[]).map(m=>{const a=m.attributes||{};
 const th=(a.thumbnail&&a.thumbnail.data&&a.thumbnail.data.attributes)||{};
 return {id:m.id,title:a.title,description:a.description,url:a.url,nos:(a.smart_theater_no_list||[]).map(x=>x.no),
   poster:(th.formats&&(th.formats.small||th.formats.medium)||th).url||null,
   directors:(a.directors||[]).map(x=>x.director),actors:(a.actors||[]).map(x=>x.name)}});
const t=(d.theater&&d.theater.attributes)||{};
process.stdout.write(JSON.stringify({no:t.smart_theater_no,name:t.name,movies:ms}));
"""

def star_payload(build, page_id):
    r = S.get(f"{STAR}/_nuxt/static/{build}/theaters/{page_id}/payload.js", timeout=60)
    if r.status_code != 200: return None
    r.encoding = "utf-8"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f: f.write(r.text); p = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f: f.write(NODE_JS); js = f.name
    try:
        out = subprocess.run(["node", js, p], capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout else None
    finally:
        os.unlink(p); os.unlink(js)

def star_theaters():
    theaters = []
    try:
        home = S.get(STAR + "/", timeout=30).text
        build = re.search(r"/_nuxt/static/(\d+)/", home).group(1)
    except Exception as e:
        for no, (tid, name, city, area) in STAR_META.items():
            theaters.append({"id": tid, "name": name, "area": area, "city": city, "status": "unavailable", "error": str(e), "movies": [], "url": STAR})
        source("Star Theaters (startheaters.jp)", STAR, False, f"build id: {e}"); return theaters
    found = {}
    for pid in range(1, 10):
        try:
            pl = star_payload(build, pid)
            if pl and pl.get("no") in STAR_META: found[pl["no"]] = (pid, pl)
        except Exception as e: log("star payload", pid, e)
    jobs = []
    for no, (pid, pl) in found.items():
        for m in pl["movies"]:
            for n in m["nos"]:
                for d in DAYS: jobs.append((no, m["id"], n, d))
    def fetch(job):
        no, mid, n, d = job
        try:
            r = S.get(f"{STAR}/schedule/data/{n}/{no}/{d.strftime('%Y%m%d')}.json", timeout=30)
            if r.status_code == 200 and r.text.startswith("{"): return job, r.json()
        except Exception: pass
        return job, None
    with ThreadPoolExecutor(16) as ex: results = list(ex.map(fetch, jobs))
    shows = {}  # (no, movie id) -> {variant title: set((date,time,screen))}
    for (no, mid, n, d), js in results:
        if not js: continue
        for hhmm, screens in js.items():
            for scr, ev in screens.items():
                if ev.get("eventStatus") not in (None, "EventScheduled"): continue
                st = dt.datetime.fromisoformat(ev["startDate"].replace("Z", "+00:00")).astimezone(JST)
                name = (ev.get("name") or {}); vt = name.get("ja", "")
                key = (vt, name.get("en") or "")
                shows.setdefault((no, mid), {}).setdefault(key, set()).add((iso(st.date()), st.strftime("%H:%M"), (ev.get("location", {}).get("name") or {}).get("ja", "")))
    for no, (tid, name, city, area) in STAR_META.items():
        th = {"id": tid, "name": name, "area": area, "city": city, "url": f"{STAR}/theaters/{found[no][0]}" if no in found else STAR,
              "price": "¥2,000 adult (members ¥1,500; Fri members ¥1,100)", "notes": "Star Theaters chain. Foreign films are either subtitled in Japanese (字幕) or dubbed (吹替); no English subtitles.",
              "movies": [], "status": "ok" if no in found else "unavailable"}
        if no in found:
            pid, pl = found[no]
            for m in pl["movies"]:
                variants = shows.get((no, m["id"]))
                if not variants: continue
                desc_ja = BeautifulSoup(m.get("description") or "", "html.parser").get_text(" ").strip() or None
                tja = clean_title(m["title"])
                eng = re.search(r"／([A-Za-z0-9][^／]*)$", tja)
                en_from_sched = next((k[1] for k in variants if k[1]), "")
                en_from_sched = re.sub(r"\s*/\s*(DolbyAtmos|IMAX|4DX).*$", "", en_from_sched, flags=re.I)
                tja = re.sub(r"／[A-Za-z0-9][^／]*$", "", tja).strip()
                title_en = (eng.group(1).strip() if eng else "") or en_from_sched or tr(tja) or tja
                foreign = bool(eng or en_from_sched)
                fmts, allshows, rating = set(), {}, None
                for (vt, ven), sset in variants.items():
                    f = fmt_note(vt, foreign=foreign)
                    short = "Dub" if "dub" in f else ("Sub" if "Original" in f else ("JP subs" if "Japanese sub" in f else ""))
                    if "Atmos" in vt: short = (short + " Atmos").strip()
                    fmts.add(f)
                    rm = re.search(r"【(PG12|R15\+|R18\+)】", vt)
                    if rm: rating = rm.group(1)
                    for d, t, sc in sset:
                        allshows.setdefault((d, t, short), sc)
                th["movies"].append({
                    "title": title_en, "title_ja": tja, "format": " / ".join(sorted(fmts)),
                    "synopsis": tr(desc_ja) if desc_ja else None, "synopsis_ja": desc_ja,
                    "runtime": None, "rating": rating,
                    "poster": m.get("poster"), "director": ", ".join(m.get("directors") or []) or None,
                    "cast": ", ".join(m.get("actors") or []) or None,
                    "showtimes": [{"date": d, "time": t, "tag": tag} for d, t, tag in sorted(allshows)],
                    "source": f"{STAR}/theaters/{pid}/movies/{m['id']}/"})
            th["movies"].sort(key=lambda x: x["title"])
        theaters.append(th)
    source("Star Theaters (startheaters.jp JSON)", STAR, bool(found), f"theaters found: {sorted(found)}", sum(len(t["movies"]) for t in theaters))
    return theaters

# ---------------------------------------------------------------- Exchange Reel Time (on base)
RT = "https://reeltime.imenu360.com/BookingAPI/TheaterBookingService.svc/"
RT_AREA = {"Kadena Keystone Theater": "central", "Foster Butler Theater": "central", "Futenma Theater": "central",
           "Courtney Theater": "central", "Kinser Theater": "south", "Schwab Theater": "north", "Hansen Theater": "north"}
def reeltime():
    out = []
    s = requests.Session(); s.headers.update({"User-Agent": UA, "Origin": "https://reeltime.imenu360.com", "Referer": "https://reeltime.imenu360.com/"})
    def call(m, d):
        r = s.post(RT + m, json={"postData": base64.b64encode(json.dumps(d).encode()).decode() if d else ""}, timeout=40)
        return json.loads(base64.b64decode(r.json()["data"]))
    try:
        tok = call("GetNewToken", None)["tId"]
        camps = call("GetLocationCamps", {"tId": tok, "locationId": 5})["campList"]
    except Exception as e:
        source("Exchange Reel Time Theaters (reeltime.imenu360.com)", "https://reeltime.imenu360.com/", False, str(e)); return out
    for c in camps:
        for t in c["cityTheaters"]:
            name = t["TheaterName"]
            page = f"https://reeltime.imenu360.com/Okinawa/{requests.utils.quote(c['cityName'])}/{requests.utils.quote(name)}"
            th = {"id": "rt-" + str(t["TheaterId"]), "name": name.replace("Theater", "Reel Time Theater").strip(), "base": c["cityName"],
                  "area": RT_AREA.get(name, "central"), "city": c["cityName"] + " (on base, ID required)", "url": page, "onbase": True,
                  "notes": "Exchange Reel Time theater. English-language first-run Hollywood films. Base access (DoD ID) required.", "movies": [], "status": "ok"}
            try:
                d = call("GetLocationMovies", {"tId": tok, "locationId": 5, "cityId": str(c["cityId"]), "theaterId": str(t["TheaterId"])})
                movies = {m["MovieId"]: m for m in d.get("MovieList") or []}
                sched = {}
                for sc in d.get("MovieScheduleList") or []:
                    sdt = dt.datetime.fromisoformat(sc["ScheduleDateTime"])
                    if sdt.date() in DAYS: sched.setdefault(sc["MovieId"], []).append(sdt)
                for mid, times in sched.items():
                    m = movies.get(mid, {})
                    desc = BeautifulSoup(m.get("MovieDescription") or "", "html.parser").get_text("\n")
                    desc = "\n".join(l.strip() for l in desc.splitlines() if l.strip() and not l.strip().upper().startswith(("RATED-R", "PG ", "PG-", "R -", "G -", "GENRE")) and "Notes will not" not in l and "accompanying parent" not in l and "Guardians are not" not in l and "auditorium themselves" not in l)
                    th["movies"].append({"title": m.get("MovieTitle", "?"), "synopsis": desc.strip() or None, "rating": m.get("Rating"),
                        "runtime": (m.get("DurationInHour") or 0) * 60 + (m.get("DurationInMinute") or 0) or None,
                        "genres": m.get("Genres"), "poster": m.get("MovieImage"), "format": "English", "price": f"${m.get('Charges_Adult')} adult / ${m.get('Charges_Child')} child" if m.get("Charges_Adult") else None,
                        "trailer": m.get("TrailerLink") or None,
                        "showtimes": [{"date": iso(x.date()), "time": x.strftime("%H:%M")} for x in sorted(times)], "source": page})
                th["movies"].sort(key=lambda x: x["showtimes"][0]["date"] + x["showtimes"][0]["time"])
            except Exception as e:
                th["status"] = "unavailable"; th["error"] = str(e)
            out.append(th)
    source("Exchange Reel Time Theaters (reeltime.imenu360.com API)", "https://reeltime.imenu360.com/", bool(out), f"{len(out)} theaters", sum(len(t["movies"]) for t in out))
    return out

def sakurazaka():
    url = "https://www.sakura-zaka.com/"
    th = {"id": "sakurazaka", "name": "Sakurazaka Theater", "name_ja": "桜坂劇場", "area": "south", "city": "Naha (Makishi, near Kokusai-dori)",
          "url": url, "movies": [], "status": "unavailable",
          "notes": "Indie/art-house cinema. Its website blocks automated fetching, so showtimes can't be read here; check the site directly."}
    try:
        r = S.get(url, timeout=20, headers={"Accept-Language": "ja,en;q=0.8", "Accept": "text/html"})
        note = f"HTTP {r.status_code}"
    except Exception as e: note = str(e)
    source("Sakurazaka Theater (sakura-zaka.com)", url, False, note + " - blocked to scripts")
    return th

# ---------------------------------------------------------------- events: okinawastory.jp
OS_URL = "https://www.okinawastory.jp/event"
AREA_MAP = {"本島北部": "north", "本島中部": "central", "本島南部": "south"}
CATS = [
    ("concerts", r"ライブ|コンサート|LIVE|Live|音楽|ジャズ|JAZZ|DJ|フェス.*音楽|演奏|ナイト|バー|クラブ|ミュージック|MUSIC"),
    ("family", r"子ども|こども|キッズ|親子|ファミリー|水族館|動物|恐竜|ワークショップ|体験|スタンプラリー|ハロウィン|絵本|プリキュア"),
    ("outdoors", r"ビーチ|海|マリン|ダイビング|ハイキング|トレッキング|キャンプ|自然|花火|マラソン|ラン|ウォーク|サイクル|釣り|ゴルフ|公園|星空|カヌー|SUP"),
    ("food", r"グルメ|フード|マルシェ|マーケット|市場|ビール|酒|泡盛|ランチ|ディナー|ブッフェ|ビュッフェ|スイーツ|カフェ|食|コーヒー|ワイン|朝市|物産"),
]
def classify(t):
    for c, rx in CATS:
        if re.search(rx, t): return c
    return "events"

def parse_jp_range(s):
    ds = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if not ds:
        return None, None
    a = dt.date(*map(int, ds[0])); b = dt.date(*map(int, ds[-1])) if len(ds) > 1 else (a if "〜" not in s.rstrip()[-2:] else a + dt.timedelta(days=365))
    return a, b

def okinawastory():
    items, ok = [], False
    for page in range(1, 16):
        try:
            r = S.get(OS_URL, params={"page": page}, timeout=30); r.raise_for_status(); ok = True
        except Exception as e:
            log("okinawastory", page, e); break
        soup = BeautifulSoup(r.text, "html.parser")
        arts = soup.select("article.os-c-list-cmn")
        if not arts: break
        for a in arts:
            link = a.select_one("a.os-c-list-cmn__title-link")
            if not link: continue
            ctg = [li.get_text(strip=True) for li in a.select(".os-c-list-cmn__ctg-item")]
            area = next((AREA_MAP[c] for c in ctg if c in AREA_MAP), None)
            if not area: continue  # outer islands: not on main island
            when = (a.select_one(".os-c-list-cmn__lead") or {}).get_text(" ", strip=True) if a.select_one(".os-c-list-cmn__lead") else ""
            venue = a.select_one(".os-c-list-cmn__disc"); venue = venue.get_text(" ", strip=True) if venue else ""
            d0, d1 = parse_jp_range(when)
            if d1 and d1 < TODAY: continue
            title = link.get_text(" ", strip=True)
            items.append({"title_ja": title, "when_ja": when, "venue_ja": venue, "area": area,
                          "city_ja": next((c for c in ctg if c not in AREA_MAP), ""), "start": iso(d0) if d0 else None, "end": iso(d1) if d1 else None,
                          "category": classify(title + " " + venue), "source": "https://www.okinawastory.jp" + link["href"], "src_name": "Okinawa Story (okinawastory.jp)"})
        time.sleep(0.5)
    # translate soonest first (quota-friendly): events active within 10 days
    horizon = TODAY + dt.timedelta(days=10)
    items.sort(key=lambda e: (e["start"] or "9"))
    for e in items:
        near = (not e["start"]) or dt.date.fromisoformat(e["start"]) <= horizon
        e["title"] = (tr(e["title_ja"]) if near else TCACHE.get(e["title_ja"])) or None
        e["venue"] = (tr(e["venue_ja"]) if near and e["venue_ja"] else TCACHE.get(e["venue_ja"])) or e["venue_ja"]
        e["city"] = TCACHE.get(e["city_ja"]) or (tr(e["city_ja"]) if near else None) or e["city_ja"]
        e["time"] = None
        e["description"] = f"{e['when_ja']}"
        e["price"] = None
    source("Okinawa Story events (okinawastory.jp)", OS_URL, ok and bool(items), "", len(items))
    return items

# ---------------------------------------------------------------- events: Kadena FSS (The Events Calendar API)
def kadena_fss():
    url = "https://kadenafss.com/wp-json/tribe/events/v1/events"
    items = []
    try:
        page = 1
        while page <= 8:
            r = S.get(url, params={"start_date": iso(TODAY), "end_date": iso(DAYS[-1]), "per_page": 50, "page": page}, timeout=40)
            if r.status_code != 200: break
            j = r.json()
            for ev in j.get("events", []):
                desc = re.sub(r"\s+", " ", BeautifulSoup(ev.get("description") or "", "html.parser").get_text(" ")).strip()
                sd = dt.datetime.fromisoformat(ev["start_date"]); ed = dt.datetime.fromisoformat(ev["end_date"])
                venue = ev.get("venue") or {}
                cats = [c.get("name", "") for c in ev.get("categories") or []]
                items.append({"title": html.unescape(ev["title"]), "start": iso(sd.date()), "end": iso(ed.date()),
                              "time": None if ev.get("all_day") else sd.strftime("%H:%M") + ("–" + ed.strftime("%H:%M") if ed.date() == sd.date() and ed != sd else ""),
                              "venue": html.unescape(venue.get("venue", "")) if isinstance(venue, dict) else "", "area": "central", "city": "Kadena Air Base",
                              "description": desc[:400], "price": ev.get("cost") or None, "category": "onbase", "tags": cats,
                              "source": ev.get("url"), "src_name": "Kadena FSS (kadenafss.com)"})
            if page >= int(j.get("total_pages") or 1): break
            page += 1
        source("Kadena FSS events (kadenafss.com API)", "https://kadenafss.com/events", True, "", len(items))
    except Exception as e:
        source("Kadena FSS events (kadenafss.com API)", "https://kadenafss.com/events", False, str(e))
    return items

def mccs():
    url = "https://www.okinawa.usmc-mccs.org/events"
    try:
        r = S.get(url, timeout=20); note = f"HTTP {r.status_code}"
        ok = r.status_code == 200
    except Exception as e: ok, note = False, str(e)
    source("MCCS Okinawa events (Foster/Courtney/Kinser/Schwab)", url, False, note + (" - page is JS-rendered; not parsed yet" if ok else " - blocked to scripts"))

# ---------------------------------------------------------------- main
def main():
    os.makedirs(DATA, exist_ok=True)
    checked = NOW.strftime("%Y-%m-%d %H:%M JST")
    jobs = {}
    donut = theater_donut()
    star = star_theaters()
    rt = reeltime()
    sak = sakurazaka()
    plaza_note = "Plaza House Shopping Center (Okinawa City) does have a cinema: Cinema Plaza House, 3F, run by Star Theaters."
    movies = {"checked_at": checked, "generated": NOW.isoformat(), "days": [iso(d) for d in DAYS],
              "theaters": [donut] + star + [sak] + rt, "notes": [plaza_note,
              "AEON Mall Okinawa Rycom's cinema is 'Cinema Rycom' (Star Theaters), not an AEON Cinema.",
              "Japanese cinemas show foreign films either Japanese-subtitled (字幕) or Japanese-dubbed (吹替); English-language audio = 字幕 showings."],
              "sources": [s for s in SOURCES]}
    n_movie_src = len(SOURCES)
    for t in movies["theaters"]: t.setdefault("region", "okinawa")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kyushu
    try:
        movies["theaters"] += kyushu.eiga_cinemas(S, tr, DAYS, source, log, budget_ok)
    except Exception as e:
        source("eiga.com theater schedules (Kyushu)", "https://cinema.eiga.com/theater/40/", False, str(e))
    movies["notes"] += ["Fukuoka–Beppu: no cinemas in Yufuin, Nakatsu or Usa are listed on eiga.com; Beppu Bluebird Theater is Beppu's only cinema."]
    movies["sources"] = list(SOURCES)
    n_movie_src = len(SOURCES)
    ev = okinawastory() + kadena_fss()
    for e in ev: e.setdefault("region", "okinawa")
    ky = []
    for fn in (kyushu.yokanavi, kyushu.visit_oita):
        try: ky += fn(S, TODAY, classify, source, log)
        except Exception as e: source(fn.__name__, "", False, str(e))
    horizon = TODAY + dt.timedelta(days=7)
    ky.sort(key=lambda e: e["start"] or "9")
    for e in ky:
        near = (not e["start"]) or dt.date.fromisoformat(e["start"]) <= horizon
        e["title"] = (tr(e["title_ja"]) if near else TCACHE.get(e["title_ja"])) or None
        e["city"] = TCACHE.get(e["city_ja"]) or (tr(e["city_ja"]) if near else None) or e["city_ja"]
        e["venue"] = ""; e["time"] = None; e["price"] = None; e["description"] = e.get("when_ja")
    ev += ky
    mccs()
    ev.sort(key=lambda e: (e.get("start") or "9", e.get("time") or ""))
    events = {"checked_at": checked, "generated": NOW.isoformat(), "items": ev, "sources": SOURCES[n_movie_src:],
              "translation": {"provider": "MyMemory (api.mymemory.translated.net)", "quota_hit": T_STATE["quota_hit"], "chars_this_run": T_STATE["chars"]}}
    movies["translation"] = events["translation"]
    json.dump(movies, open(os.path.join(DATA, "movies.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(events, open(os.path.join(DATA, "events.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(TCACHE, open(TCACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=0, sort_keys=True)
    for s in SOURCES: log(f"[{s['status']:11}] {s['name']}: {s['items']} items {s['note']}")
    log("translated chars:", T_STATE["chars"], "quota hit:", T_STATE["quota_hit"])

if __name__ == "__main__":
    main()
