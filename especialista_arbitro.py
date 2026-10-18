"""Efeito do árbitro nos amarelos (Premier League, única liga com árbitro nos dados públicos).

Acrescenta ao modelo dos amarelos a média recente do árbitro (encolhida para a média da liga) e mede,
fora da amostra, se melhora a perda logarítmica e o acerto. Uso: python3 especialista_arbitro.py
"""
import csv, glob, json, math, os, sys
from collections import defaultdict, deque
from datetime import datetime
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from features import MODEL_COLS, negbin_over  # noqa: E402

K_SHRINK, LAST_REF = 12, 40


import difflib, re, unicodedata


def norm(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\b(fc|sc|sl|cf|cd|sad|clube|futebol|de|do|da|club)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


ALIAS = {"sporting cp": "sp lisbon", "sporting": "sp lisbon", "braga": "sp braga", "vitoria": "guimaraes",
         "vitoria guimaraes": "guimaraes", "estrela amadora": "estrela", "avs": "avs"}


def league_rows(league):
    """Linhas do football-data com coluna Referee (Inglaterra já a tem; Portugal vem das nomeações da Liga)."""
    rows = []
    for f in glob.glob(os.path.join(HERE, "data", "football-data", f"{league}_*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            rows += [r for r in csv.DictReader(fh) if r.get("HY") and r.get("Date")]
    if league != "E0":  # nomeações recolhidas (Portugal, Alemanha, Itália) ligadas por data e equipa da casa
        import arbitros
        arbitros.attach(rows, arbitros.load(league))
    out = []
    for r in rows:
        if r.get("Referee"):
            r["dt"] = datetime.strptime(r["Date"], "%d/%m/%Y")
            out.append(r)
    return out


def ref_feature(league="E0"):
    """(data, equipa da casa) -> log(critério encolhido do árbitro / liga) usando só jogos anteriores."""
    rows = league_rows(league)
    rows.sort(key=lambda r: r["dt"])
    hist, league, out = defaultdict(lambda: deque(maxlen=LAST_REF)), deque(maxlen=380), {}
    for r in rows:
        y, fl = float(r["HY"]) + float(r["AY"]), float(r["HF"]) + float(r["AF"])
        if len(league) >= 60:
            ly, lf = sum(a for a, _ in league), sum(b for _, b in league)
            h = hist[r["Referee"].strip()]
            rate_lg = ly / lf
            # critério do árbitro: amarelos por falta, encolhido para o da liga (K jogos fictícios)
            rate = (sum(a for a, _ in h) + K_SHRINK * ly / len(league)) / (sum(b for _, b in h) + K_SHRINK * lf / len(league))
            out[(r["dt"], r["HomeTeam"])] = (math.log(rate / rate_lg), len(h), r["Referee"].strip())
        hist[r["Referee"].strip()].append((y, fl))
        league.append((y, fl))
    return out


if __name__ == "__main__":
    D = v2.build()
    LG = sys.argv[1] if len(sys.argv) > 1 else "E0"
    D = D[(D.S != "2021") & (D.L == LG)].reset_index(drop=True)
    RF = ref_feature(LG)
    D["y_ref"] = [RF.get((dt, h), (0.0, 0, ""))[0] for dt, h in zip(D.dt, D.home)]
    D["ref_n"] = [RF.get((dt, h), (0.0, 0, ""))[1] for dt, h in zip(D.dt, D.home)]
    D = D[[(dt, h) in RF for dt, h in zip(D.dt, D.home)]].reset_index(drop=True)  # só jogos com árbitro identificado
    print(f"{LG}: {len(D)} jogos, árbitro identificado em {D.home.size and ((D.ref_n > 0) | (D.y_ref != 0)).mean():.0%}")
    print("variação do efeito árbitro:", D.y_ref.describe()[["std", "min", "max"]].round(3).to_dict())
    tr, te = D.S.isin(v2.TRAIN).values, ~D.S.isin(v2.TRAIN).values
    res = {}
    for name, cols in (("sem árbitro", MODEL_COLS["y"]), ("com árbitro", MODEL_COLS["y"] + ["y_ref"])):
        m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, cols], D.loc[tr, "y_y"])
        mu = m.predict(D[cols]); disp = float(np.mean((D.loc[tr, "y_y"] - mu[tr]) ** 2 / mu[tr]))
        ll = []
        for line in (2.5, 3.5, 4.5, 5.5):
            p = np.clip([negbin_over(a, line, disp) for a in mu[te]], 1e-4, 1 - 1e-4)
            y = (D.y_y.values[te] > line).astype(float)
            ll.append(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        res[name] = (dict(zip(cols, np.round(m.coef_, 3))), np.round(ll, 4), m)
        print(f"\n{name}: perda log. teste (2,5/3,5/4,5/5,5) {np.round(ll, 4)} · média {np.mean(ll):.4f}")
    coef_ref = res["com árbitro"][0]["y_ref"]
    print(f"\ncoeficiente do árbitro: {coef_ref} (1,0 = o árbitro conta por inteiro)")
    # quanto pesa: árbitro duro (+1 desvio) vs brando (−1 desvio) em amarelos esperados
    sd = D.y_ref.std()
    print(f"árbitro duro vs brando (±1 desvio): x{math.exp(coef_ref * sd):.2f} / x{math.exp(-coef_ref * sd):.2f} nos amarelos esperados")

    # árbitros extremos: o modelo sem árbitro erra nestes jogos? (treino e teste em separado)
    m0 = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, MODEL_COLS["y"]], D.loc[tr, "y_y"])
    D["res"] = D.y_y - m0.predict(D[MODEL_COLS["y"]])
    q = D.y_ref.quantile([.1, .9]).values
    for name, mask in (("brandos (10%)", D.y_ref <= q[0]), ("rigorosos (10%)", D.y_ref >= q[1])):
        for lab, sub in (("treino", tr), ("teste", te)):
            g = D[mask & sub]
            if len(g) > 5:
                print(f"árbitros {name} · {lab}: n={len(g)} amarelos {g.y_y.mean():.2f}, modelo erra por {g.res.mean():+.2f} ± {1.96 * g.res.std() / np.sqrt(len(g)):.2f}")
