"""Leituras ao intervalo: dado o resultado aos 45' e o que se esperava antes do jogo, prever a 2.ª parte.

Mercados: há golo na 2.ª parte; menos de (golos ao intervalo + 2,5) no jogo; menos de (golos ao intervalo + 1,5).
Treino 2021/22–2024/25, teste 2025/26–2026/27. Exporta o modelo para app/data/modelos.json (chave "intervalo").
"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from features import predict_mu, poisson_over  # noqa: E402

M = json.load(open(os.path.join(HERE, "app", "data", "modelos.json")))
D = v2.build()
D = D[D.S != "2021"].reset_index(drop=True)
D["mu_g2"] = [predict_mu(M["models"]["g2"], r) for r in D.to_dict("records")]
D["ht_tot"] = D.y_hth + D.y_hta
D["ht_gd"] = (D.y_hth - D.y_hta).abs()
# o favorito está a perder ao intervalo? (pressão para marcar)
D["fav_losing"] = np.where(D.pH >= D.pA, D.y_hth < D.y_hta, D.y_hta < D.y_hth).astype(float)
D["log_mu"] = np.log(D.mu_g2)
COLS = ["log_mu", "ht_tot", "ht_gd", "fav_losing"]
tr, te = D.S.isin(v2.TRAIN).values, ~D.S.isin(v2.TRAIN).values
m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, COLS], D.loc[tr, "y_g2"])
mu = m.predict(D[COLS])
print("coeficientes:", dict(zip(COLS, np.round(m.coef_, 3))), "intercept", round(m.intercept_, 3))
cand = {"Há golo na 2.ª parte": (1 - np.exp(-mu), D.y_g2 > 0),
        "Menos de (intervalo + 2,5) golos": (1 - np.array([poisson_over(a, 2.5) for a in mu]), D.y_g2 <= 2),
        "Menos de (intervalo + 1,5) golos": (1 - np.array([poisson_over(a, 1.5) for a in mu]), D.y_g2 <= 1)}
out, cal = [], {}
for name, (p, y) in cand.items():
    y = np.asarray(y, float)
    pts = v2.pav(p[tr], y[tr]); pc = v2.cal_apply(pts, p); cal[name] = pts
    for lo, hi in ((0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.01)):
        k = te & (pc >= lo) & (pc < hi)
        out.append([name, f"{lo:.0%}–{min(hi, 1):.0%}", int(k.sum()), round(100 * pc[k].mean(), 1) if k.sum() else None, round(100 * y[k].mean(), 1) if k.sum() else None, round(100 * y[te].mean(), 1)])
print(pd.DataFrame(out, columns=["mercado ao intervalo", "confiança", "jogos teste", "previsto %", "real %", "taxa base %"]).to_string(index=False))
M["intervalo"] = {"cols": COLS, "coef": [round(float(c), 5) for c in m.coef_], "intercept": round(float(m.intercept_), 5),
                  "cal": {k: [(round(a, 4), round(b, 4)) for a, b in v] for k, v in cal.items()}}
json.dump(M, open(os.path.join(HERE, "app", "data", "modelos.json"), "w"), indent=1)
print("modelo do intervalo exportado")
