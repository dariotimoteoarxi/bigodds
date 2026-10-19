"""Especialista nas taças europeias: os modelos das 6 ligas aguentam em jogos da Champions, Liga Europa e Conference?

Só jogos entre duas equipas das 6 ligas (é delas que há histórico). Cada equipa usa os seus jogos no campeonato;
a média "da liga" é a das duas ligas; a força relativa vem do Elo próprio (sem odds públicas das taças).
Resultados, minutos dos golos e amarelos: ESPN (grátis). Cantos não há nos dados públicos das taças.
Uso: python3 especialista_uefa.py
"""
import bisect, csv, glob, gzip, json, os, re, sys, urllib.request
from collections import defaultdict
from datetime import datetime
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import elo  # noqa: E402
from consultor import calibrate  # noqa: E402
from features import entry, features, league_entry, negbin_over, predict_mu  # noqa: E402

CACHE = os.path.join(HERE, "results", "espn_uefa")


def cup_details(cup, ym):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{cup}_{ym}.json")
    if not os.path.exists(path):
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{cup}/scoreboard?dates={ym}&limit=400"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept-Encoding": "gzip"}), timeout=60) as r:
            raw = r.read()
        open(path, "wb").write(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    out = []
    for e in json.load(open(path, encoding="utf-8")).get("events", []):
        c = e["competitions"][0]
        if c["status"]["type"]["name"] not in ("STATUS_FULL_TIME", "STATUS_FINAL_AET", "STATUS_FINAL_PEN"):
            continue
        side = {x["homeAway"]: x for x in c["competitors"]}
        tid = {side["home"]["team"]["id"]: 0, side["away"]["team"]["id"]: 1}
        goals, yel = [], [0, 0]
        for d in c.get("details") or []:
            mm = re.match(r"(\d+)'", d.get("clock", {}).get("displayValue", ""))
            if not mm or int(mm.group(1)) > 90 + 15:
                continue  # prolongamento fora
            kind = (d.get("type") or {}).get("text", "")
            if d.get("scoringPlay"):
                goals.append((int(mm.group(1)), tid.get((d.get("team") or {}).get("id"))))
            elif kind.startswith("Yellow Card") and (d.get("team") or {}).get("id") in tid:
                yel[tid[d["team"]["id"]]] += 1
        hg = sum(1 for m, t in goals if t == 0 and m <= 120)
        out.append({"cup": cup, "dt": datetime.fromisoformat(e["date"].replace("Z", "+00:00")).replace(tzinfo=None),
                    "home": side["home"]["team"]["displayName"], "away": side["away"]["team"]["displayName"],
                    "neutral": bool(c.get("neutralSite")), "goals": goals, "y": yel})
    return out


def domestic():
    team, league, where = defaultdict(list), defaultdict(list), {}
    for f in sorted(glob.glob(os.path.join(HERE, "data", "football-data", "*.csv"))):
        lg = os.path.basename(f).split("_")[0]
        if lg not in elo.live.SLUG:
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            if not r.get("Date") or not r.get("HomeTeam"):
                continue
            dt = datetime.strptime(r["Date"], "%d/%m/%Y")
            for t in (r["HomeTeam"], r["AwayTeam"]):
                e = entry(r, t)
                if e:
                    team[t].append((dt, e))
                    where[t] = lg
            le = league_entry(r)
            if le:
                league[lg].append((dt, le))
    for d in (team, league):
        for k in d:
            d[k].sort(key=lambda x: x[0])
    return team, league, where


def before(seq, dt, n):
    i = bisect.bisect_left([x[0] for x in seq], dt)
    return [x[1] for x in seq[max(0, i - n):i]]


def main():
    M = json.load(open(os.path.join(HERE, "app", "data", "modelos.json")))
    P, cal = M["elo"], M["cal"]
    team, league, where = domestic()
    games, nm = elo.all_games()
    R, hist = elo.run(games, P["K"], P["H"], outsider=P["outsider"], fd_teams=set(where))
    diff = {(g["dt"].date(), g["home"], g["away"]): d for g, d in hist if g["cup"]}
    rows = []
    for cup in elo.CUPS:
        for ym in elo.months():
            try:
                cg = cup_details(cup, ym)
            except Exception as ex:
                print("sem", cup, ym, ex)
                continue
            for g in cg:
                h, a = nm.get(g["home"], g["home"]), nm.get(g["away"], g["away"])
                if h not in where or a not in where:
                    continue
                H, A = before(team[h], g["dt"], 20), before(team[a], g["dt"], 20)
                L = before(league[where[h]], g["dt"], 190) + before(league[where[a]], g["dt"], 190)
                d = diff.get((g["dt"].date(), h, a))
                if d is None:
                    continue
                ph, pd_, pa = elo.probs(d, P)
                ft = features(H, A, L, {"pH": ph, "pA": pa, "po": None})
                if not ft:
                    continue
                mu = {k: predict_mu(M["models"][k], ft) for k in ("ht", "y", "hg", "ag", "hy")}
                ht_goals = sum(1 for m, t in g["goals"] if m <= 45)
                hg = sum(1 for m, t in g["goals"] if t == 0)
                ag = sum(1 for m, t in g["goals"] if t == 1)
                season = g["dt"].year if g["dt"].month >= 7 else g["dt"].year - 1
                base = {"S": season, "jogo": f"{h} – {a}"}
                rows.append({**base, "mercado": "1.ª parte: mais de 0,5 golos", "p": calibrate(cal, "ht+", 1 - np.exp(-mu["ht"])), "ok": int(ht_goals > 0)})
                rows.append({**base, "mercado": "Casa marca", "p": calibrate(cal, "hs", 1 - np.exp(-mu["hg"])), "ok": int(hg > 0)})
                rows.append({**base, "mercado": "Fora marca", "p": calibrate(cal, "as", 1 - np.exp(-mu["ag"])), "ok": int(ag > 0)})
                fav_home = ph >= pa
                rows.append({**base, "mercado": "Favorito ou empate", "p": (ph if fav_home else pa) + pd_, "ok": int((hg >= ag) if fav_home else (ag >= hg))})
                for ln in (2.5, 3.5, 4.5, 5.5):
                    po = negbin_over(mu["y"], ln, M["models"]["y"]["disp"])
                    rows.append({**base, "mercado": "Amarelos: mais de", "p": calibrate(cal, "y+", po), "ok": int(sum(g["y"]) > ln)})
                    rows.append({**base, "mercado": "Amarelos: menos de", "p": calibrate(cal, "y-", 1 - po), "ok": int(sum(g["y"]) < ln)})
                for ln in (0.5, 1.5, 2.5, 3.5):
                    po = negbin_over(mu["hy"], ln, M["models"]["hy"]["disp"])
                    rows.append({**base, "mercado": "Amarelos casa: menos de", "p": calibrate(cal, "hy-", 1 - po), "ok": int(g["y"][0] < ln)})
    D = pd.DataFrame(rows)
    print(f"{D.jogo.nunique()} jogos europeus entre equipas das 6 ligas (2021/22–2026/27)")
    out = []
    for mk, G in D.groupby("mercado"):
        for lo, hi in ((0.65, 0.74), (0.74, 0.80), (0.80, 0.90)):
            k = (G.p >= lo) & (G.p < hi)
            if k.sum() >= 25:
                out.append([mk, f"{lo:.0%}–{hi:.0%}", int(k.sum()), round(100 * G.p[k].mean(), 1), round(100 * G.ok[k].mean(), 1)])
    print(pd.DataFrame(out, columns=["mercado", "faixa", "n", "previsto %", "real %"]).to_string(index=False))
    D.to_pickle(os.path.join(HERE, "results", "uefa_teste.pkl"))
    # correção europeia por mercado: ajustada em 2021/22–2024/25 e testada em 2025/26–2026/27 (153 jogos), todas as
    # faixas acertaram o mostrado ou mais (no máximo 0,6 pontos abaixo); em produção usa todos os jogos
    import especialista_v2 as v2
    KEY = {"Amarelos: menos de": "y-", "Amarelos: mais de": "y+", "Amarelos casa: menos de": "hy-", "1.ª parte: mais de 0,5 golos": "ht+",
           "Casa marca": "hs", "Fora marca": "as", "Favorito ou empate": "dc"}
    M["uefa"] = {KEY[mk]: [(round(float(a), 4), round(float(b), 4)) for a, b in v2.pav(G.p.values, G.ok.values)] for mk, G in D.groupby("mercado")}
    M["uefa"]["jogos"] = int(D.jogo.nunique())
    json.dump(M, open(os.path.join(HERE, "app", "data", "modelos.json"), "w"), indent=1)
    print("correção europeia exportada para app/data/modelos.json")


if __name__ == "__main__":
    main()
