"""Mercados candidatos: golo na 2.ª parte, mais de 1,5 golos, equipa marca e dupla hipótese.

Mesmo método dos atuais: regressão de Poisson (treino 2021/22–2024/25), calibração no treino,
acerto fora da amostra (2025/26–2026/27), e seleção diária com e sem os mercados novos.
"""
import os, sys
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from features import MODEL_COLS, negbin_over  # noqa: E402

D = v2.build()
D = D[(D.S != "2021")].dropna(subset=["pH"]).reset_index(drop=True)
tr, te = D.S.isin(v2.TRAIN).values, ~D.S.isin(v2.TRAIN).values
mu = {}
for fam in ("ht", "c", "y", "ft", "g2", "hg", "ag"):
    cols, tgt = MODEL_COLS[fam], "y_" + fam
    m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, cols], D.loc[tr, tgt])
    mu[fam] = (m.predict(D[cols]), float(np.mean((D.loc[tr, tgt] - m.predict(D[cols])[tr]) ** 2 / m.predict(D[cols])[tr])))

cand = {
    # atuais
    "Golo na 1.ª parte": [(1 - np.exp(-mu["ht"][0]), D.y_ht > 0)],
    "Cantos (melhor linha)": [(s * (negbin_over_v := np.array([negbin_over(a, l, mu["c"][1]) for a in mu["c"][0]])) + (1 - s) * (1 - negbin_over_v),
                               (D.y_c > l) if s else (D.y_c < l)) for l in v2.LINES["c"] for s in (1, 0)],
    "Amarelos (melhor linha)": [(s * (o := np.array([negbin_over(a, l, mu["y"][1]) for a in mu["y"][0]])) + (1 - s) * (1 - o),
                                 (D.y_y > l) if s else (D.y_y < l)) for l in v2.LINES["y"] for s in (1, 0)],
    "Favorito ganha": [(np.maximum(D.pH, D.pA).values, np.where(D.pH >= D.pA, D.res == "H", D.res == "A"))],
    # candidatos
    "Golo na 2.ª parte": [(1 - np.exp(-mu["g2"][0]), D.y_g2 > 0)],
    "Mais de 1,5 golos": [(1 - np.exp(-mu["ft"][0]) * (1 + mu["ft"][0]), D.y_ft > 1.5)],
    "Equipa da casa marca": [(1 - np.exp(-mu["hg"][0]), D.y_hg > 0)],
    "Equipa de fora marca": [(1 - np.exp(-mu["ag"][0]), D.y_ag > 0)],
    "Dupla hipótese (favorito ou empate)": [((np.maximum(D.pH, D.pA) + D.pD).values, np.where(D.pH >= D.pA, D.res != "A", D.res != "H"))],
}
print(f"{len(D)} jogos · treino {tr.sum()} · teste {te.sum()}\n")
rows, cal = [], {}
for name, opts in cand.items():
    P_ = np.concatenate([np.asarray(p, float) for p, _ in opts]); Y_ = np.concatenate([np.asarray(y, float) for _, y in opts])
    T_ = np.concatenate([tr] * len(opts)); E_ = np.concatenate([te] * len(opts))
    pts = v2.pav(P_[T_], Y_[T_]); cal[name] = (pts, opts)
    pc = v2.cal_apply(pts, P_)
    base = Y_[E_].mean() if len(opts) == 1 else np.nan
    for lo in (0.80, 0.85, 0.90):
        m = E_ & (pc >= lo)
        rows.append([name, f"≥{lo:.0%}", int(m.sum() / (1 if len(opts) == 1 else 1)), round(100 * pc[m].mean(), 1) if m.sum() else None,
                     round(100 * Y_[m].mean(), 1) if m.sum() else None, round(100 * base, 1) if base == base else None])
print(pd.DataFrame(rows, columns=["mercado", "confiança", "apostas (teste)", "previsto %", "real %", "taxa base %"]).to_string(index=False))

# seleção diária (1 por jogo, 3 por dia, prob. calibrada entre 72% e 88%) com e sem candidatos
def daily(names):
    best = {}
    for name in names:
        pts, opts = cal[name]
        for p, y in opts:
            pc = v2.cal_apply(pts, np.asarray(p, float)); y = np.asarray(y, float)
            for i in np.where(te & (pc >= .72) & (pc <= .88))[0]:
                if i not in best or pc[i] > best[i][0]:
                    best[i] = (pc[i], y[i], name)
    K = pd.DataFrame([{"dt": D.dt[i], "p": v[0], "hit": v[1], "m": v[2]} for i, v in best.items()])
    day = K.sort_values("p", ascending=False).groupby("dt").head(3)
    g = day.groupby("dt").agg(n=("hit", "size"), h=("hit", "sum"))
    return len(day), 100 * day.hit.mean(), 100 * (g[g.n == 3].h == 3).mean(), day.m.value_counts().to_dict()
atuais = ["Golo na 1.ª parte", "Cantos (melhor linha)", "Amarelos (melhor linha)", "Favorito ganha"]
for lab, names in (("atuais", atuais), ("atuais + candidatos", list(cand))):
    n, h, t, mix = daily(names)
    print(f"\nseleção diária {lab}: {n} apostas · acerto {h:.1f}% · tripla certa {t:.1f}%\n   {mix}")
