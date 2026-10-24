"""Fukuoka–Beppu corridor sources for Family Activity Planner (imported by refresh.py)."""
import datetime as dt, re, time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

EIGA = "https://cinema.eiga.com"
# (eiga path, English name, sub-area, city)
CINEMAS = [
    ("40/400101/7080", "T-Joy Hakata", "fukuoka", "Hakata Station (JR Hakata City)"),
    ("40/400101/7001", "United Cinemas Canal City 13", "fukuoka", "Canal City Hakata"),
    ("40/400101/7003", "Toho Cinemas Tenjin Solaria", "fukuoka", "Tenjin"),
    ("40/400101/7010", "KBC Cinema (indie)", "fukuoka", "Nakasu / Tenjin"),
    ("40/400101/7103", "kino cinema Tenjin", "fukuoka", "Tenjin"),
    ("40/400101/7096", "United Cinemas Fukuoka Momochi", "fukuoka", "Momochi"),
    ("40/400101/7107", "Toho Cinemas LaLaport Fukuoka", "fukuoka", "Naka-ku (LaLaport)"),
    ("40/400501/7021", "AEON Cinema Chikushino", "fukuoka", "Chikushino (near Dazaifu)"),
    ("40/400601/7022", "AEON Cinema Onojo", "fukuoka", "Onojo (near Dazaifu)"),
    ("40/400301/7018", "T-Joy Kurume", "kurume", "Kurume"),
    ("40/400201/7013", "T-Joy Riverwalk Kitakyushu", "kitakyushu", "Kokura"),
    ("40/400201/7011", "Lawson United Cinema Kokura", "kitakyushu", "Kokura"),
    ("40/400201/7014", "Kokura Korona Cinema World", "kitakyushu", "Kokura"),
    ("40/400201/7015", "Kokura Showakan (classic indie)", "kitakyushu", "Kokura"),
    ("40/400201/7012", "AEON Cinema Tobata", "kitakyushu", "Tobata"),
    ("44/440201/7053", "Beppu Bluebird Theater", "beppu", "Beppu (Kitahama, retro single-screen)"),
    ("44/440101/7055", "T-Joy Park Place Oita", "oita", "Oita city"),
    ("44/440101/7090", "Toho Cinemas Amu Plaza Oita", "oita", "Oita Station"),
    ("44/440101/7056", "Toho Cinemas Oita Wasada", "oita", "Oita city (Wasada)"),
    ("44/440101/7050", "Cinema 5 (indie)", "oita", "Oita city"),
    ("44/440101/7054", "Cinema 5 bis (indie)", "oita", "Oita city"),
]

def eiga_cinemas(S, tr, DAYS, source, log, budget_ok):
    theaters, movie_ids = [], {}
    def get(c):
        path, name, area, city = c
        url = f"{EIGA}/theater/{path}/"
        try:
            r = S.get(url, timeout=30); r.raise_for_status(); r.encoding = "utf-8"
            return c, url, r.text
        except Exception as e:
            return c, url, e
    with ThreadPoolExecutor(6) as ex: pages = list(ex.map(get, CINEMAS))
    days = {d.strftime("%Y%m%d"): d.isoformat() for d in DAYS}
    for (path, name, area, city), url, html in pages:
        th = {"id": "k-" + path.split("/")[-1], "name": name, "region": "kyushu", "area": area, "city": city, "url": url,
              "movies": [], "status": "ok", "notes": "Showtimes via eiga.com (映画.com). Foreign films: 字幕 = original audio w/ Japanese subs, 吹替 = Japanese dub."}
        if isinstance(html, Exception):
            th["status"] = "unavailable"; th["error"] = str(html); theaters.append(th); continue
        soup = BeautifulSoup(html, "html.parser")
        th["name_ja"] = (soup.select_one("h1") or soup.new_tag("x")).get_text(strip=True)
        for sec in soup.select("section[id^=m][data-title]"):
            mid = sec["id"][1:]
            tja = re.sub(r"\s+", " ", sec.get("data-title", "").replace("\u3000", " ")).strip()
            img = sec.select_one(".movie-image img")
            data = [s.get_text(strip=True) for s in sec.select(".movie-image p.data span")]
            runtime = next((int(x[:-1]) for x in data if re.fullmatch(r"\d+分", x)), None)
            rating = next((x for x in data if x in ("G", "PG12", "R15+", "R18+")), None)
            shows = set(); fmts = set()
            sched = sec.select_one(".movie-schedule")
            if not sched: continue
            tag = ""
            for ch in sched.find_all(["div", "table"]):
                if getattr(ch, "name", None) == "div" and "movie-type" in (ch.get("class") or []):
                    t = ch.get_text(" ", strip=True); tag = ("Sub" if "字幕" in t else "Dub" if "吹替" in t else "") + (" " + re.sub(r"(字幕|吹替)", "", t).strip() if re.sub(r"(字幕|吹替)", "", t).strip() else "")
                    tag = tag.strip()
                elif getattr(ch, "name", None) == "table":
                    for td in ch.select("td[data-date]"):
                        d = days.get(td["data-date"])
                        if not d: continue
                        for x in td.select("small, p.date"): x.decompose()
                        for hh, mm in re.findall(r"(?<![～~\d])(\d{1,2}):(\d{2})", td.get_text(" ")):
                            shows.add((d, f"{int(hh):02d}:{mm}", tag))
                    if tag: fmts.add(tag.split()[0])
            if not shows: continue
            movie_ids.setdefault(mid, tja)
            th["movies"].append({"eiga_id": mid, "title_ja": tja, "runtime": runtime, "rating": rating,
                "poster": img["src"] if img else None,
                "format": " / ".join(sorted({"Sub": "Original language, Japanese subtitles", "Dub": "Japanese dub"}.get(f, f) for f in fmts)) or "Japanese (no English subtitles)",
                "showtimes": [{"date": d, "time": t, "tag": g} for d, t, g in sorted(shows)],
                "source": f"https://eiga.com/movie/{mid}/"})
        theaters.append(th)
    # synopses from eiga.com movie pages
    info = {}
    def minfo(mid):
        try:
            r = S.get(f"https://eiga.com/movie/{mid}/", timeout=30); r.encoding = "utf-8"
            sp = BeautifulSoup(r.text, "html.parser")
            p = sp.select_one(".movie-details .txt-block p")
            syn = p.get_text("\n", strip=True) if p else None
            orig = re.search(r"原題(?:または英題)?[：:]\s*([^<\n／]+)", r.text)
            yr = re.search(r"(\d{4})年製作", r.text)
            return mid, {"synopsis_ja": syn, "title_orig": __import__("html").unescape(orig.group(1).strip()) if orig else None, "year": yr.group(1) if yr else None}
        except Exception as e:
            return mid, {}
    with ThreadPoolExecutor(6) as ex: info = dict(ex.map(minfo, list(movie_ids)))
    today, tomorrow = DAYS[0].isoformat(), DAYS[1].isoformat()
    # translate near-term first: films showing today/tomorrow
    order = sorted([(t, m) for t in theaters for m in t["movies"]], key=lambda x: 0 if any(s["date"] in (today, tomorrow) for s in x[1]["showtimes"]) else 1)
    for t, m in order:
        i = info.get(m["eiga_id"], {})
        syn = i.get("synopsis_ja")
        short = None
        if syn:  # translate only the first paragraph (keeps quota sane); full Japanese kept
            short = syn.split("\n")[0]
            if len(short) > 320: short = short[:320].rsplit("。", 1)[0] + "。"
        m["synopsis_ja"] = syn; m["year"] = i.get("year")
        m["title"] = i.get("title_orig") or (tr(m["title_ja"]) if budget_ok() else None) or m["title_ja"]
        m["synopsis"] = tr(short) if short and budget_ok() else None
    ok = sum(1 for t in theaters if t["status"] == "ok")
    source("eiga.com theater schedules (Fukuoka/Kitakyushu/Kurume/Oita/Beppu)", EIGA + "/theater/40/", ok > 0, f"{ok}/{len(theaters)} cinemas read", sum(len(t["movies"]) for t in theaters))
    return theaters

YOKA_AREA = {"博多": "fukuoka", "天神": "fukuoka", "中洲": "fukuoka", "大濠": "fukuoka", "ももち": "fukuoka", "EAST": "fukuoka", "WEST": "fukuoka", "南エリア": "fukuoka", "近郊": "fukuoka"}
OITA_AREA = {"別府市": "beppu", "由布市": "beppu", "日出町": "beppu", "大分市": "oita", "中津市": "nakatsu-usa", "宇佐市": "nakatsu-usa", "豊後高田市": "nakatsu-usa", "杵築市": "beppu"}

def jp_dates(s, TODAY):
    ds = re.findall(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", s)
    out, y = [], TODAY.year
    for yy, mm, dd in ds:
        if yy: y = int(yy)
        try: out.append(dt.date(y, int(mm), int(dd)))
        except ValueError: pass
    if not out: return None, None
    return out[0], out[-1] if len(out) > 1 else (out[0] + dt.timedelta(days=90) if re.search(r"[～〜~]\s*$", s.split("\n")[0]) else out[0])

def yokanavi(S, TODAY, classify, source, log):
    items, ok = [], False
    for page in range(1, 6):
        try:
            r = S.get("https://yokanavi.com/events", params={"page": page}, timeout=30); r.raise_for_status(); ok = True; r.encoding = "utf-8"
        except Exception as e: log("yokanavi", e); break
        sp = BeautifulSoup(r.text, "html.parser"); cards = sp.select(".card-list__item .card")
        if not cards: break
        for c in cards:
            a = c.select_one("a.card-title")
            if not a: continue
            per = c.select_one(".card-period .txt"); per = per.get_text("\n", strip=True) if per else ""
            d0, d1 = jp_dates(per, TODAY)
            if d1 and d1 < TODAY: continue
            txt = c.get_text(" ", strip=True)
            area_txt = next((k for k in YOKA_AREA if k in txt), None)
            tags = " ".join(x.get_text() for x in c.select("a[href*=tag], .card-tag, .tag")) or txt[-80:]
            title = a.get_text(" ", strip=True)
            desc = c.select_one(".card-description"); desc = desc.get_text(" ", strip=True) if desc else ""
            cat = "concerts" if re.search(r"#音楽|#ナイトタイム", txt) else "food" if "#グルメ" in txt else classify(title + " " + desc)
            if re.search(r"祭|まつり|フェス", title) and cat not in ("food", "concerts"): cat = "events"
            items.append({"title_ja": title, "desc_ja": desc, "when_ja": per.replace("\n", " "), "venue_ja": "", "city_ja": "福岡市",
                          "region": "kyushu", "area": "fukuoka", "start": d0.isoformat() if d0 else None, "end": d1.isoformat() if d1 else None,
                          "category": cat, "source": "https://yokanavi.com" + a["href"], "src_name": "Yokanavi (Fukuoka City official)"})
        time.sleep(0.4)
    source("Yokanavi events (yokanavi.com, Fukuoka City)", "https://yokanavi.com/events", ok, "", len(items))
    return items

def visit_oita(S, TODAY, classify, source, log):
    items, ok = [], False
    for page in range(1, 8):
        url = "https://www.visit-oita.jp/events" + (f"/index/page:{page}" if page > 1 else "/")
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 404: break
            r.raise_for_status(); ok = True; r.encoding = "utf-8"
        except Exception as e: log("visit-oita", e); break
        sp = BeautifulSoup(r.text, "html.parser"); lis = sp.select(".list-4col li")
        if not lis: break
        for li in lis:
            a = li.select_one("h2.ttl-post a")
            if not a: continue
            city = (li.select_one("[class^=ico-area]") or sp.new_tag("x")).get_text(strip=True)
            genres = " ".join(x.get_text(strip=True) for x in li.select("[class^=ico-genre]"))
            per = (li.select_one("p.exp") or sp.new_tag("x")).get_text(" ", strip=True)
            d0, d1 = jp_dates(per, TODAY)
            if d1 and d1 < TODAY: continue
            title = a.get_text(" ", strip=True)
            cat = classify(title + " " + genres)
            if "温泉" in title or "湯" in title: cat = "outdoors" if cat == "events" else cat
            if re.search(r"祭|まつり|フェス|カーニバル", title) and cat not in ("food", "concerts"): cat = "events"
            items.append({"title_ja": title, "desc_ja": "", "when_ja": per, "venue_ja": "", "city_ja": city, "region": "kyushu",
                          "area": OITA_AREA.get(city, "oita-other"), "start": d0.isoformat() if d0 else None, "end": d1.isoformat() if d1 else None,
                          "category": cat, "source": "https://www.visit-oita.jp" + a["href"], "src_name": "Visit Oita (visit-oita.jp)", "cancelled": "中止" in per or "中止" in title})
        time.sleep(0.4)
    source("Visit Oita events (visit-oita.jp: Beppu, Yufuin, Oita, Nakatsu, Usa)", "https://www.visit-oita.jp/events/", ok, "", len(items))
    return items
