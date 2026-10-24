# Family Activity Planner

(Formerly "Okinawa Now". The repo name and URL are unchanged.)

A mobile-first static app that shows what's on across Okinawa's main island: movies (Theater Donut first), events, concerts and nightlife, family activities, outdoors, food, and on-base happenings.

- `index.html`, `app.js`, `style.css`: the static front end (deployed on Render as a static site, publish path `.`)
- `data/movies.json`, `data/events.json`: written by the refresh script. Both carry a `checked_at` time in JST and a `sources` list that shows which sources were ok and which were unavailable.
- `data/translations.json`: cache of machine translations (MyMemory, ja→en) so daily runs only translate new text.

## Refresh (daily)

```bash
git clone https://github.com/JSBOKI/okinawa-now && cd okinawa-now
python3 -m pip install -r requirements.txt
python3 tools/refresh.py
git add data && git commit -m "data refresh $(TZ=Asia/Tokyo date +%F)" && git push
```

You need Python 3.9+ and `node` on PATH, because Star Theaters schedule payloads are JS. Optional: set `MYMEMORY_EMAIL=you@example.com` to raise the free translation quota.

## Sources
Fukuoka–Beppu region: showtimes come from eiga.com theater pages (21 cinemas in Fukuoka city, Dazaifu area, Kurume, Kitakyushu, Oita and Beppu), with synopses from eiga.com movie pages. Events come from yokanavi.com (Fukuoka City) and visit-oita.jp. Set TRANSLATE_BUDGET_SEC (default 330) to cap translation time.

| Source | What |
|---|---|
| theater-donut.com | Theater Donut Okinawa (Koza) schedule + synopses |
| startheaters.jp (`/schedule/data/*.json` + Nuxt payloads) | Cinema Q, Cinema Palette, Cinema Plaza House, Southern Plex, Mihama 7plex, Cinema Rycom |
| reeltime.imenu360.com API | Exchange Reel Time theaters: Kadena Keystone, Foster, Courtney, Kinser, Schwab, Futenma, Hansen |
| okinawastory.jp/event | Island-wide events (north/central/south) |
| kadenafss.com (The Events Calendar REST API) | Kadena FSS events |
| sakura-zaka.com, okinawa.usmc-mccs.org | Block scripted fetches, so the app marks them unavailable |

Nothing is invented: if a source fails, the app says so.
