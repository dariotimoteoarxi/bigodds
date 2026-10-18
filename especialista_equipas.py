"""Acerto por equipa e aprendizagem por equipa.

1. Para cada equipa e família de mercado: quantas apostas da faixa da app (≥72%) o modelo fez nas épocas de teste
   (2025/26–2026/27, fora da amostra), quanto previa e quanto acertou. Exporta app/data/equipas.json.
2. Teste: corrigir a probabilidade pelo historial recente da equipa (erro médio encolhido, só com jogos anteriores)
   melhora a previsão? Mede a perda logarítmica e a calibração das apostas no teste.
Uso: python3 especialista_equipas.py
"""
import json, math, os, sys
from collections import defaultdict
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from consultor import FAMILY, calibrate  # noqa: E402
from features import negbin_over, predict_mu  # noqa: E402

M = json.load(open(os.path.join(HERE, "app", "data", "modelos.json")))
MOD, CAL, LINES = M["models"], M["cal"], M["lines"]


def predictions():
    D = v2.build()
    D = D[D.S != "2021"].sort_values("dt").reset_index(drop=True)
    rows = []
    for r in D.to_dict("records"):
        mu = {k: predict_mu(MOD[k], r) for k in ("ht", "c", "y", "g2", "hg", "ag")}
        c = [("ht+", 1 - math.exp(-mu["ht"]), r["y_ht"] > 0), ("g2+", 1 - math.exp(-mu["g2"]), r["y_g2"] > 0),
             ("hs", 1 - math.exp(-mu["hg"]), r["y_hg"] > 0), ("as", 1 - math.exp(-mu["ag"]), r["y_ag"] > 0)]
        for fam, y in (("c", r["y_c"]), ("y", r["y_y"])):
            for line in LINES[fam]:
                po = negbin_over(mu[fam], line, MOD[fam]["disp"])
                c += [(fam + "+", po, y > line), (fam + "-", 1 - po, y < line)]
        for key, p_raw, hit in c:
            p = calibrate(CAL, key, p_raw)
            if p >= 0.72:  # só o que a app chegaria a sugerir
                rows.append({"dt": r["dt"], "S": r["S"], "L": r["L"], "home": r["home"], "away": r["away"], "key": key,
                             "fam": FAMILY.get(key, key), "p": p, "hit": int(hit)})
    return pd.DataFrame(rows)


def learn_test(P, K):
    """Corrige p pelo erro médio (real − previsto) das duas equipas nessa família, encolhido com K apostas fictícias."""
    acc = defaultdict(lambda: [0.0, 0])  # (equipa, família) -> [soma dos erros, n]
    adj = np.zeros(len(P))
    for d, g in P.groupby("dt", sort=True):
        for i, r in g.iterrows():
            e = [acc[(t, r.fam)] for t in (r.home, r.away)]
            adj[i] = sum(s / (n + K) for s, n in e) / 2
        for i, r in g.iterrows():  # só depois do dia: nada do próprio jogo entra na correção
            for t in (r.home, r.away):
                acc[(t, r.fam)][0] += r.hit - r.p
                acc[(t, r.fam)][1] += 1
    return np.clip(P.p.values + np.clip(adj, -0.05, 0.05), 0.01, 0.99)


def main():
    P = predictions()
    te = ~P.S.isin(v2.TRAIN)
    ll = lambda p, y: -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    y = P.hit.values[te]
    print(f"apostas ≥72% no teste: {te.sum()} · previsto {100 * P.p[te].mean():.1f}% · real {100 * y.mean():.1f}%")
    print(f"sem correção por equipa: perda log. {ll(np.clip(P.p.values[te], 0.01, 0.99), y):.4f}")
    for K in (30, 100, 300):
        q = learn_test(P, K)[te]
        top = q >= 0.80
        print(f"com correção (K={K}): perda log. {ll(q, y):.4f} · apostas ≥80%: {top.sum()} previsto {100 * q[top].mean():.1f}% real {100 * y[top].mean():.1f}%")
    base_top = P.p.values[te] >= 0.80
    print(f"referência sem correção · apostas ≥80%: {base_top.sum()} previsto {100 * P.p.values[te][base_top].mean():.1f}% real {100 * y[base_top].mean():.1f}%")

    # acerto por equipa (teste, fora da amostra)
    T = P[te]
    out = {}
    for side in ("home", "away"):
        for (team, fam), g in T.groupby([side, "fam"]):
            x = out.setdefault(team, {}).setdefault(fam, {"n": 0, "p": 0.0, "hit": 0})
            x["n"] += len(g); x["p"] += g.p.sum(); x["hit"] += int(g.hit.sum())
    for team, fams in out.items():
        for fam, x in fams.items():
            x["previsto"], x["real"] = round(x.pop("p") / x["n"], 3), round(x["hit"] / x["n"], 3)
    leagues = {t: l for l, t in zip(T.L, T.home)}
    bins = [(0.72, 0.76), (0.76, 0.80), (0.80, 0.84), (0.84, 0.88), (0.88, 1.01)]
    calib = [{"faixa": f"{int(a * 100)}–{min(int(b * 100), 100)}%", "n": int(k.sum()), "previsto": round(float(T.p[k].mean()), 3), "real": round(float(T.hit[k].mean()), 3)}
             for a, b in bins for k in [(T.p >= a) & (T.p < b)] if k.sum()]
    print("calibração (teste):", calib)
    json.dump({"fonte": "teste 2025/26–2026/27, apostas do modelo ≥72%", "equipas": out, "ligas": leagues, "calibracao": calib},
              open(os.path.join(HERE, "app", "data", "equipas.json"), "w"), ensure_ascii=False, indent=0)
    tot = sorted(((t, sum(x["n"] for x in f.values()), sum(x["hit"] for x in f.values())) for t, f in out.items()), key=lambda z: -z[2] / z[1])
    print("melhores equipas:", [(t, n, round(100 * h / n, 1)) for t, n, h in tot[:5]])
    print("piores equipas:", [(t, n, round(100 * h / n, 1)) for t, n, h in tot[-5:]])


if __name__ == "__main__":
    main()
