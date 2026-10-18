"""Fiabilidade por liga × mercado: corrige a confiança onde o modelo erra sistematicamente numa liga.

Mede, no treino, a diferença entre acerto real e previsto (apostas >= 72%) por liga e mercado, com
encolhimento; testa se aplicar essa correção melhora a seleção diária fora da amostra; exporta-a.
"""
import json, os
import numpy as np, pandas as pd
import especialista_v2 as v2
from sklearn.linear_model import PoissonRegressor
from features import MODEL_COLS, negbin_over

HERE = os.path.dirname(os.path.abspath(__file__))
SHRINK = 150

D = v2.build()
D = D[D.S != "2021"].reset_index(drop=True)
tr = D.S.isin(v2.TRAIN).values
te = ~tr
mods = {}
for fam, target in (("ht", "y_ht"), ("c", "y_c"), ("y", "y_y")):
    cols = MODEL_COLS[fam]
    m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, cols], D.loc[tr, target])
    mu = m.predict(D[cols])
    mods[fam] = (mu, float(np.mean((D.loc[tr, target] - mu[tr]) ** 2 / mu[tr])))

# candidatos: (chave, linha) -> (p bruto, acertou)
cand = {("ht+", 0.5): (1 - np.exp(-mods["ht"][0]), (D.y_ht > 0.5).values.astype(float))}
for fam in ("c", "y"):
    mu, disp = mods[fam]
    for line in v2.LINES[fam]:
        po = np.array([negbin_over(a, line, disp) for a in mu])
        cand[(fam + "+", line)] = (po, (D["y_" + fam] > line).values.astype(float))
        cand[(fam + "-", line)] = (1 - po, (D["y_" + fam] < line).values.astype(float))
cand[("fav", 0)] = (D.fav_p.values.astype(float), D.fav_win.values.astype(float))

cal = {}
for key in {k for k, _ in cand}:
    P_ = np.concatenate([cand[c][0] for c in cand if c[0] == key]); Y_ = np.concatenate([cand[c][1] for c in cand if c[0] == key])
    T_ = np.concatenate([tr for c in cand if c[0] == key]); ok = ~np.isnan(P_) & ~np.isnan(Y_)
    cal[key] = v2.pav(P_[T_ & ok], Y_[T_ & ok])
pc = {c: v2.cal_apply(cal[c[0]], v[0]) for c, v in cand.items()}

# correção por liga × mercado, só com o treino
offs = {}
for key in cal:
    for lg in D.L.unique():
        ps, ys = [], []
        for c in cand:
            if c[0] != key:
                continue
            m = tr & (D.L.values == lg) & (pc[c] >= 0.72) & ~np.isnan(cand[c][1])
            ps.append(pc[c][m]); ys.append(cand[c][1][m])
        ps, ys = np.concatenate(ps), np.concatenate(ys)
        if len(ps):
            offs[(lg, key)] = float((ys.mean() - ps.mean()) * len(ps) / (len(ps) + SHRINK))


def select(use_offs):
    picks = []
    for i in np.where(te)[0]:
        best = None
        for c, (p, y) in cand.items():
            if np.isnan(p[i]) or np.isnan(y[i]):
                continue
            q = pc[c][i] + (offs.get((D.L[i], c[0]), 0) if use_offs else 0)
            if q > 0.88:
                continue
            if best is None or q > best[0]:
                best = (q, c[0], y[i])
        if best and best[0] >= 0.72:
            picks.append({"dt": D.dt[i], "p": best[0], "m": best[1], "hit": best[2]})
    K = pd.DataFrame(picks)
    day = K.sort_values("p", ascending=False).groupby("dt").head(3)
    g = day.groupby("dt").agg(n=("hit", "size"), h=("hit", "sum"))
    d2 = day.groupby("dt").head(2).groupby("dt").agg(n=("hit", "size"), h=("hit", "sum"))
    return len(day), day.hit.mean(), (d2[d2.n == 2].h == 2).mean(), (g[g.n == 3].h == 3).mean()


for flag in (False, True):
    n, hit, dup, trip = select(flag)
    print(f"{'com' if flag else 'sem'} correção por liga: {n} apostas · acerto {100 * hit:.1f}% · dupla {100 * dup:.1f}% · tripla {100 * trip:.1f}%")
print("\nmaiores correções (treino):")
for (lg, key), v in sorted(offs.items(), key=lambda x: -abs(x[1]))[:10]:
    print(f"  {lg} {key}: {v * 100:+.1f} pp")

# exportar correções calculadas com todas as épocas (para produção)
allo = {}
for key in cal:
    for lg in D.L.unique():
        ps, ys = [], []
        for c in cand:
            if c[0] == key:
                m = (D.L.values == lg) & (pc[c] >= 0.72) & ~np.isnan(cand[c][1])
                ps.append(pc[c][m]); ys.append(cand[c][1][m])
        ps, ys = np.concatenate(ps), np.concatenate(ys)
        if len(ps):
            allo.setdefault(lg, {})[key] = {"ajuste": round(float((ys.mean() - ps.mean()) * len(ps) / (len(ps) + SHRINK)), 4),
                                            "n": int(len(ps)), "acerto": round(float(ys.mean()), 3)}
path = os.path.join(HERE, "app", "data", "modelos.json")
M = json.load(open(path)); M["ligas"] = allo; json.dump(M, open(path, "w"), indent=1)
print("\ncorreções por liga gravadas em modelos.json")
