"""Avaliação fora da amostra: calibra em 2021/22–2024/25 e testa em 2025/26–2026/27.

Mede o acerto de cada mercado por nível de probabilidade e o de uma seleção diária de 3 apostas.
Uso: python3 especialista_avaliar.py   (depois de especialista_backtest.py)
"""
import json, os
import numpy as np, pandas as pd
from especialista_backtest import negbin_over

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = {"2122", "2223", "2324", "2425"}


def pav(p, y):
    """Regressão isotónica (pool adjacent violators): devolve pontos (p, acerto real) crescentes."""
    o = np.argsort(p); p, y = np.asarray(p)[o], np.asarray(y, float)[o]
    blocks = [[p[i], y[i], 1.0] for i in range(len(p))]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][1] / out[-2][2] > out[-1][1] / out[-1][2]:
            a, c = out.pop(), out.pop()
            out.append([(a[0] * a[2] + c[0] * c[2]) / (a[2] + c[2]), a[1] + c[1], a[2] + c[2]])
    return [(b[0], b[1] / b[2], b[2]) for b in out]


def apply_cal(cal, p):
    xs = np.array([c[0] for c in cal]); ys = np.array([c[1] for c in cal])
    return np.interp(p, xs, ys)


P = pd.read_pickle(os.path.join(HERE, "results", "especialista.pkl"))
P = P[P.S != "2021"].copy()
cands = {
    "Golo na 1.ª parte: sim": (P.p_ht.values, P.ht_goal.values),
    "Cantos: mais de 8,5": (np.array([negbin_over(m, 8.5, d) for m, d in zip(P.c_mu, P.c_disp)]), (P.corners > 8.5).astype(int).values),
    "Cantos: menos de 10,5": (1 - np.array([negbin_over(m, 10.5, d) for m, d in zip(P.c_mu, P.c_disp)]), (P.corners < 10.5).astype(int).values),
    "Amarelos: mais de 3,5": (np.array([negbin_over(m, 3.5, d) for m, d in zip(P.y_mu, P.y_disp)]), (P.yellows > 3.5).astype(int).values),
    "Amarelos: menos de 4,5": (1 - np.array([negbin_over(m, 4.5, d) for m, d in zip(P.y_mu, P.y_disp)]), (P.yellows < 4.5).astype(int).values),
    "1X2: favorito ganha": (P.fav_p.astype(float).values, P.fav_win.astype(float).values),
}
train = P.S.isin(TRAIN).values
cals, rows, picks = {}, [], []
for name, (p, y) in cands.items():
    ok = ~np.isnan(p) & ~np.isnan(y)
    cal = pav(p[train & ok], y[train & ok])
    # comprime a tabela em pontos com pelo menos 30 jogos para não sobreajustar
    pts, acc = [], [0, 0, 0]
    for x, r, n in cal:
        acc = [acc[0] + x * n, acc[1] + r * n, acc[2] + n]
        if acc[2] >= 30:
            pts.append((acc[0] / acc[2], acc[1] / acc[2], acc[2])); acc = [0, 0, 0]
    cals[name] = [(round(a, 4), round(b, 4)) for a, b, _ in pts]
    pc = apply_cal(pts, p)
    test = ~train & ok
    for lo in (0.70, 0.75, 0.80):
        m = test & (pc >= lo)
        rows.append([name, f"≥{lo:.0%}", int(m.sum()), round(100 * pc[m].mean(), 1) if m.sum() else None, round(100 * y[m].mean(), 1) if m.sum() else None])
    for i in np.where(test)[0]:
        picks.append({"dt": P.dt.iloc[i], "jogo": P.home.iloc[i] + " – " + P.away.iloc[i], "mercado": name, "p": pc[i], "hit": y[i]})

print("=== Acerto fora da amostra (2025/26–2026/27), por probabilidade calibrada ===")
print(pd.DataFrame(rows, columns=["mercado", "confiança", "apostas", "previsto %", "real %"]).to_string(index=False))

K = pd.DataFrame(picks)
K = K.sort_values("p", ascending=False).drop_duplicates(["dt", "jogo"])  # no máximo 1 aposta por jogo
print("\n=== Seleção diária: as 3 apostas mais prováveis de cada dia (mín. 72%) ===")
for thr in (0.72, 0.76):
    day = K[K.p >= thr].sort_values("p", ascending=False).groupby("dt").head(3)
    g = day.groupby("dt").agg(n=("hit", "size"), hits=("hit", "sum"), p=("p", "prod"))
    n3 = g[g.n == 3]
    print(f"limiar {thr:.0%}: {len(day)} apostas em {g.shape[0]} dias · acerto {100 * day.hit.mean():.1f}% (previsto {100 * day.p.mean():.1f}%)"
          f" · boletim de 3 certo em {100 * (n3.hits == 3).mean():.1f}% dos dias (previsto {100 * n3.p.mean():.1f}%, {len(n3)} dias)")
    print("   por mercado:", day.groupby("mercado").hit.agg(["size", "mean"]).round(3).to_dict("index"))
    two = day.groupby("dt").head(2).groupby("dt").agg(n=("hit", "size"), hits=("hit", "sum"))
    two = two[two.n == 2]
    print(f"   boletim de 2: certo em {100 * (two.hits == 2).mean():.1f}% dos dias ({len(two)} dias)")
json.dump(cals, open(os.path.join(HERE, "app", "data", "calibracao.json"), "w"), ensure_ascii=False, indent=1)
print("\ncalibração guardada em app/data/calibracao.json")

# --- calibração de produção: todas as épocas (o futebol de agora pesa) + acerto histórico por faixa ---
prod = {}
for name, (p, y) in cands.items():
    ok = ~np.isnan(p) & ~np.isnan(y)
    w_recent = P.S.isin({"2526", "2627"}).values
    # as épocas recentes contam a dobrar: repetem-se na amostra
    pp = np.concatenate([p[ok], p[ok & w_recent]]); yy = np.concatenate([y[ok], y[ok & w_recent]])
    cal = pav(pp, yy)
    pts, acc = [], [0, 0, 0]
    for x, r, n in cal:
        acc = [acc[0] + x * n, acc[1] + r * n, acc[2] + n]
        if acc[2] >= 40:
            pts.append((acc[0] / acc[2], acc[1] / acc[2], acc[2])); acc = [0, 0, 0]
    pc = apply_cal(pts, p)
    bands = {}
    for lo, hi in ((0.70, 0.75), (0.75, 0.80), (0.80, 1.01)):
        m = ok & (pc >= lo) & (pc < hi)
        if m.sum():
            bands[f"{lo:.2f}"] = {"n": int(m.sum()), "acerto": round(float(y[m].mean()), 3)}
    prod[name] = {"cal": [(round(a, 4), round(b, 4)) for a, b, _ in pts], "faixas": bands}
json.dump(prod, open(os.path.join(HERE, "app", "data", "calibracao.json"), "w"), ensure_ascii=False, indent=1)
print("calibração de produção:", {k: v["faixas"] for k, v in prod.items()})
