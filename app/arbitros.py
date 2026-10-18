"""Árbitros da Liga Portugal: nomeações (API pública do site da Liga) ligadas aos jogos do football-data.

Só Python de base. As nomeações vivem em data/arbitros/P1.csv (histórico) e em cache por jornada.
"""
import csv, difflib, json, os, re, time, unicodedata, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "..", "data", "arbitros")
CSV = os.path.join(DIR, "P1.csv")


def csv_path(league):
    return os.path.join(DIR, f"{league}.csv")
URL = "https://www.ligaportugal.pt/api/v1/competition/round/{r}/nominations?competition={c}&season={s}"
FIELDS = ["season", "round", "date", "home", "away", "referee"]
REFRESH_EVERY = 3 * 3600
ALIAS = {"sporting cp": "sp lisbon", "sporting": "sp lisbon", "braga": "sp braga", "vitoria": "guimaraes",
         "vitoria guimaraes": "guimaraes", "estrela amadora": "estrela",
         "bayern munchen": "bayern munich", "borussia monchengladbach": "m'gladbach", "1 koln": "fc koln", "koln": "fc koln",
         "eintracht frankfurt": "ein frankfurt", "bayer 04 leverkusen": "leverkusen", "bayer leverkusen": "leverkusen",
         "1 fsv mainz 05": "mainz", "fsv mainz 05": "mainz", "borussia dortmund": "dortmund", "tsg hoffenheim": "hoffenheim",
         "1 union berlin": "union berlin", "vfl bochum": "bochum", "st pauli": "st pauli", "hamburger sv": "hamburg",
         "1 heidenheim": "heidenheim", "sv werder bremen": "werder bremen", "vfb stuttgart": "stuttgart", "vfl wolfsburg": "wolfsburg",
         "augsburg": "augsburg", "rb leipzig": "rb leipzig", "freiburg": "freiburg", "schalke 04": "schalke 04",
         "internazionale": "inter", "inter": "inter", "hellas verona": "verona"}


def norm(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\b(fc|sc|sl|cf|cd|sad|clube|futebol|de|do|da|club|ac|as|ssc|ss|us|tsg|e v|ev)\b", " ", n.replace(".", " ").replace("-", " "))
    n = re.sub(r"\s+", " ", n).strip()
    return ALIAS.get(n, n)


def comp(season):
    return "ligaportugalbwin" if season in ("20212022", "20222023") else "ligaportugalbetclic"


def fetch(season, rnd, force=False):
    """Nomeações de uma jornada; jornadas completas ficam em cache para sempre."""
    path = os.path.join(DIR, "cache", f"{season}_{rnd}.json")
    if os.path.exists(path) and not force:
        with open(path) as fh:
            return json.load(fh)
    req = urllib.request.Request(URL.format(r=rnd, c=comp(season), s=season), headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data and all(x.get("refereeName") for x in data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh)
    time.sleep(1)  # não sobrecarregar o site da Liga
    return data


def to_rows(season, rnd, data):
    return [{"season": season, "round": rnd, "date": x["fixture"]["matchDate"][:10], "home": x["fixture"]["homeTeam"]["name"],
             "away": x["fixture"]["awayTeam"]["name"], "referee": (x.get("refereeName") or "").strip()} for x in data]


def load(league="P1"):
    path = csv_path(league)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def save(rows, league="P1"):
    os.makedirs(DIR, exist_ok=True)
    with open(csv_path(league), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def refresh(now, league="P1"):
    """Atualiza as nomeações dos próximos jogos ainda sem árbitro (máx. de 3 em 3 h)."""
    if league == "I1":
        return refresh_it(now)
    if os.path.exists(CSV) and time.time() - os.path.getmtime(CSV) < REFRESH_EVERY:
        return
    rows = load()
    soon = {(r["season"], int(r["round"])) for r in rows if not r["referee"]
            and now.date() - timedelta(days=1) <= datetime.strptime(r["date"], "%Y-%m-%d").date() <= now.date() + timedelta(days=8)}
    for season, rnd in sorted(soon):
        try:
            fresh = to_rows(season, rnd, fetch(season, rnd, force=True))
        except Exception:
            continue  # sem rede: fica para a próxima
        rows = [r for r in rows if not (r["season"] == season and int(r["round"]) == rnd)] + fresh
    save(rows)  # também marca a hora da última verificação


def _index(rows):
    by_day = defaultdict(dict)
    for r in rows:
        if r["referee"]:
            by_day[r["date"]][norm(r["home"])] = r["referee"]
    return by_day


def referee_for(by_day, date_iso, home):
    cands = by_day.get(date_iso, {})
    hit = difflib.get_close_matches(norm(home), list(cands), n=1, cutoff=0.5)
    return cands[hit[0]] if hit else None


def attach(fd_rows, nominations=None):
    """Acrescenta a coluna Referee às linhas do football-data da Liga Portugal (data dd/mm/aaaa)."""
    by_day = _index(nominations if nominations is not None else load())
    for r in fd_rows:
        if not r.get("Referee") and r.get("Date"):
            day = datetime.strptime(r["Date"], "%d/%m/%Y").strftime("%Y-%m-%d")
            r["Referee"] = referee_for(by_day, day, r["HomeTeam"]) or ""
    return fd_rows


# --- Serie A: API pública do site legaseriea.it -----------------------------------------------
IT_API = "https://api-sdp.legaseriea.it/v1/serie-a/football"
IT_COMP = "serie-a::Football_Competition::ec93b94f74294dc98ab5bcfd67fc0d88"


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    time.sleep(1)  # não sobrecarregar o site da Lega
    return data


def refresh_it(now, horizon_days=8, max_matches=12):
    """Nomeações dos jogos da Serie A dos próximos dias ainda sem árbitro (máx. de 3 em 3 h)."""
    path = csv_path("I1")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < REFRESH_EVERY:
        return
    rows = load("I1")
    seasons = {s["seasonName"]: s["seasonId"] for s in _get_json(f"{IT_API}/competitions/{IT_COMP}/seasons")["seasons"]}
    y = now.year if now.month >= 7 else now.year - 1
    sid = seasons.get(f"{y}/{y + 1}")
    if not sid:
        return
    label = f"{y}/{str(y + 1)[2:]}"
    known = {(r["date"], norm(r["home"])): r for r in rows if r["season"] == label}
    done = 0
    for m in _get_json(f"{IT_API}/seasons/{sid}/matches")["matches"]:
        date = str(m.get("matchDateLocal") or "")[:10]
        if not date or not (now.date() - timedelta(days=1) <= datetime.strptime(date, "%Y-%m-%d").date() <= now.date() + timedelta(days=horizon_days)):
            continue
        home, away = m["home"]["shortName"], m["away"]["shortName"]
        r = known.get((date, norm(home)))
        if r and r["referee"]:
            continue
        if done >= max_matches:
            break
        facts = _get_json(f"{IT_API}/seasons/{sid}/match/{m['matchId']}/matchfacts")
        ref = next((" ".join(x for x in (o.get("mediaFirstName"), o.get("mediaLastName")) if x) for o in facts.get("referees") or []
                    if o.get("role") == "Referee"), "")
        done += 1
        if r:
            r["referee"] = ref
        else:
            rows.append({"season": label, "round": m.get("roundName") or "", "date": date, "home": home, "away": away, "referee": ref})
    save(rows, "I1")  # também marca a hora da última verificação
