"""Árbitros da Bundesliga (DFB Datencenter) -> data/arbitros/D1.csv. Uso: python3 recolher_arbitros_de.py [2025-2026 ...]

1 pedido por segundo, com cache de cada página em data/arbitros/cache_de/.
"""
import os, re, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import arbitros  # noqa: E402

BASE = "https://datencenter.dfb.de"
SEASONS = ["2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026", "2026-2027"]
CACHE = os.path.join(arbitros.DIR, "cache_de")
MONTHS = {m: i for i, m in enumerate(["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
                                      "september", "oktober", "november", "dezember"], 1)}


def get(url, keep=True):
    path = os.path.join(CACHE, re.sub(r"[^a-z0-9]+", "_", url.lower())[-150:] + ".html")
    if keep and os.path.exists(path):
        return open(path, encoding="utf-8").read()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    time.sleep(1)
    if keep:
        os.makedirs(CACHE, exist_ok=True)
        open(path, "w", encoding="utf-8").write(html)
    return html


def text(html):
    t = re.sub(r"<[^>]+>", "|", html)
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(\| ?)+", "|", t)


def match(url, season, rnd, keep):
    t = text(get(url, keep))
    ref = re.search(r"Schiedsrichter/in: \|([^|]+)\|", t)
    day = re.search(r"(\d{1,2})\. (\w+) (\d{4}), \d{1,2}:\d{2} Uhr", t)
    teams = url.rsplit("/", 1)[1].rsplit("-", 1)[0]
    score = re.search(r"\|([^|]+?) \|\d+:\d+ \|\(\d+:\d+\) \|([^|]+?) \|", t)
    home, away = (score.group(1).strip(), score.group(2).strip()) if score else (teams, "")
    date = f"{day.group(3)}-{MONTHS.get(day.group(2).lower(), 0):02d}-{int(day.group(1)):02d}" if day else ""
    return {"season": season, "round": rnd, "date": date, "home": home, "away": away, "referee": ref.group(1).strip() if ref else ""}


def season_rows(season, rounds=range(1, 35), keep=True):
    out = []
    for rnd in rounds:
        try:
            html = get(f"{BASE}/datencenter/bundesliga/{season}/{rnd}-spieltag", keep)
        except Exception as e:
            print(season, rnd, e, file=sys.stderr)
            continue
        links = sorted(set(re.findall(rf'href="{BASE}(/datencenter/bundesliga/{season}/{rnd}-spieltag/[^"]+-\d+)"', html)))
        for l in links:
            try:
                out.append(match(BASE + l, season, rnd, keep))
            except Exception as e:
                print(l, e, file=sys.stderr)
    return out


if __name__ == "__main__":
    seasons = sys.argv[1:] or SEASONS
    rows = [r for r in arbitros.load("D1") if r["season"] not in seasons]
    for s in seasons:
        rows += season_rows(s)
        arbitros.save(rows, "D1")
        print(s, "ok", flush=True)
    print(f"{len(rows)} jogos, {sum(1 for r in rows if r['referee'])} com árbitro")
