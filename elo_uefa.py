"""Afina e testa o Elo próprio nos jogos das taças europeias.

Escolhe K, vantagem de casa e Elo inicial dos clubes de fora das 6 ligas pela perda logarítmica nas taças de
2022/23–2024/25; testa nas taças de 2025/26–2026/27 contra a referência ingénua (frequências de 1/X/2).
Só exporta para app/data/modelos.json ("elo") se o teste for claramente melhor. Uso: python3 elo_uefa.py
"""
import itertools, json, math, os, sys
from datetime import datetime
import numpy as np
from scipy.optimize import minimize
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import elo  # noqa: E402

VAL = (datetime(2022, 7, 1), datetime(2025, 7, 1))
TEST = datetime(2025, 7, 1)


def outcome(g):
    return 2 if g["hg"] > g["ag"] else 1 if g["hg"] == g["ag"] else 0  # 0 fora, 1 empate, 2 casa


def fit_logit(diffs, ys):
    x, y = np.asarray(diffs) / 400, np.asarray(ys)

    def nll(t):
        b, c1, d = t
        c2 = c1 + math.exp(d)
        sa = 1 / (1 + np.exp(-(c1 - b * x)))
        sh = 1 - 1 / (1 + np.exp(-(c2 - b * x)))
        p = np.where(y == 0, sa, np.where(y == 2, sh, 1 - sa - sh))
        return -np.mean(np.log(np.clip(p, 1e-9, 1)))
    r = minimize(nll, [1.5, -0.6, -0.3], method="Nelder-Mead", options={"maxiter": 4000})
    b, c1, d = r.x
    return {"beta": float(b), "c1": float(c1), "c2": float(c1 + math.exp(d))}


def logloss(rows, p):
    ll = []
    for diff, y in rows:
        pr = elo.probs(diff, p)[::-1]  # (fora, empate, casa)
        ll.append(-math.log(max(pr[y], 1e-9)))
    return float(np.mean(ll))


def main():
    games, nm = elo.all_games()
    fd = {g["home"] for g in games if not g["cup"]}
    cups = [g for g in games if g["cup"]]
    print(f"jogos: {len(games)} ({len(cups)} das taças) · clubes das taças ligados às 6 ligas: {len({v for v in nm.values() if v in fd})}")
    best = None
    for K, H, out in itertools.product((15, 20, 30), (50, 70, 90), (1350, 1450, 1500)):
        R, hist = elo.run(games, K, H, outsider=out, fd_teams=fd)
        train = [(d, outcome(g)) for g, d in hist if g["dt"] < VAL[0] and g["dt"] >= datetime(2021, 7, 1)]
        p = fit_logit(*zip(*train))
        val = [(d, outcome(g)) for g, d in hist if g["cup"] and VAL[0] <= g["dt"] < VAL[1]]
        s = logloss(val, p)
        if not best or s < best[0]:
            best = (s, K, H, out, p, hist)
    s, K, H, out, _, hist = best
    fit = [(d, outcome(g)) for g, d in hist if g["cup"] and datetime(2022, 7, 1) <= g["dt"] < TEST]  # taças: o empate e a vantagem de casa são diferentes das ligas
    p = fit_logit(*zip(*fit))
    test = [(d, outcome(g)) for g, d in hist if g["cup"] and g["dt"] >= TEST]
    base_rows = [outcome(g) for g, d in hist if g["cup"] and VAL[0] <= g["dt"] < TEST]
    freq = [base_rows.count(k) / len(base_rows) for k in (0, 1, 2)]
    naive = float(np.mean([-math.log(freq[y]) for _, y in test]))
    ll = logloss(test, p)
    print(f"melhor: K={K} casa={H} inicial fora das ligas={out} · validação {s:.4f}")
    print(f"teste taças 2025/26–2026/27: {len(test)} jogos · Elo {ll:.4f} · ingénuo {naive:.4f}")
    # calibração do resultado mais provável
    rows = []
    for d, y in test:
        pr = elo.probs(d, p)[::-1]
        k = int(np.argmax(pr))
        rows.append((pr[k], int(y == k)))
    rows = np.array(rows)
    for a, b in ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 1.01)):
        k = (rows[:, 0] >= a) & (rows[:, 0] < b)
        if k.sum():
            print(f"  favorito com {a:.0%}–{min(b, 1):.0%}: {k.sum()} jogos · previsto {100 * rows[k, 0].mean():.1f}% · real {100 * rows[k, 1].mean():.1f}%")
    if ll < naive - 0.02:
        path = os.path.join(HERE, "app", "data", "modelos.json")
        M = json.load(open(path))
        M["elo"] = {"K": K, "H": H, "outsider": out, **{k: round(v, 5) for k, v in p.items()},
                    "teste": {"jogos": len(test), "logloss": round(ll, 4), "ingenuo": round(naive, 4)}}
        json.dump(M, open(path, "w"), indent=1)
        print("Elo exportado para a app")
    else:
        print("Elo NÃO exportado: não bate a referência ingénua com margem")


if __name__ == "__main__":
    main()
