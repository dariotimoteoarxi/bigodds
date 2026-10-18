"""Backtest walk-forward do modelo de golos (Dixon-Coles com decaimento temporal) nas 6 ligas.

Pergunta: as probabilidades do modelo batem a odd de ABERTURA, e as apostas com valor contra a abertura
ganham à odd de FECHO (CLV)? Só se usa informação disponível quando a abertura foi recolhida
(o football-data recolhe à sexta para o fim de semana e à terça para o meio da semana).

Uso:  python3 backtest.py            -> escreve results/bets.csv e imprime o resumo
"""
import glob, os, warnings
import numpy as np, pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

warnings.simplefilter("ignore", pd.errors.PerformanceWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
LEAGUES = {"E0": "Inglaterra", "SP1": "Espanha", "I1": "Itália", "D1": "Alemanha", "F1": "França", "P1": "Portugal"}
XI = 0.0019          # decaimento por dia (meia-vida ~1 ano), valor clássico de Dixon-Coles
HISTORY_DAYS = 730
PROMOTED_PRIOR = -0.25  # equipas sem época anterior na liga começam abaixo da média
MAXG = 10


def load():
    frames = []
    for f in glob.glob(os.path.join(HERE, "data", "football-data", "*.csv")):
        l, s = os.path.basename(f)[:-4].split("_")
        if l in LEAGUES and s != "2627":
            d = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
            frames.append(d.assign(L=l, S=s))
    D = pd.concat(frames, ignore_index=True).dropna(subset=["FTHG", "FTAG", "HomeTeam", "AwayTeam"])
    D["dt"] = pd.to_datetime(D.Date, dayfirst=True)
    return D.sort_values(["L", "dt"]).reset_index(drop=True)


def cutoff(d):
    """Dia de recolha da odd de abertura: a última terça (1) ou sexta (4) até à data do jogo."""
    back = min((d.weekday() - w) % 7 for w in (1, 4))
    return d - pd.Timedelta(days=back)


def fit(train, teams, prior, x0):
    """Poisson ponderado: log lam_casa = mu + casa + ataque_c - defesa_f. Devolve parâmetros e rho de Dixon-Coles."""
    n = len(teams)
    hi, ai = train.hi.values, train.ai.values
    hg, ag, w = train.FTHG.values, train.FTAG.values, train.w.values
    lam_prior = 1.0  # força do prior: equivale a ~1 jogo completo de informação

    def nll(p):
        mu, home, att, de = p[0], p[1], p[2:2 + n], p[2 + n:]
        lh = np.exp(mu + home + att[hi] - de[ai])
        la = np.exp(mu + att[ai] - de[hi])
        f = np.sum(w * (lh - hg * np.log(lh) + la - ag * np.log(la)))
        f += lam_prior * (np.sum((att - prior) ** 2) + np.sum((de - prior) ** 2))
        rh, ra = w * (lh - hg), w * (la - ag)
        g = np.empty_like(p)
        g[0] = rh.sum() + ra.sum()
        g[1] = rh.sum()
        g[2:2 + n] = np.bincount(hi, rh, n) + np.bincount(ai, ra, n) + 2 * lam_prior * (att - prior)
        g[2 + n:] = -np.bincount(ai, rh, n) - np.bincount(hi, ra, n) + 2 * lam_prior * (de - prior)
        return f, g

    p = minimize(nll, x0, jac=True, method="L-BFGS-B").x
    lh = np.exp(p[0] + p[1] + p[2:2 + n][hi] - p[2 + n:][ai])
    la = np.exp(p[0] + p[2:2 + n][ai] - p[2 + n:][hi])
    best, rho = -np.inf, 0.0
    for r in np.arange(-0.25, 0.101, 0.01):
        t = np.ones_like(lh)
        t[(hg == 0) & (ag == 0)] = 1 - lh[(hg == 0) & (ag == 0)] * la[(hg == 0) & (ag == 0)] * r
        t[(hg == 0) & (ag == 1)] = 1 + lh[(hg == 0) & (ag == 1)] * r
        t[(hg == 1) & (ag == 0)] = 1 + la[(hg == 1) & (ag == 0)] * r
        t[(hg == 1) & (ag == 1)] = 1 - r
        ll = np.sum(w * np.log(np.clip(t, 1e-9, None)))
        if ll > best:
            best, rho = ll, r
    return p, rho


def score_matrix(lh, la, rho):
    m = np.outer(poisson.pmf(np.arange(MAXG + 1), lh), poisson.pmf(np.arange(MAXG + 1), la))
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    return m / m.sum()


def ah_ev(m, line, odds):
    """Valor esperado de 1 unidade no handicap asiático da equipa da casa com linha `line` (quartos divididos)."""
    diff = np.subtract.outer(np.arange(MAXG + 1), np.arange(MAXG + 1))
    quarter = (line * 4) % 2 != 0
    ev = 0.0
    for h in ((line - 0.25, line + 0.25) if quarter else (line, line)):
        d = diff + h
        ev += 0.5 * np.sum(m * np.where(d > 0, odds - 1, np.where(d == 0, 0, -1)))
    return ev


def ah_ret(margin, line, odds):
    quarter = (line * 4) % 2 != 0
    r = 0.0
    for h in ((line - 0.25, line + 0.25) if quarter else (line, line)):
        d = margin + h
        r += 0.5 * (odds - 1 if d > 0 else (0 if d == 0 else -1))
    return r


def predict_league(g):
    """Previsões walk-forward para uma liga: uma linha por jogo com probabilidades do modelo."""
    out = []
    g = g.assign(cut=g.dt.map(cutoff))
    seasons = sorted(g.S.unique())
    x0 = {}
    for cut, batch in g[g.S != seasons[0]].groupby("cut"):
        train = g[(g.dt < cut) & (g.dt >= cut - pd.Timedelta(days=HISTORY_DAYS))]
        teams = sorted(set(train.HomeTeam) | set(train.AwayTeam) | set(batch.HomeTeam) | set(batch.AwayTeam))
        idx = {t: i for i, t in enumerate(teams)}
        season = batch.S.iloc[0]
        prev = seasons[seasons.index(season) - 1]
        prev_teams = set(g[g.S == prev].HomeTeam)
        prior = np.array([0.0 if t in prev_teams else PROMOTED_PRIOR for t in teams])
        tr = train.assign(hi=train.HomeTeam.map(idx), ai=train.AwayTeam.map(idx),
                          w=np.exp(-XI * (cut - train.dt).dt.days.values))
        start = np.concatenate([[0.3, 0.25], [x0.get(("a", t), prior[i]) for i, t in enumerate(teams)],
                                [x0.get(("d", t), prior[i]) for i, t in enumerate(teams)]])
        p, rho = fit(tr, teams, prior, start)
        n = len(teams)
        x0 = {**{("a", t): p[2 + i] for i, t in enumerate(teams)}, **{("d", t): p[2 + n + i] for i, t in enumerate(teams)}}
        for _, r in batch.iterrows():
            h, a = idx[r.HomeTeam], idx[r.AwayTeam]
            lh = np.exp(p[0] + p[1] + p[2 + h] - p[2 + n + a])
            la = np.exp(p[0] + p[2 + a] - p[2 + n + h])
            m = score_matrix(lh, la, rho)
            tg = np.add.outer(np.arange(MAXG + 1), np.arange(MAXG + 1))
            out.append({"i": r.name, "mH": np.tril(m, -1).sum(), "mD": np.trace(m), "mA": np.triu(m, 1).sum(),
                        "mO": m[tg > 2.5].sum(), "m": m})
    return out


def fair(df, cols):
    p = 1 / df[cols].astype(float)
    return p.div(p.sum(axis=1), axis=0).values


def main():
    D = load()
    preds = []
    for l, g in D.groupby("L"):
        preds += predict_league(g)
        print(f"{LEAGUES[l]}: {len(preds)} previsões acumuladas", flush=True)
    P = pd.DataFrame(preds).set_index("i")
    E = D.loc[P.index].join(P.drop(columns="m"))
    E["oH"], E["oD"], E["oA"] = (E.FTR == "H") * 1, (E.FTR == "D") * 1, (E.FTR == "A") * 1
    E["over"] = ((E.FTHG + E.FTAG) > 2.5) * 1

    # probabilidades de referência sem margem: abertura e fecho (Pinnacle quando existe, senão média do mercado)
    for tag, pin, avg in (("open", ["PSH", "PSD", "PSA"], ["AvgH", "AvgD", "AvgA"]),
                          ("close", ["PSCH", "PSCD", "PSCA"], ["AvgCH", "AvgCD", "AvgCA"])):
        f = np.where(E[pin].notna().all(axis=1).values[:, None], fair(E, pin), fair(E, avg))
        E[[f"{tag}H", f"{tag}D", f"{tag}A"]] = f
    for tag, pin, avg in (("open", ["P>2.5", "P<2.5"], ["Avg>2.5", "Avg<2.5"]),
                          ("close", ["PC>2.5", "PC<2.5"], ["AvgC>2.5", "AvgC<2.5"])):
        ok = (E[pin] > 1).all(axis=1).values
        E[f"{tag}O"] = np.where(ok, fair(E, pin)[:, 0], fair(E, avg)[:, 0])

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    E.drop(columns=[c for c in E.columns if c not in KEEP]).to_csv(os.path.join(HERE, "results", "predictions.csv"), index=False)
    bets = make_bets(E, P)
    bets.to_csv(os.path.join(HERE, "results", "bets.csv"), index=False)
    report(E, bets)


KEEP = ["L", "S", "dt", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "mH", "mD", "mA", "mO",
        "openH", "openD", "openA", "closeH", "closeD", "closeA", "openO", "closeO"]


def make_bets(E, P):
    """Uma aposta candidata por mercado e jogo: o lado com maior valor esperado contra a odd de abertura (média do mercado)."""
    rows = []
    for i, r in E.iterrows():
        base = {"L": r.L, "S": r.S, "dt": r["dt"], "jogo": f"{r.HomeTeam} - {r.AwayTeam}"}
        # 1X2: preço de entrada = média de abertura (substituto de Betclic/22bet); 1xBet só existe em 2024/25
        cands = []
        for k, oc, cc, o1x in (("H", "AvgH", "AvgCH", "1XBH"), ("D", "AvgD", "AvgCD", "1XBD"), ("A", "AvgA", "AvgCA", "1XBA")):
            if pd.notna(r[oc]):
                cands.append(("1X2", k, r[f"m{k}"], r[oc], r[f"close{k}"], r[f"o{k}"], r.get(o1x)))
        for k, oc, sgn in (("Over", "Avg>2.5", 1), ("Under", "Avg<2.5", 0)):
            if pd.notna(r[oc]) and r[oc] > 1:
                pm = r.mO if sgn else 1 - r.mO
                pc = r.closeO if sgn else 1 - r.closeO
                cands.append(("O/U 2.5", k, pm, r[oc], pc, r.over if sgn else 1 - r.over, np.nan))
        for mkt in ("1X2", "O/U 2.5"):
            c = [x for x in cands if x[0] == mkt]
            if not c:
                continue
            best = max(c, key=lambda x: x[2] * x[3] - 1)
            _, sel, pm, odd, pc, won, o1x = best
            rows.append({**base, "mercado": mkt, "selecao": sel, "p_modelo": pm, "odd": odd, "ev": pm * odd - 1,
                         "clv": odd * pc - 1, "ret": odd * won - 1, "ret_1xbet": o1x * won - 1 if pd.notna(o1x) else np.nan})
        # handicap asiático: linha e odds médias de abertura; CLV só quando a linha não mudou até ao fecho
        if pd.notna(r.get("AHh")) and pd.notna(r.get("AvgAHH")):
            m = P.at[i, "m"]
            gd = r.FTHG - r.FTAG
            opts = [("casa", ah_ev(m, r.AHh, r.AvgAHH), r.AvgAHH, ah_ret(gd, r.AHh, r.AvgAHH), "AvgCAHH"),
                    ("fora", ah_ev(m.T, -r.AHh, r.AvgAHA), r.AvgAHA, ah_ret(-gd, -r.AHh, r.AvgAHA), "AvgCAHA")]
            sel, ev, odd, ret, ccol = max(opts, key=lambda x: x[1])
            clv = np.nan
            if r.get("AHCh") == r.AHh and pd.notna(r.get("AvgCAHH")):
                q = 1 / r.AvgCAHH + 1 / r.AvgCAHA
                clv = odd / (r[ccol] * q) - 1
            rows.append({**base, "mercado": "Handicap asiático", "selecao": sel, "p_modelo": np.nan, "odd": odd,
                         "ev": ev, "clv": clv, "ret": ret, "ret_1xbet": np.nan})
    return pd.DataFrame(rows)


def rps(p, o):
    c = np.cumsum(p, axis=1) - np.cumsum(o, axis=1)
    return np.mean(np.sum(c[:, :2] ** 2, axis=1) / 2)


def report(E, bets):
    o = E[["oH", "oD", "oA"]].values
    print("\n=== Calibração 1X2 (RPS, menor = melhor) ===")
    rows = []
    for l, g in E.groupby("L"):
        g = g.dropna(subset=["openH", "openD", "openA", "closeH", "closeD", "closeA"])
        o = g[["oH", "oD", "oA"]].values
        m, op, cl = g[["mH", "mD", "mA"]].values, g[["openH", "openD", "openA"]].values, g[["closeH", "closeD", "closeA"]].values
        rows.append([LEAGUES[l], len(g), rps(m, o), rps(op, o), rps(cl, o), rps((m + op) / 2, o)])
    print(pd.DataFrame(rows, columns=["Liga", "jogos", "modelo", "abertura", "fecho", "50% modelo + 50% abertura"]).round(4).to_string(index=False))

    print("\n=== Apostas com valor contra a abertura (preço = média do mercado à abertura) ===")
    out = []
    for mkt, g in bets.groupby("mercado"):
        for thr in (0.0, 0.03, 0.05, 0.10):
            b = g[g.ev >= thr]
            if len(b) < 30:
                continue
            c = b.clv.dropna()
            out.append([mkt, f"≥{thr:.0%}", len(b), 100 * (b.ret > 0).mean(), b.odd.mean(), 100 * b.ret.mean(),
                        196 * b.ret.std() / np.sqrt(len(b)), 100 * c.mean(), 196 * c.std() / np.sqrt(len(c)), 100 * (c > 0).mean()])
    print(pd.DataFrame(out, columns=["mercado", "valor", "apostas", "acerto%", "odd média", "ROI%", "±IC", "CLV%", "±IC CLV", "% CLV>0"]).round(1).to_string(index=False))

    print("\n=== Por liga (valor ≥ 3%) ===")
    b = bets[bets.ev >= 0.03]
    t = b.groupby(["mercado", "L"]).apply(lambda g: pd.Series({
        "apostas": len(g), "ROI%": 100 * g.ret.mean(), "±IC": 196 * g.ret.std() / np.sqrt(len(g)),
        "CLV%": 100 * g.clv.mean(), "±IC CLV": 196 * g.clv.std() / np.sqrt(g.clv.notna().sum())}), include_groups=False)
    print(t.rename(index=LEAGUES).round(1).to_string())
    x = bets[(bets.ev >= 0.03) & bets.ret_1xbet.notna()]
    if len(x):
        print(f"\n1X2 em 2024/25 à odd de abertura da 1xBet (substituto 22bet): {len(x)} apostas, ROI {100 * x.ret_1xbet.mean():.1f}%")
    soft_vs_sharp(E)


def fair_power(df, cols):
    """Margem removida pelo método de potência (p_i = q_i^k, soma 1): corrige o exagero nos outsiders."""
    q = 1 / df[cols].values.astype(float)
    lo, hi = np.ones(len(q)), np.full(len(q), 3.0)
    for _ in range(40):
        k = (lo + hi) / 2
        s = (q ** k[:, None]).sum(axis=1)
        lo, hi = np.where(s > 1, k, lo), np.where(s > 1, hi, k)
    return q ** ((lo + hi) / 2)[:, None]


def soft_vs_sharp(E, max_odd=3.5):
    """Estratégia ancorada no mercado: apostar quando a casa soft paga acima do preço justo da Pinnacle à abertura."""
    print(f"\n=== Casa soft acima do preço justo Pinnacle (abertura, 1X2, odds até {max_odd}) ===")
    pin = ["PSH", "PSD", "PSA"]
    E = E[E[pin].notna().all(axis=1) & E[["PSCH", "PSCD", "PSCA"]].notna().all(axis=1)]
    fo = fair_power(E, pin)
    fc = fair_power(E, ["PSCH", "PSCD", "PSCA"])
    won = E[["oH", "oD", "oA"]].values
    out = []
    for name, cols in (("Bet365", ["B365H", "B365D", "B365A"]), ("1xBet (22bet)", ["1XBH", "1XBD", "1XBA"]),
                       ("Bwin", ["BWH", "BWD", "BWA"]), ("William Hill", ["WHH", "WHD", "WHA"]),
                       ("Melhor odd", ["MaxH", "MaxD", "MaxA"])):
        if not set(cols) <= set(E.columns):
            continue
        odds = E[cols].values.astype(float)
        for thr in (0.0, 0.02, 0.05):
            edge = odds * fo - 1
            sel = (np.nan_to_num(edge, nan=-1) >= thr) & (np.nan_to_num(odds, nan=99) <= max_odd)
            if sel.sum() < 30:
                continue
            ret = (odds * won - 1)[sel]
            clv = (odds * fc - 1)[sel]
            out.append([name, f"≥{thr:.0%}", int(sel.sum()), 100 * (sel.sum() / np.isfinite(odds).all(axis=1).sum()),
                        np.mean(odds[sel]), 100 * ret.mean(), 196 * ret.std() / np.sqrt(len(ret)),
                        100 * clv.mean(), 196 * clv.std() / np.sqrt(len(clv))])
    print(pd.DataFrame(out, columns=["casa", "vantagem", "apostas", "apostas/jogo %", "odd média", "ROI%", "±IC",
                                     "CLV%", "±IC CLV"]).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
