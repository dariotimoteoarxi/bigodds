"""Variáveis dos mercados de especialista, partilhadas pelo backtest e pela app (só Python de base).

Cada jogo é descrito pelo histórico recente das duas equipas e da liga, e pelo que o mercado espera
(probabilidades sem margem do 1X2 e do Over/Under 2,5). Tudo relativo à média da liga para servir
qualquer campeonato.
"""
import math

LAST_TEAM, LAST_VENUE, LAST_LEAGUE, RECENT_LEAGUE = 20, 10, 380, 100
DECAY = 0.93


def num(row, k):
    v = row.get(k)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v  # 0 é um valor válido (0 golos, 0 cartões)


def entry(row, team):
    """O jogo do ponto de vista de uma equipa, ou None se faltarem estatísticas."""
    home = row["HomeTeam"] == team
    a, b = ("H", "A") if home else ("A", "H")
    v = {"home": home, "htf": num(row, "HT" + a + "G"), "hta": num(row, "HT" + b + "G"), "gf": num(row, "FT" + a + "G"),
         "ga": num(row, "FT" + b + "G"), "cf": num(row, a + "C"), "ca": num(row, b + "C"), "yf": num(row, a + "Y"),
         "ya": num(row, b + "Y"), "ff": num(row, a + "F"), "fa": num(row, b + "F")}
    return None if None in v.values() else v


def league_entry(row):
    v = {"hth": num(row, "HTHG"), "hta": num(row, "HTAG"), "fth": num(row, "FTHG"), "fta": num(row, "FTAG"),
         "c": None, "y": None, "f": None}
    if None not in (num(row, "HC"), num(row, "AC"), num(row, "HY"), num(row, "AY"), num(row, "HF"), num(row, "AF")):
        v.update(c=num(row, "HC") + num(row, "AC"), y=num(row, "HY") + num(row, "AY"), f=num(row, "HF") + num(row, "AF"))
    return None if None in v.values() else v


def wavg(xs):
    if not xs:
        return None
    w = [DECAY ** i for i in range(len(xs))][::-1]
    return sum(a * b for a, b in zip(xs, w)) / sum(w)


def poisson_over(lam, line):
    k = int(math.floor(line))
    return 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k + 1))


def implied_total(p_over25):
    lo, hi = 0.2, 6.0
    for _ in range(50):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if poisson_over(m, 2.5) < p_over25 else (lo, m)
    return (lo + hi) / 2


def features(H, A, L, mk):
    """H, A: entradas das equipas (mais antiga primeiro); L: entradas da liga; mk: {'pH','pA','po'} (pode ter None).

    Devolve None se não houver histórico suficiente.
    """
    if len(H) < 6 or len(A) < 6 or len(L) < 60:
        return None
    H, A, L = H[-LAST_TEAM:], A[-LAST_TEAM:], L[-LAST_LEAGUE:]
    Lr = L[-RECENT_LEAGUE:]
    lg = lambda k, rows=L: sum(x[k] for x in rows) / len(rows)
    ht_h, ht_a, ft = lg("hth"), lg("hta"), lg("fth") + lg("fta")
    c_avg, y_avg, y_rec, f_avg = lg("c"), lg("y"), lg("y", Lr), lg("f")
    t = lambda T, k: wavg([x[k] for x in T])
    hv = [x for x in H if x["home"]][-LAST_VENUE:] or H
    av = [x for x in A if not x["home"]][-LAST_VENUE:] or A
    ht_avg = (ht_h + ht_a) / 2
    # golos na 1.ª parte: forças de ataque e defesa ao intervalo (geral e no local do jogo)
    ht_model = ht_h * t(H, "htf") / ht_avg * t(A, "hta") / ht_avg + ht_a * t(A, "htf") / ht_avg * t(H, "hta") / ht_avg
    ht_venue = ht_h * t(hv, "htf") / ht_avg * t(av, "hta") / ht_avg + ht_a * t(av, "htf") / ht_avg * t(hv, "hta") / ht_avg
    po, pH, pA = mk.get("po"), mk.get("pH"), mk.get("pA")
    lam_tot = implied_total(po) if po else ft
    strength = abs(pH - pA) if pH is not None and pA is not None else 0.3
    pair = lambda T1, T2, k1, k2: (t(T1, k1) + t(T2, k2)) / 2
    c_base = pair(H, A, "cf", "ca") + pair(A, H, "cf", "ca")
    c_venue = pair(hv, av, "cf", "ca") + pair(av, hv, "cf", "ca")
    y_base = pair(H, A, "yf", "ya") + pair(A, H, "yf", "ya")
    y_venue = pair(hv, av, "yf", "ya") + pair(av, hv, "yf", "ya")
    fouls = pair(H, A, "ff", "fa") + pair(A, H, "ff", "fa")
    lg_safe = lambda x: math.log(max(x, 1e-3))
    c2, y2 = c_avg / 2, y_avg / 2  # média por equipa na liga
    side = lambda T1, T2, kf, ka, avg: lg_safe(t(T1, kf) * t(T2, ka) / avg / avg)  # ataque de uma x o que a outra concede
    return {
        # golos na 1.ª parte
        "ht_model": lg_safe(ht_model), "ht_venue": lg_safe(ht_venue), "ht_mkt": lg_safe(lam_tot * (ht_h + ht_a) / ft),
        # cantos
        "c_base": lg_safe(c_base / c_avg), "c_venue": lg_safe(c_venue / c_avg), "c_lg": lg_safe(c_avg),
        "c_strength": strength, "c_goals": lam_tot / ft,
        # amarelos (com faltas e tendência recente da liga)
        "y_base": lg_safe(y_base / y_avg), "y_venue": lg_safe(y_venue / y_avg), "y_lg": lg_safe(y_avg),
        "y_trend": lg_safe(y_rec / y_avg), "y_fouls": lg_safe(fouls / f_avg), "y_balance": 1 - strength, "y_goals": lam_tot / ft,
        # por equipa (cantos e amarelos de cada lado)
        "hc_base": side(H, A, "cf", "ca", c2), "ac_base": side(A, H, "cf", "ca", c2),
        "hc_venue": side(hv, av, "cf", "ca", c2), "ac_venue": side(av, hv, "cf", "ca", c2),
        "hy_base": side(H, A, "yf", "ya", y2), "ay_base": side(A, H, "yf", "ya", y2),
        "hy_venue": side(hv, av, "yf", "ya", y2), "ay_venue": side(av, hv, "yf", "ya", y2),
        "lc2": lg_safe(c2), "ly2": lg_safe(y2),
        # mercado 1X2 (para "equipa marca")
        "mk_ph": pH if pH is not None else 0.45, "mk_pa": pA if pA is not None else 0.30,
        # contexto para o texto humano
        "_ht_model": ht_model, "_lam_tot": lam_tot, "_c_base": c_base, "_y_base": y_base, "_fouls": fouls,
    }


MODEL_COLS = {
    "ht": ["ht_model", "ht_venue", "ht_mkt"],
    "c": ["c_base", "c_venue", "c_lg", "c_strength", "c_goals"],
    "y": ["y_base", "y_venue", "y_lg", "y_trend", "y_fouls", "y_balance", "y_goals"],
    "ft": ["ht_mkt", "ht_model", "ht_venue"],
    "g2": ["ht_mkt", "ht_model", "ht_venue"],
    "hg": ["ht_mkt", "ht_model", "ht_venue", "mk_ph", "mk_pa"],
    "ag": ["ht_mkt", "ht_model", "ht_venue", "mk_ph", "mk_pa"],
    "hc": ["hc_base", "hc_venue", "lc2", "mk_ph", "mk_pa", "c_goals"],
    "ac": ["ac_base", "ac_venue", "lc2", "mk_ph", "mk_pa", "c_goals"],
    "hy": ["hy_base", "hy_venue", "ly2", "y_trend", "y_fouls", "mk_ph", "mk_pa", "y_balance"],
}


def predict_mu(model, feats):
    """Média esperada (golos ao intervalo, cantos ou amarelos) de uma regressão de Poisson exportada."""
    z = model["intercept"] + sum(c * feats[k] for k, c in zip(model["cols"], model["coef"]))
    return math.exp(z)


def negbin_over(mu, line, disp):
    """P(total > linha) com binomial negativa (variância = mu * disp)."""
    if disp <= 1.0001:
        return poisson_over(mu, line)
    p = 1 / disp
    r = mu * p / (1 - p)
    cdf, pmf = 0.0, p ** r
    for i in range(int(math.floor(line)) + 1):
        if i:
            pmf *= (i - 1 + r) / i * (1 - p)
        cdf += pmf
    return 1 - cdf
