"""Apostas de maior risco com valor: odds 1,80–2,50 acima do preço justo dão lucro a sério?

Preço justo = Pinnacle na abertura sem margem (método da potência, como a app). Aposta-se à melhor odd das casas
"soft" (Bet365, Bwin, Interwetten, William Hill, BetVictor) quando paga pelo menos (1 + margem) × justo.
Mede-se o acerto, o lucro (ROI) e o CLV contra o fecho da Pinnacle, em 1X2 e golos 2,5, de 2021/22 a 2025/26.
Uso: python3 valor_risco.py
"""
import glob, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SOFT = ["B365", "BW", "IW", "WH", "VC"]
MARKETS = {"1x2": (["H", "D", "A"], "PS{}", "PSC{}", "{}{}", lambda r: {"H": 0, "D": 1, "A": 2}[r["FTR"]]),
           "ou": ([">2.5", "<2.5"], "P{}", "PC{}", "{}{}", lambda r: 0 if r["FTHG"] + r["FTAG"] > 2.5 else 1)}


def fair_power(q):
    q = np.asarray(q, float)
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if (q ** -k).sum() > 1 else (lo, k)
    p = q ** -((lo + hi) / 2)
    return p / p.sum()


def bets():
    out = []
    for f in glob.glob(os.path.join(HERE, "data", "football-data", "*.csv")):
        lg, s = os.path.basename(f)[:-4].split("_")
        if s in ("2021", "2627"):
            continue
        d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False).dropna(subset=["FTHG", "FTAG", "FTR"])
        for mk, (sels, op, cl, soft, res) in MARKETS.items():
            oc, cc = [op.format(x) for x in sels], [cl.format(x) for x in sels]
            if not set(oc + cc) <= set(d.columns):
                continue
            for _, r in d.iterrows():
                o, c = r[oc].astype(float).values, r[cc].astype(float).values
                if np.isnan(o).any() or np.isnan(c).any() or (o <= 1).any():
                    continue
                po, pc, win = fair_power(o), fair_power(c), res(r)
                for i, x in enumerate(sels):
                    offers = [r[soft.format(b, x)] for b in SOFT if soft.format(b, x) in d.columns and pd.notna(r[soft.format(b, x)])]
                    if not offers:
                        continue
                    odd = float(max(offers))
                    out.append({"L": lg, "S": s, "mk": mk, "odd": odd, "p": po[i], "edge": odd * po[i] - 1,
                                "clv": odd * pc[i] - 1, "win": int(win == i)})
    return pd.DataFrame(out)


B = bets()
rows = []
for lo, hi in ((1.30, 1.80), (1.80, 2.50), (2.50, 3.50)):
    for e in (0.0, 0.02, 0.04):
        k = (B.odd >= lo) & (B.odd < hi) & (B.edge >= e)
        x = B[k]
        if len(x):
            rows.append([f"{lo:.2f}–{hi:.2f}", f"≥{e:.0%}", len(x), round(100 * x.p.mean(), 1), round(100 * x.win.mean(), 1),
                         round(x.odd.mean(), 2), round(100 * (x.win * x.odd - 1).mean(), 1), round(100 * x.clv.mean(), 1),
                         round(100 * (x.clv > 0).mean(), 0)])
print(pd.DataFrame(rows, columns=["odds", "margem", "apostas", "prob. justa %", "acerto %", "odd média", "ROI %", "CLV %", "CLV>0 %"]).to_string(index=False))
k = (B.odd >= 1.8) & (B.odd < 2.5) & (B.edge >= 0.02)
print("\n1,80–2,50 com margem ≥2%, por época (ROI %):", {s: round(100 * (g.win * g.odd - 1).mean(), 1) for s, g in B[k].groupby("S")})
print("por mercado:", {m: (len(g), round(100 * (g.win * g.odd - 1).mean(), 1)) for m, g in B[k].groupby("mk")})
