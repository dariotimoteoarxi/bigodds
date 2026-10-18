"""Backtest dos mercados de especialista: golo na 1.ª parte, cantos, cartões (amarelos) e 1X2.

Para cada jogo usa só jogos anteriores (das duas equipas, com peso maior nos mais recentes) e mede
o acerto por nível de probabilidade. Uso: python3 especialista_backtest.py
"""
import glob, math, os
from collections import defaultdict, deque
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
LAST, DECAY, MIN_GAMES = 20, 0.93, 6


def load():
    fr = []
    for f in glob.glob(os.path.join(HERE, "data", "football-data", "*.csv")):
        l, s = os.path.basename(f)[:-4].split("_")
        if l in ("E0", "SP1", "I1", "D1", "F1", "P1"):
            fr.append(pd.read_csv(f, encoding="utf-8-sig", low_memory=False).assign(L=l, S=s))
    D = pd.concat(fr, ignore_index=True).dropna(subset=["FTHG", "HTHG", "HC", "AC", "HY", "AY"])
    D["dt"] = pd.to_datetime(D.Date, dayfirst=True)
    # probabilidade justa de mais de 2,5 golos (odds de fecho da média do mercado; abertura se faltar)
    D["po"] = [fair2(a, b) if fair2(a, b) is not None else fair2(c, d)
               for a, b, c, d in zip(D["AvgC>2.5"], D["AvgC<2.5"], D["Avg>2.5"], D["Avg<2.5"])]
    D["fav_p"] = [max(fair3(x, y, z)) if fair3(x, y, z) else None for x, y, z in zip(D.AvgCH, D.AvgCD, D.AvgCA)]
    D["fav_side"] = [int(np.argmax(fair3(x, y, z))) if fair3(x, y, z) else None for x, y, z in zip(D.AvgCH, D.AvgCD, D.AvgCA)]
    return D.sort_values(["L", "dt"]).reset_index(drop=True)


def fair3(a, b, c):
    try:
        q = [1 / float(v) for v in (a, b, c)]
        if any(math.isnan(x) for x in q):
            return None
        return [x / sum(q) for x in q]
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def wavg(xs):
    w = [DECAY ** i for i in range(len(xs))][::-1]
    return sum(a * b for a, b in zip(xs, w)) / sum(w)


def poisson_over(lam, line):
    k = int(math.floor(line))
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))


def negbin_over(mu, line, disp):
    """P(X > line) com binomial negativa: variância = mu * disp."""
    if disp <= 1.0001:
        return poisson_over(mu, line)
    p = 1 / disp
    r = mu * p / (1 - p)
    k = int(math.floor(line))
    cdf, pmf = 0.0, p ** r
    for i in range(k + 1):
        if i:
            pmf *= (i - 1 + r) / i * (1 - p)
        cdf += pmf
    return 1 - cdf


def implied_total(p_over25):
    lo, hi = 0.2, 6.0
    for _ in range(50):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if poisson_over(m, 2.5) < p_over25 else (lo, m)
    return (lo + hi) / 2


def fair2(a, b):
    try:
        qa, qb = 1 / float(a), 1 / float(b)
        return qa / (qa + qb)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def run():
    D = load()
    rows = []
    for l, g in D.groupby("L"):
        hist = defaultdict(lambda: deque(maxlen=LAST))   # equipa -> jogos anteriores
        league = deque(maxlen=400)                        # jogos anteriores da liga
        for r in g.itertuples(index=False):
            h, a = r.HomeTeam, r.AwayTeam
            if len(hist[h]) >= MIN_GAMES and len(hist[a]) >= MIN_GAMES and len(league) >= 100:
                L = pd.DataFrame(league)
                lg = {k: L[k].mean() for k in L.columns}
                H, A = list(hist[h]), list(hist[a])
                f = lambda T, k: wavg([x[k] for x in T])
                # golo na 1.ª parte: forças de ataque/defesa ao intervalo + golos esperados implícitos nas odds de O/U 2,5
                ht_avg = (lg["hth"] + lg["hta"]) / 2
                lh = lg["hth"] * (f(H, "htf") / ht_avg) * (f(A, "hta_") / ht_avg)
                la = lg["hta"] * (f(A, "htf") / ht_avg) * (f(H, "hta_") / ht_avg)
                lam_model = lh + la
                po = r.po if r.po == r.po else None
                share = (lg["hth"] + lg["hta"]) / (lg["fth"] + lg["fta"])
                lam_mkt = implied_total(po) * share if po else None
                lam_ht = 0.5 * lam_model + 0.5 * lam_mkt if lam_mkt else lam_model
                # cantos: a favor e contra de cada equipa
                c_mu = (f(H, "cf") + f(A, "ca")) / 2 + (f(A, "cf") + f(H, "ca")) / 2
                # amarelos: próprios e provocados
                y_mu = (f(H, "yf") + f(A, "ya")) / 2 + (f(A, "yf") + f(H, "ya")) / 2
                rows.append({"L": l, "S": r.S, "dt": r.dt, "home": h, "away": a,
                             "p_ht": 1 - math.exp(-lam_ht), "p_ht_model": 1 - math.exp(-lam_model), "ht_goal": int(r.HTHG + r.HTAG > 0),
                             "c_mu": c_mu, "corners": r.HC + r.AC, "y_mu": y_mu, "yellows": r.HY + r.AY,
                             "c_disp": lg["c_var"] / lg["c_mean"], "y_disp": lg["y_var"] / lg["y_mean"],
                             "fav_p": r.fav_p, "fav_win": (int(r.FTR == "HDA"[int(r.fav_side)]) if r.fav_side == r.fav_side and r.fav_side is not None else None)})
            # atualiza histórico com o jogo (depois de prever)
            hist[h].append({"htf": r.HTHG, "hta_": r.HTAG, "cf": r.HC, "ca": r.AC, "yf": r.HY, "ya": r.AY})
            hist[a].append({"htf": r.HTAG, "hta_": r.HTHG, "cf": r.AC, "ca": r.HC, "yf": r.AY, "ya": r.HY})
            league.append({"hth": r.HTHG, "hta": r.HTAG, "fth": r.FTHG, "fta": r.FTAG,
                           "c_mean": r.HC + r.AC, "c_var": 0.0, "y_mean": r.HY + r.AY, "y_var": 0.0})
            # variância dos totais da liga (para a dispersão)
            if len(league) >= 2:
                cs = [x["c_mean"] for x in league]; ys = [x["y_mean"] for x in league]
                league[-1]["c_var"] = float(np.var(cs)); league[-1]["y_var"] = float(np.var(ys))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    P = run()
    P = P[P.S != "2021"]
    print(f"{len(P)} jogos com previsão (2021/22–2026/27)\n")

    def calib(name, p, y):
        b = pd.cut(p, [0, .3, .4, .5, .6, .7, .75, .8, .85, .9, 1])
        t = pd.DataFrame({"p": p, "y": y, "b": b}).groupby("b", observed=True).agg(n=("y", "size"), previsto=("p", "mean"), real=("y", "mean"))
        print(f"--- {name} ---"); print((t.assign(previsto=lambda x: (100 * x.previsto).round(1), real=lambda x: (100 * x.real).round(1))).to_string()); print()

    calib("Golo na 1.ª parte (modelo + mercado)", P.p_ht, P.ht_goal)
    calib("Golo na 1.ª parte (só modelo)", P.p_ht_model, P.ht_goal)
    print("taxa base golo 1.ª parte:", round(100 * P.ht_goal.mean(), 1), "%\n")
    for line in (8.5, 9.5, 10.5):
        po = np.array([negbin_over(m, line, d) for m, d in zip(P.c_mu, P.c_disp)])
        calib(f"Cantos mais de {line}", po, (P.corners > line).astype(int))
    for line in (3.5, 4.5):
        po = np.array([negbin_over(m, line, d) for m, d in zip(P.y_mu, P.y_disp)])
        calib(f"Amarelos mais de {line}", po, (P.yellows > line).astype(int))
    P.to_pickle(os.path.join(HERE, "results", "especialista.pkl"))
