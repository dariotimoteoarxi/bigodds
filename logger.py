"""Registador de odds com hora (The Odds API -> SQLite).

Correr de 5 em 5 minutos (cron):  */5 * * * * cd <pasta> && ODDS_API_KEY=... python3 logger.py
Cada execução decide sozinha que competições precisam de nova leitura, para poupar créditos:
de hora a hora até 3 h antes do jogo, de 15 em 15 min até 90 min antes, de 5 em 5 min no fim.
"""
import json, os, sqlite3, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.the-odds-api.com/v4"
SPORTS = [
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_germany_bundesliga",
    "soccer_france_ligue_one", "soccer_portugal_primeira_liga",
    "soccer_uefa_champs_league", "soccer_uefa_europa_league", "soccer_uefa_europa_conference_league",
]
# shortcut: 22bet não existe na API; onexbet (1xBet, mesma plataforma) serve de substituto e betclic_fr de Betclic PT.
# Trocar se aparecerem as chaves reais. pinnacle e betfair_ex_eu são só a referência de preço justo.
BOOKMAKERS = os.environ.get("ODDS_BOOKMAKERS", "betclic_fr,onexbet,pinnacle,betfair_ex_eu")
# cada mercado custa 1 crédito por leitura; spreads quase não vem nas casas europeias
MARKETS = os.environ.get("ODDS_MARKETS", "h2h,totals")
DB = os.environ.get("ODDS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "odds.sqlite"))
WINDOW = timedelta(hours=24)

SCHEMA = """
create table if not exists events(id text primary key, sport text, home text, away text, commence text);
create table if not exists snapshots(ts text, event_id text, bookmaker text, market text, outcome text,
  point real, price real, last_update text);
create index if not exists snap_event on snapshots(event_id, market, ts);
create table if not exists polls(ts text, sport text, n_events int, credits_used int, credits_left int);
"""


def interval(minutes_to_ko):
    """Intervalo entre leituras em função do tempo até ao jogo mais próximo."""
    if minutes_to_ko <= 90:
        return timedelta(minutes=5)
    if minutes_to_ko <= 180:
        return timedelta(minutes=15)
    return timedelta(hours=1)


def due(now, kickoffs, last_poll):
    """True se a competição precisa de nova leitura. kickoffs: datetimes dos jogos; last_poll: datetime ou None."""
    upcoming = [k for k in kickoffs if now < k <= now + WINDOW]
    if not upcoming:
        return False
    if last_poll is None:
        return True
    # tolerância de 30 s para o cron não falhar a janela por segundos
    return now - last_poll >= interval((min(upcoming) - now).total_seconds() / 60) - timedelta(seconds=30)


def get(path, **params):
    params["apiKey"] = os.environ["ODDS_API_KEY"]
    with urllib.request.urlopen(f"{API}{path}?{urllib.parse.urlencode(params)}", timeout=30) as r:
        return json.load(r), r.headers


def iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def tick(db, now):
    for sport in SPORTS:
        events, _ = get(f"/sports/{sport}/events")  # não gasta créditos
        db.executemany("insert or replace into events values(?,?,?,?,?)",
                       [(e["id"], sport, e["home_team"], e["away_team"], e["commence_time"]) for e in events])
        last = db.execute("select max(ts) from polls where sport=?", (sport,)).fetchone()[0]
        kickoffs = [iso(e["commence_time"]) for e in events]
        if not due(now, kickoffs, iso(last) if last else None):
            continue
        ids = [e["id"] for e, k in zip(events, kickoffs) if now < k <= now + WINDOW]
        odds, h = get(f"/sports/{sport}/odds", bookmakers=BOOKMAKERS, markets=MARKETS,
                      oddsFormat="decimal", eventIds=",".join(ids))
        ts = now.isoformat()
        rows = [(ts, ev["id"], b["key"], m["key"], o["name"], o.get("point"), o["price"], m.get("last_update"))
                for ev in odds for b in ev.get("bookmakers", []) for m in b["markets"] for o in m["outcomes"]]
        db.executemany("insert into snapshots values(?,?,?,?,?,?,?,?)", rows)
        db.execute("insert into polls values(?,?,?,?,?)",
                   (ts, sport, len(ids), int(h.get("x-requests-last", 0)), int(h.get("x-requests-remaining", -1))))
        db.commit()
        print(f"{ts} {sport}: {len(ids)} jogos, {len(rows)} odds, créditos restantes {h.get('x-requests-remaining')}")


def closing(db, event_id, market, bookmaker):
    """Última odd registada antes do início do jogo (odd de fecho)."""
    return db.execute("""select s.outcome, s.point, s.price, s.ts from snapshots s join events e on e.id=s.event_id
        where s.event_id=? and s.market=? and s.bookmaker=? and s.ts < e.commence
        and s.ts=(select max(ts) from snapshots where event_id=s.event_id and market=s.market
                  and bookmaker=s.bookmaker and ts < e.commence)""", (event_id, market, bookmaker)).fetchall()


if __name__ == "__main__":
    if "ODDS_API_KEY" not in os.environ:
        sys.exit("Falta a variável ODDS_API_KEY (chave da The Odds API).")
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    tick(con, datetime.now(timezone.utc))
