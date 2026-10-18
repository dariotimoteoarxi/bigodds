"""Afinação dos mercados de especialista (v2): regressões de Poisson com as variáveis de app/features.py.

Treina em 2021/22–2024/25, testa em 2025/26–2026/27 contra a versão base, calibra por mercado e linha
e exporta app/data/modelos.json para a app. Uso: python3 especialista_v2.py
"""
import csv, glob, json, math, os, sys
from collections import defaultdict, deque
from datetime import datetime
import numpy as np, pandas as pd
from sklearn.linear_model import PoissonRegressor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
from features import MODEL_COLS, entry, features, league_entry, negbin_over, num  # noqa: E402

TRAIN = {"2122", "2223", "2324", "2425"}
LINES = {"c": [7.5, 8.5, 9.5, 10.5, 11.5], "y": [2.5, 3.5, 4.5, 5.5]}


def fair(row, cols):
    q = [num(row, c) for c in cols]
    if None in q or min(q) <= 1:
        return None
    q = [1 / x for x in q]
    return [x / sum(q) for x in q]


def build():
    out = []
    for lg in ("E0", "SP1", "I1", "D1", "F1", "P1"):
        rows = []
        for f in glob.glob(os.path.join(HERE, "data", "football-data", f"{lg}_*.csv")):
            s = os.path.basename(f)[:-4].split("_")[1]
            with open(f, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    if r.get("Date") and r.get("HomeTeam"):
                        r["S"], r["dt"] = s, datetime.strptime(r["Date"], "%d/%m/%Y")
                        rows.append(r)
        rows.sort(key=lambda r: r["dt"])
        hist, league = defaultdict(lambda: deque(maxlen=20)), deque(maxlen=380)
        for r in rows:
            h, a = r["HomeTeam"], r["AwayTeam"]
            x = fair(r, ["AvgH", "AvgD", "AvgA"])
            o = fair(r, ["Avg>2.5", "Avg<2.5"])
            mk = {"pH": x[0] if x else None, "pA": x[2] if x else None, "po": o[0] if o else None}
            ft = features(list(hist[h]), list(hist[a]), list(league), mk)
            eh, ea, el = entry(r, h), entry(r, a), league_entry(r)
            if ft and eh and el:
                fav = max(x[0], x[2]) if x else None
                out.append({**ft, "L": lg, "S": r["S"], "dt": r["dt"], "home": h, "away": a,
                            "y_ht": eh["htf"] + eh["hta"], "y_c": el["c"], "y_y": el["y"],
                            "y_ft": el["fth"] + el["fta"], "y_g2": el["fth"] + el["fta"] - el["hth"] - el["hta"],
                            "y_hg": el["fth"], "y_ag": el["fta"], "y_hc": float(r["HC"]), "y_ac": float(r["AC"]), "y_hy": float(r["HY"]), "y_hth": el["hth"], "y_hta": el["hta"], "pH": x[0] if x else None, "pD": x[1] if x else None,
                            "pA": x[2] if x else None, "res": r["FTR"],
                            "fav_p": fav, "fav_win": (int(r["FTR"] == ("H" if x[0] >= x[2] else "A")) if x else None)})
            if eh and ea:
                hist[h].append(eh)
                hist[a].append(ea)
            if el:
                league.append(el)
    return pd.DataFrame(out)


def pav(p, y, w=None):
    o = np.argsort(p)
    p, y = np.asarray(p, float)[o], np.asarray(y, float)[o]
    w = np.ones(len(p)) if w is None else np.asarray(w, float)[o]
    out = []
    for i in range(len(p)):
        out.append([p[i] * w[i], y[i] * w[i], w[i]])
        while len(out) > 1 and out[-2][1] / out[-2][2] > out[-1][1] / out[-1][2]:
            a, b = out.pop(), out.pop()
            out.append([a[0] + b[0], a[1] + b[1], a[2] + b[2]])
    pts, acc = [], [0, 0, 0]
    for s0, s1, n in out:  # agrupa em pontos com >= 40 jogos (equivalentes) para não sobreajustar
        acc = [acc[0] + s0, acc[1] + s1, acc[2] + n]
        if acc[2] >= 40:
            pts.append((acc[0] / acc[2], acc[1] / acc[2]))
            acc = [0, 0, 0]
    return pts


def cal_apply(pts, p):
    return np.interp(p, [a for a, _ in pts], [b for _, b in pts])


def logloss(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


if __name__ == "__main__":
    D = build()
    D = D[D.S != "2021"].reset_index(drop=True)
    tr = D.S.isin(TRAIN).values
    te = ~tr
    print(f"{len(D)} jogos · treino {tr.sum()} · teste {te.sum()}\n")
    models, preds = {}, {}
    for fam, target in (("ht", "y_ht"), ("c", "y_c"), ("y", "y_y"), ("g2", "y_g2"), ("hg", "y_hg"), ("ag", "y_ag")):
        cols = MODEL_COLS[fam]
        m = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, cols], D.loc[tr, target])
        mu = m.predict(D[cols])
        disp = float(np.mean((D.loc[tr, target] - mu[tr]) ** 2 / mu[tr]))
        models[fam] = {"cols": cols, "coef": [round(float(c), 5) for c in m.coef_], "intercept": round(float(m.intercept_), 5), "disp": round(disp, 4)}
        base_cols = {"ht": ["ht_model", "ht_mkt"], "c": ["c_base", "c_lg"], "y": ["y_base", "y_lg"]}.get(fam, cols)
        b = PoissonRegressor(alpha=1e-4, max_iter=500).fit(D.loc[tr, base_cols], D.loc[tr, target])
        preds[fam] = (mu, b.predict(D[base_cols]), disp)
        print(f"{fam}: coeficientes {dict(zip(cols, np.round(m.coef_, 3)))} · dispersão {disp:.2f}")

    # candidatos por mercado/direção/linha
    cand = {}
    mu, mub, _ = preds["ht"]
    cand["ht+"] = {0.5: (1 - np.exp(-mu), 1 - np.exp(-mub), (D.y_ht > 0.5).values)}
    for fam in ("c", "y"):
        mu, mub, disp = preds[fam]
        tgt = D["y_" + fam].values
        for side in ("+", "-"):
            cand[fam + side] = {}
            for line in LINES[fam]:
                po = np.array([negbin_over(a, line, disp) for a in mu])
                pb = np.array([negbin_over(a, line, disp) for a in mub])
                cand[fam + side][line] = (po, pb, tgt > line) if side == "+" else (1 - po, 1 - pb, tgt < line)
    cand["fav"] = {0: (D.fav_p.values.astype(float), D.fav_p.values.astype(float), D.fav_win.values.astype(float))}
    # mercados acrescentados (teste em especialista_novos.py): golo na 2.ª parte, equipa marca, dupla hipótese
    for key, fam, tgt in (("g2+", "g2", D.y_g2 > 0.5), ("hs", "hg", D.y_hg > 0.5), ("as", "ag", D.y_ag > 0.5)):
        mu, _, _ = preds[fam]
        cand[key] = {0.5: (1 - np.exp(-mu), 1 - np.exp(-mu), tgt.values)}
    pH, pD, pA = D.pH.astype(float).values, D.pD.astype(float).values, D.pA.astype(float).values
    dc = np.where(pH >= pA, pH + pD, pA + pD)
    dc_hit = np.where(pH >= pA, D.res != "A", D.res != "H").astype(float)
    dc_hit[np.isnan(dc)] = np.nan
    cand["dc"] = {0: (dc, dc, dc_hit)}

    print("\n=== Teste 2025/26–2026/27: perda logarítmica (menor = melhor), modelo novo vs base ===")
    for key, lines in cand.items():
        for line, (p, pb, y) in lines.items():
            ok = te & ~np.isnan(p) & ~np.isnan(y.astype(float))
            if key != "fav" and line in (0.5, 8.5, 9.5, 3.5, 4.5):
                print(f"{key} {line}: novo {logloss(p[ok], y[ok]):.4f} · base {logloss(pb[ok], y[ok]):.4f}")

    # calibração por mercado-direção (todas as linhas juntas), treino → teste
    print("\n=== Acerto no teste por faixa calibrada (todas as linhas) ===")
    out_cal, rows = {}, []
    for key, lines in cand.items():
        P_ = np.concatenate([v[0] for v in lines.values()]); Y_ = np.concatenate([np.asarray(v[2], float) for v in lines.values()])
        T_ = np.concatenate([tr for _ in lines]); E_ = np.concatenate([te for _ in lines])
        ok = ~np.isnan(P_) & ~np.isnan(Y_)
        pts = pav(P_[T_ & ok], Y_[T_ & ok])
        pc = cal_apply(pts, P_)
        for lo, hi in ((0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.01)):
            m = E_ & ok & (pc >= lo) & (pc < hi)
            if m.sum() >= 20:
                rows.append([key, f"{lo:.0%}–{min(hi, 1):.0%}", int(m.sum()), round(100 * pc[m].mean(), 1), round(100 * Y_[m].mean(), 1)])
        # produção: todas as épocas, as recentes a contar a dobrar
        w = np.concatenate([np.where(D.S.isin({"2526", "2627"}), 2.0, 1.0) for _ in lines])
        out_cal[key] = pav(P_[ok], Y_[ok], w[ok])
    print(pd.DataFrame(rows, columns=["mercado", "faixa", "n", "previsto %", "real %"]).to_string(index=False))

    # escolha da linha por jogo e seleção diária (teste, calibração de treino)
    print("\n=== Seleção diária no teste: melhor linha por mercado, 1 aposta por jogo ===")
    picks = []
    tr_cal = {}
    for key, lines in cand.items():
        P_ = np.concatenate([v[0] for v in lines.values()]); Y_ = np.concatenate([np.asarray(v[2], float) for v in lines.values()])
        T_ = np.concatenate([tr for _ in lines]); ok = ~np.isnan(P_) & ~np.isnan(Y_)
        tr_cal[key] = pav(P_[T_ & ok], Y_[T_ & ok])
    for i in np.where(te)[0]:
        best = None
        for key, lines in cand.items():
            for line, (p, _, y) in lines.items():
                if np.isnan(p[i]):
                    continue
                pc = float(cal_apply(tr_cal[key], p[i]))
                if pc > 0.88:  # demasiado óbvio: odd sem interesse
                    continue
                if best is None or pc > best[0]:
                    best = (pc, key, line, float(y[i]))
        if best and best[0] >= 0.72:
            picks.append({"dt": D.dt[i], "p": best[0], "mercado": best[1], "linha": best[2], "hit": best[3]})
    K = pd.DataFrame(picks)
    for thr in (0.72, 0.76, 0.80):
        day = K[K.p >= thr].sort_values("p", ascending=False).groupby("dt").head(3)
        g = day.groupby("dt").agg(n=("hit", "size"), h=("hit", "sum"), p=("p", "prod"))
        n2 = day.groupby("dt").head(2).groupby("dt").agg(n=("hit", "size"), h=("hit", "sum"))
        print(f"limiar {thr:.0%}: {len(day)} apostas · acerto {100 * day.hit.mean():.1f}% (previsto {100 * day.p.mean():.1f}%)"
              f" · dupla certa {100 * (n2[n2.n == 2].h == 2).mean():.1f}% · tripla certa {100 * (g[g.n == 3].h == 3).mean():.1f}% ({(g.n == 3).sum()} dias)")
        print("   por mercado:", {k: f"{v['size']} · {100 * v['mean']:.0f}%" for k, v in day.groupby("mercado").hit.agg(["size", "mean"]).to_dict("index").items()})

    faixas = {}
    for key, lines in cand.items():
        P_ = np.concatenate([v[0] for v in lines.values()]); Y_ = np.concatenate([np.asarray(v[2], float) for v in lines.values()])
        ok = ~np.isnan(P_) & ~np.isnan(Y_)
        pc = cal_apply(out_cal[key], P_)
        faixas[key] = {}
        for lo, hi in ((0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.01)):
            m = ok & (pc >= lo) & (pc < hi)
            if m.sum() >= 30:
                faixas[key][f"{lo:.2f}"] = {"n": int(m.sum()), "acerto": round(float(Y_[m].mean()), 3)}
    json.dump({"models": models, "lines": LINES, "faixas": faixas, "boletins": {"2": 0.759, "3": 0.622},
               "cal": {k: [(round(a, 4), round(b, 4)) for a, b in v] for k, v in out_cal.items()}},
              open(os.path.join(HERE, "app", "data", "modelos.json"), "w"), indent=1)
    print("\nmodelos exportados para app/data/modelos.json")
