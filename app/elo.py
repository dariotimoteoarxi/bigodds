"""Elo próprio: forças das equipas comparáveis entre ligas, para os jogos das taças europeias.

Junta os jogos das 6 ligas (football-data) com os das 3 taças (ESPN, com resultados). As taças são o que liga
as ligas entre si. Os parâmetros (K, vantagem de casa, empate) vêm de elo_uefa.py e estão em modelos.json ("elo").
Só Python de base.
"""
import csv, difflib, glob, json, math, os, time, urllib.request
from datetime import datetime

import live
from arbitros import norm

HERE = os.path.dirname(os.path.abspath(__file__))
FD_DIRS = [os.path.join(HERE, "..", "data", "football-data"), os.path.join(HERE, "data")]
CACHE = os.path.join(HERE, "data", "espn")
CUPS = ("uefa.champions", "uefa.europa", "uefa.europa.conf")


def cup_month(cup, ym, refresh=False):
    """Jogos de uma taça num mês: [{data, casa, fora, golos casa, golos fora, terminado}] (cache em disco)."""
    path = os.path.join(CACHE, f"uefa2_{cup}_{ym}.json")
    if os.path.exists(path) and not refresh:
        with open(path) as fh:
            return json.load(fh)
    req = urllib.request.Request(live.ESPN.format(lg=cup, d=ym) + "&limit=300", headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"})
    out = []
    for e in live._get(req).get("events") or []:
        side = {t["homeAway"]: t for t in e["competitions"][0]["competitors"]}
        done = e["status"]["type"].get("completed", False)
        out.append({"date": e["date"], "home": side["home"]["team"]["displayName"], "away": side["away"]["team"]["displayName"],
                    "hg": int(side["home"].get("score") or 0) if done else None, "ag": int(side["away"].get("score") or 0) if done else None,
                    "done": done, "neutral": bool(e["competitions"][0].get("neutralSite"))})
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(out, fh)
    time.sleep(0.3)
    return out


def months(start="202107", end=None):
    end = end or datetime.now().strftime("%Y%m")
    y, m = int(start[:4]), int(start[4:])
    while f"{y}{m:02d}" <= end:
        if m not in (6,):  # junho: sem jogos das taças
            yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def league_games():
    seen, out = set(), []
    for d in FD_DIRS:
        for f in glob.glob(os.path.join(d, "*_*.csv")):
            lg = os.path.basename(f).split("_")[0]
            if lg not in live.SLUG:
                continue
            with open(f, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if r.get("FTHG") in (None, "") or not r.get("HomeTeam"):
                        continue
                    dt = datetime.strptime(r["Date"], "%d/%m/%Y")
                    k = (dt.date(), r["HomeTeam"])
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append({"dt": dt, "home": r["HomeTeam"], "away": r["AwayTeam"], "hg": int(r["FTHG"]), "ag": int(r["FTAG"]),
                                "cup": False, "neutral": False, "L": lg})
    return out


def name_map(fd_teams, espn_names):
    """Nome ESPN -> nome football-data para os clubes das 6 ligas; os outros ficam com o nome ESPN."""
    idx = {norm(t): t for t in fd_teams}
    out = {}
    for n in espn_names:
        hit = difflib.get_close_matches(norm(n), list(idx), n=1, cutoff=0.8)
        out[n] = idx[hit[0]] if hit else n
    return out


def all_games(refresh_current=False):
    lg = league_games()
    cups = []
    now = datetime.now().strftime("%Y%m")
    for cup in CUPS:
        for ym in months():
            try:
                cups += [dict(g, cup_name=cup) for g in cup_month(cup, ym, refresh=refresh_current and ym == now)]
            except Exception:
                pass  # sem rede: fica o que está em cache
    nm = name_map({g["home"] for g in lg} | {g["away"] for g in lg}, {g["home"] for g in cups} | {g["away"] for g in cups})
    games = lg + [{"dt": datetime.fromisoformat(g["date"].replace("Z", "+00:00")).replace(tzinfo=None), "home": nm[g["home"]], "away": nm[g["away"]],
                   "hg": g["hg"], "ag": g["ag"], "cup": True, "neutral": g["neutral"], "L": g["cup_name"]} for g in cups if g["done"]]
    return sorted(games, key=lambda g: g["dt"]), nm


def run(games, K=20.0, H=60.0, start=1500.0, outsider=1500.0, fd_teams=()):
    """Percorre os jogos por ordem e devolve (ratings finais, [(jogo, diferença antes do jogo)])."""
    R, hist = {}, []
    fd = set(fd_teams)
    for g in games:
        for t in (g["home"], g["away"]):
            if t not in R:
                R[t] = start if t in fd or not fd else outsider
        diff = R[g["home"]] - R[g["away"]] + (0 if g["neutral"] else H)
        hist.append((g, diff))
        e = 1 / (1 + 10 ** (-diff / 400))
        s = 1.0 if g["hg"] > g["ag"] else 0.5 if g["hg"] == g["ag"] else 0.0
        gd = abs(g["hg"] - g["ag"])
        mult = 1 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        R[g["home"]] += K * mult * (s - e)
        R[g["away"]] -= K * mult * (s - e)
    return R, hist


def probs(diff, p):
    """Logit ordenado: P(fora), P(empate), P(casa) a partir da diferença de Elo (já com a vantagem de casa)."""
    x = p["beta"] * diff / 400
    sig = lambda z: 1 / (1 + math.exp(-z))
    pa = sig(p["c1"] - x)
    ph = 1 - sig(p["c2"] - x)
    return ph, max(0.0, 1 - ph - pa), pa


_STATE = {"t": 0, "R": None, "nm": None}


def ratings(max_age=6 * 3600):
    """Ratings atuais (recalculados de 6 em 6 h, com os jogos europeus do mês atualizados)."""
    if _STATE["R"] is None or time.time() - _STATE["t"] > max_age:
        with open(os.path.join(HERE, "data", "modelos.json"), encoding="utf-8") as fh:
            p = json.load(fh).get("elo")
        if not p:
            return None, None, None
        games, nm = all_games(refresh_current=True)
        fd = {g["home"] for g in games if not g["cup"]}
        R, _ = run(games, p["K"], p["H"], outsider=p["outsider"], fd_teams=fd)
        _STATE.update(t=time.time(), R=R, nm=nm, p=p)
    return _STATE["R"], _STATE["nm"], _STATE.get("p")


def cup_prediction(home_espn, away_espn, neutral=False):
    """Probabilidades 1X2 de um jogo das taças (nomes ESPN), ou None se faltar uma das equipas."""
    R, nm, p = ratings()
    if not R:
        return None
    h, a = (nm or {}).get(home_espn, home_espn), (nm or {}).get(away_espn, away_espn)
    if h not in R or a not in R:
        return None
    ph, pd, pa = probs(R[h] - R[a] + (0 if neutral else p["H"]), p)
    return {"casa": round(ph, 3), "empate": round(pd, 3), "fora": round(pa, 3), "elo_casa": round(R[h]), "elo_fora": round(R[a])}


def _self_test():
    g = [{"dt": datetime(2025, 1, i + 1), "home": "A", "away": "B", "hg": 2, "ag": 0, "neutral": False} for i in range(10)]
    R, hist = run(g, K=20, H=60)
    assert R["A"] > 1500 > R["B"] and hist[0][1] == 60
    ph, pd, pa = probs(200, {"beta": 1.0, "c1": -1.0, "c2": 0.2})
    assert ph > pa and abs(ph + pd + pa - 1) < 1e-9


if __name__ == "__main__":
    _self_test()
    print("ok")
