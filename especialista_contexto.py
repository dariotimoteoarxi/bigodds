"""Contexto para lá do histórico: cansaço (dias de descanso, jogo europeu a meio da semana) e remates à baliza.

O xG só existe no football-data desde 2026/27 (poucos jogos para treinar), por isso o perigo criado entra pelos
remates à baliza (HST/AST), que existem em todas as épocas. Datas das taças europeias: ESPN (grátis, sem conta).
Para cada mercado compara, fora da amostra (treino 2021/22–2024/25, teste 2025/26–2026/27), o modelo atual com o
modelo + contexto: perda logarítmica e acerto das apostas na faixa da app (72–88%). Uso: python3 especialista_contexto.py
"""
import csv, difflib, glob, json, math, os, sys, time, urllib.request
from collections import defaultdict, deque
from datetime import datetime, timedelta
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from arbitros import norm  # noqa: E402
from features import MODEL_COLS, negbin_over, num, wavg  # noqa: E402
import live  # noqa: E402

CUPS = ("uefa.champions", "uefa.europa", "uefa.europa.conf")
CACHE = os.path.join(HERE, "app", "data", "espn")


def uefa_games():
    """[(data, equipa ESPN)] de todos os jogos das 3 taças desde 2021/22 (cache em disco por mês)."""
    out = []
    os.makedirs(CACHE, exist_ok=True)
    for cup in CUPS:
        for y in range(2021, 2027):
            for m in list(range(7, 13)) + list(range(1, 6)):
                ym = f"{y + (m < 7)}{m:02d}"
                if ym > datetime.now().strftime("%Y%m"):
                    continue
                path = os.path.join(CACHE, f"uefa_{cup}_{ym}.json")
                if not os.path.exists(path):
                    req = urllib.request.Request(live.ESPN.format(lg=cup, d=ym) + "&limit=300", headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"})
                    try:
                        ev = live._get(req).get("events") or []
                    except Exception:
                        ev = []
                    json.dump([{"date": e["date"], "teams": [t["team"]["displayName"] for t in e["competitions"][0]["competitors"]]} for e in ev], open(path, "w"))
                    time.sleep(0.3)
                out += [(e["date"][:10], t) for e in json.load(open(path)) for t in e["teams"]]
    return out


def team_calendar():
    """{(liga, equipa football-data): [datas de jogos]} com liga + taças europeias; e remates por jogo."""
    rows = []
    for f in glob.glob(os.path.join(HERE, "data", "football-data", "*_*.csv")):
        lg = os.path.basename(f).split("_")[0]
        with open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("Date") and r.get("HomeTeam"):
                    r["L"], r["dt"] = lg, datetime.strptime(r["Date"], "%d/%m/%Y")
                    rows.append(r)
    dates = defaultdict(set)
    for r in rows:
        dates[r["HomeTeam"]].add(r["dt"].date())
        dates[r["AwayTeam"]].add(r["dt"].date())
    names = {norm(t): t for t in dates}
    euro = defaultdict(set)
    for d, t in uefa_games():
        hit = difflib.get_close_matches(norm(t), list(names), n=1, cutoff=0.8)
        if hit:
            euro[names[hit[0]]].add(datetime.strptime(d, "%Y-%m-%d").date())
    return rows, dates, euro


def context(rows, dates, euro):
    """Por jogo (liga, data, casa): descanso, jogo europeu nos 4 dias anteriores e remates à baliza recentes."""
    out, sot, lg_sot = {}, defaultdict(lambda: deque(maxlen=20)), defaultdict(lambda: deque(maxlen=380))
    for r in sorted(rows, key=lambda r: r["dt"]):
        d, h, a = r["dt"].date(), r["HomeTeam"], r["AwayTeam"]
        rec = {}
        for side, t in (("h", h), ("a", a)):
            prev = [x for x in dates[t] | euro[t] if x < d]
            rec["rest_" + side] = min((d - max(prev)).days, 10) if prev else 10
            rec["euro_" + side] = float(any(0 < (d - x).days <= 4 for x in euro[t]))
        L = lg_sot[r["L"]]
        if len(sot[h]) >= 6 and len(sot[a]) >= 6 and len(L) >= 60:
            avg = sum(L) / len(L) / 2
            att_h = (wavg([x[0] for x in sot[h]]) + wavg([x[1] for x in sot[a]])) / 2
            att_a = (wavg([x[0] for x in sot[a]]) + wavg([x[1] for x in sot[h]])) / 2
            rec.update(sot_h=math.log(max(att_h, .3) / avg), sot_a=math.log(max(att_a, .3) / avg), sot_t=math.log(max(att_h + att_a, .6) / (2 * avg)))
        out[(r["L"], r["dt"], h)] = rec
        hs, as_ = num(r, "HST"), num(r, "AST")
        if hs is not None and as_ is not None:
            sot[h].append((hs, as_))
            sot[a].append((as_, hs))
            L.append(hs + as_)
    return out




def evaluate(D, NEW):
    """Para cada mercado: modelo atual contra modelo + variáveis novas (perda log. e apostas 72–88% no teste)."""
    tr, te = D.S.isin(v2.TRAIN).values, ~D.S.isin(v2.TRAIN).values
    TARGET = {"ht": "y_ht", "g2": "y_g2", "hg": "y_hg", "ag": "y_ag", "c": "y_c", "y": "y_y"}
    M = json.load(open(os.path.join(HERE, "app", "data", "modelos.json")))
    res = []
    for fam, new in NEW.items():
        base = MODEL_COLS[fam]
        y = D[TARGET[fam]].values
        disp = M["models"][fam].get("disp", 1.0)
        lines = M["lines"].get(fam, [0.5])
        for name, cols in (("atual", base), ("+ contexto", base + new)):
            m = PoissonRegressor(alpha=1e-4, max_iter=1000).fit(D.loc[tr, cols], y[tr])
            mu = m.predict(D[cols])
            ll, picks = [], []
            for line in lines:
                po = np.array([negbin_over(x, line, disp) for x in mu])
                for p_raw, hit in ((po, y > line), (1 - po, y < line)) if fam in ("c", "y") else ((po, y > line),):
                    pts = v2.pav(p_raw[tr], hit[tr].astype(float))
                    pc = np.clip(v2.cal_apply(pts, p_raw), 1e-4, 1 - 1e-4)
                    h = hit[te].astype(float)
                    ll.append(-np.mean(h * np.log(pc[te]) + (1 - h) * np.log(1 - pc[te])))
                    k = (pc[te] >= 0.72) & (pc[te] <= 0.88)
                    picks += list(zip(pc[te][k], h[k]))
            pk = np.array(picks) if picks else np.zeros((0, 2))
            res.append([fam, name, round(float(np.mean(ll)), 4), len(pk), round(100 * pk[:, 0].mean(), 1) if len(pk) else None,
                        round(100 * pk[:, 1].mean(), 1) if len(pk) else None,
                        dict(zip(new, np.round(m.coef_[len(base):], 3))) if name != "atual" else ""])
    return pd.DataFrame(res, columns=["mercado", "modelo", "perda log. teste", "apostas 72–88%", "previsto %", "real %", "coef. novos"])


def main():
    rows, dates, euro = team_calendar()
    print("equipas com jogos europeus encontrados:", sum(1 for t in euro if euro[t]))
    ctx = context(rows, dates, euro)
    D = v2.build()
    D = D[D.S != "2021"].reset_index(drop=True)
    extra = pd.DataFrame([ctx.get((r.L, r.dt, r.home), {}) for r in D.itertuples()])
    D = pd.concat([D, extra], axis=1)
    D["rest_diff"] = D.rest_h - D.rest_a
    D["euro_any"] = np.maximum(D.euro_h, D.euro_a)
    D["short_rest"] = ((D.rest_h <= 3) | (D.rest_a <= 3)).astype(float)
    D = D.dropna(subset=["sot_t"]).reset_index(drop=True)
    print(f"jogos: {len(D)} · com jogo europeu antes: {int(D.euro_any.sum())}")
    NEW = {"ht": ["sot_t", "euro_any", "short_rest"], "g2": ["sot_t", "euro_any", "short_rest"],
           "hg": ["sot_h", "euro_h", "rest_diff"], "ag": ["sot_a", "euro_a", "rest_diff"],
           "c": ["sot_t", "euro_any", "short_rest"], "y": ["euro_any", "short_rest"]}
    print(evaluate(D, NEW).to_string(index=False))


if __name__ == "__main__":
    main()
