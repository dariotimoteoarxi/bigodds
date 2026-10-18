"""Filtro de consenso: as apostas em que o modelo e uma segunda opinião independente concordam acertam mais?

Segunda opinião por mercado (sem o modelo):
- golos (1.ª parte, 2.ª parte, equipa marca): só o mercado (total de golos esperado das odds Over/Under e 1X2);
- cantos e amarelos: só o histórico das duas equipas (médias recentes, sem tendências da liga nem odds).
Teste fora da amostra (2025/26–2026/27) nas apostas da faixa da app (72–88%). Uso: python3 especialista_consenso.py
"""
import json, math, os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from consultor import calibrate  # noqa: E402
from features import negbin_over, predict_mu  # noqa: E402

M = json.load(open(os.path.join(HERE, "app", "data", "modelos.json")))
MOD, CAL, LINES = M["models"], M["cal"], M["lines"]
D = v2.build()
D = D[~D.S.isin(v2.TRAIN) & (D.S != "2021")].reset_index(drop=True)

rows = []
for r in D.to_dict("records"):
    mu = {k: predict_mu(MOD[k], r) for k in ("ht", "c", "y", "g2", "hg", "ag")}
    lam, ht_m = r["_lam_tot"], math.exp(r["ht_mkt"])
    share = r["pH"] / (r["pH"] + r["pA"]) if r["pH"] and r["pA"] else 0.55
    c_hist, y_hist = math.exp(r["c_base"] + r["c_lg"]), math.exp(r["y_base"] + r["y_lg"])
    cands = [("ht+", None, 1 - math.exp(-mu["ht"]), 1 - math.exp(-ht_m), r["y_ht"] > 0),
             ("g2+", None, 1 - math.exp(-mu["g2"]), 1 - math.exp(-max(lam - ht_m, 0.05)), r["y_g2"] > 0),
             ("hs", None, 1 - math.exp(-mu["hg"]), 1 - math.exp(-lam * share), r["y_hg"] > 0),
             ("as", None, 1 - math.exp(-mu["ag"]), 1 - math.exp(-lam * (1 - share)), r["y_ag"] > 0)]
    for fam, hist, y in (("c", c_hist, r["y_c"]), ("y", y_hist, r["y_y"])):
        for line in LINES[fam]:
            po, p2 = negbin_over(mu[fam], line, MOD[fam]["disp"]), negbin_over(hist, line, MOD[fam]["disp"])
            cands += [(fam + "+", line, po, p2, y > line), (fam + "-", line, 1 - po, 1 - p2, y < line)]
    for key, line, p_raw, p2, hit in cands:
        rows.append({"key": key, "line": line, "p": calibrate(CAL, key, p_raw), "p2": p2, "hit": int(hit), "S": r["S"]})
P = pd.DataFrame(rows)
band = P[(P.p >= 0.72) & (P.p <= 0.88)].copy()

out = []
for name, rule in (("todas", lambda x: np.ones(len(x), bool)),
                   ("2.ª opinião ≥ 70%", lambda x: x.p2 >= 0.70),
                   ("2.ª opinião ≥ prob. − 5 pp", lambda x: x.p2 >= x.p - 0.05),
                   ("2.ª opinião < prob. − 10 pp (desacordo)", lambda x: x.p2 < x.p - 0.10)):
    k = rule(band)
    s = band[k]
    out.append([name, len(s), round(100 * s.p.mean(), 1), round(100 * s.hit.mean(), 1), round(100 * (s.hit.mean() - s.p.mean()), 1)])
print(pd.DataFrame(out, columns=["apostas 72–88%", "n", "previsto %", "real %", "real − previsto"]).to_string(index=False))

print("\npor família, consenso (2.ª opinião ≥ prob. − 5 pp) contra desacordo (< prob. − 10 pp):")
fam_rows = []
for fam, g in band.groupby(band.key.str[0]):
    a, d = g[g.p2 >= g.p - 0.05], g[g.p2 < g.p - 0.10]
    fam_rows.append([fam, len(a), round(100 * a.hit.mean(), 1) if len(a) else None, round(100 * a.p.mean(), 1) if len(a) else None,
                     len(d), round(100 * d.hit.mean(), 1) if len(d) else None, round(100 * d.p.mean(), 1) if len(d) else None])
print(pd.DataFrame(fam_rows, columns=["família", "n acordo", "real %", "previsto %", "n desacordo", "real %", "previsto %"]).to_string(index=False))
