"""Mercados por equipa: cantos da casa, cantos de fora e amarelos da casa (só "menos de").

Treina em 2021/22–2024/25, testa em 2025/26–2026/27 e junta os modelos a app/data/modelos.json.
Teste fora da amostra (19/10/2026), faixa 74–80%, linhas até 9,5 (a 22bet tem 7 linhas à volta da média):
menos cantos casa 77,8% real para 76,6% previsto, fora 76,8% para 76,9%, menos amarelos casa 77,0% para 77,0%. Os "mais de" e os amarelos de fora
ficaram 3 a 5 pontos abaixo do previsto e não entram. Uso: python3 especialista_equipa.py (depois de especialista_v2.py)
"""
import json, os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as E  # noqa: E402
from features import MODEL_COLS, negbin_over  # noqa: E402

TARGET = {"hc": "y_hc", "ac": "y_ac", "hy": "y_hy"}
LINES = {"hc": [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5], "ac": [2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5], "hy": [0.5, 1.5, 2.5, 3.5]}
KEEP = ("hc-", "ac-", "hy-")

if __name__ == "__main__":
    D = E.build()
    D = D[D.S != "2021"].reset_index(drop=True)
    tr = D.S.isin(E.TRAIN).values
    te = ~tr
    path = os.path.join(HERE, "app", "data", "modelos.json")
    out = json.load(open(path))
    rows = []
    for fam, tgt in TARGET.items():
        cols, y = MODEL_COLS[fam], D[tgt].values
        m = PoissonRegressor(alpha=1e-4, max_iter=1000).fit(D.loc[tr, cols], y[tr])
        mu = m.predict(D[cols])
        disp = float(np.mean((y[tr] - mu[tr]) ** 2 / mu[tr]))
        out["models"][fam] = {"cols": cols, "coef": [round(float(c), 5) for c in m.coef_], "intercept": round(float(m.intercept_), 5), "disp": round(disp, 4)}
        out["lines"][fam] = LINES[fam]
        key = fam + "-"
        P = np.concatenate([1 - np.array([negbin_over(a, ln, disp) for a in mu]) for ln in LINES[fam]])
        Y = np.concatenate([(y < ln) for ln in LINES[fam]]).astype(float)
        T, S = np.concatenate([tr for _ in LINES[fam]]), np.concatenate([D.S.values for _ in LINES[fam]])
        pc = E.cal_apply(E.pav(P[T], Y[T]), P)
        for lo, hi in ((0.70, 0.74), (0.74, 0.80), (0.80, 0.85)):
            k = ~T & (pc >= lo) & (pc < hi)
            rows.append([key, f"{lo:.0%}–{hi:.0%}", int(k.sum()), round(100 * pc[k].mean(), 1), round(100 * Y[k].mean(), 1)])
        w = np.where(np.isin(S, ["2526", "2627"]), 2.0, 1.0)  # produção: todas as épocas, as recentes a contar a dobrar
        cal = E.pav(P, Y, w)
        out["cal"][key] = [(round(a, 4), round(b, 4)) for a, b in cal]
        pcp = E.cal_apply(cal, P)
        out["faixas"][key] = {f"{lo:.2f}": {"n": int(((pcp >= lo) & (pcp < hi)).sum()), "acerto": round(float(Y[(pcp >= lo) & (pcp < hi)].mean()), 3)}
                              for lo, hi in ((0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.01)) if ((pcp >= lo) & (pcp < hi)).sum() >= 30}
    print(pd.DataFrame(rows, columns=["mercado", "faixa", "n teste", "previsto %", "real %"]).to_string(index=False))
    json.dump(out, open(path, "w"), indent=1)
    print("modelos por equipa juntos a app/data/modelos.json")
