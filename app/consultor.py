"""Camada de consultoria: lê a época de cada equipa e explica o jogo (forma, xG, sorte, modelo vs mercado).

Só Python de base. O modelo é de forças (ataque/defesa) com 70% xG + 30% golos da época atual,
encolhido para a média da liga nos primeiros jogos.
"""
import math, re
from datetime import datetime

SHRINK = 4          # jogos fictícios de média da liga somados a cada equipa
OPINION_DIFF = 0.08  # o modelo tem de discordar do mercado em >= 8 pontos percentuais
OPINION_EV = 0.05    # e ver pelo menos +5% de valor esperado na melhor odd
OPINION_MAX_ODD = 4.0
OPINION_STAKE = 0.005  # 0,5% da banca: leitura não validada no backtest


def ah_ret(margin, line, odd):
    """Lucro por unidade no handicap asiático; linhas de quarto dividem a aposta em duas."""
    halves = (line - 0.25, line + 0.25) if (line * 4) % 2 else (line, line)
    return sum(0.5 * (odd - 1 if margin + h > 0 else 0 if margin + h == 0 else -1) for h in halves)


def f(row, k):
    try:
        return float(row.get(k) or "")
    except ValueError:
        return None


def team_games(rows, team):
    out = []
    for r in rows:
        if f(r, "FTHG") is None or team not in (r["HomeTeam"], r["AwayTeam"]):
            continue
        home = r["HomeTeam"] == team
        out.append({"date": datetime.strptime(r["Date"], "%d/%m/%Y"), "home": home,
                    "opp": r["AwayTeam"] if home else r["HomeTeam"],
                    "gf": f(r, "FTHG" if home else "FTAG"), "ga": f(r, "FTAG" if home else "FTHG"),
                    "xgf": f(r, "HxG" if home else "AxG"), "xga": f(r, "AxG" if home else "HxG")})
    return sorted(out, key=lambda g: g["date"])


def table(rows):
    pts = {}
    for r in rows:
        if f(r, "FTHG") is None:
            continue
        h, a, hg, ag = r["HomeTeam"], r["AwayTeam"], f(r, "FTHG"), f(r, "FTAG")
        for t, gf, ga in ((h, hg, ag), (a, ag, hg)):
            p = pts.setdefault(t, [0, 0, 0])
            p[0] += 3 if gf > ga else 1 if gf == ga else 0
            p[1] += gf - ga
            p[2] += 1
    order = sorted(pts, key=lambda t: (-pts[t][0], -pts[t][1]))
    return {t: {"pos": i + 1, "pts": pts[t][0], "dg": int(pts[t][1]), "j": pts[t][2]} for i, t in enumerate(order)}


def metric(g, for_):
    """70% xG + 30% golos (só golos se não houver xG)."""
    goals, xg = (g["gf"], g["xgf"]) if for_ else (g["ga"], g["xga"])
    return goals if xg is None else 0.7 * xg + 0.3 * goals


def ratings(rows):
    played = [r for r in rows if f(r, "FTHG") is not None]
    if not played:
        return None
    hx = [0.7 * (f(r, "HxG") if f(r, "HxG") is not None else f(r, "FTHG")) + 0.3 * f(r, "FTHG") for r in played]
    ax = [0.7 * (f(r, "AxG") if f(r, "AxG") is not None else f(r, "FTAG")) + 0.3 * f(r, "FTAG") for r in played]
    avg = (sum(hx) + sum(ax)) / (2 * len(played))
    hfa = sum(hx) / max(sum(ax), 1e-9)
    teams = {r["HomeTeam"] for r in played} | {r["AwayTeam"] for r in played}
    att, de = {}, {}
    for t in teams:
        gs = team_games(played, t)
        n = len(gs)
        att[t] = (sum(metric(g, True) for g in gs) + SHRINK * avg) / (n + SHRINK) / avg
        de[t] = (sum(metric(g, False) for g in gs) + SHRINK * avg) / (n + SHRINK) / avg
    return {"avg": avg, "hfa": hfa, "att": att, "def": de}


def matrix(lh, la, maxg=10):
    ph = [math.exp(-lh) * lh ** i / math.factorial(i) for i in range(maxg + 1)]
    pa = [math.exp(-la) * la ** i / math.factorial(i) for i in range(maxg + 1)]
    m = [[x * y for y in pa] for x in ph]
    s = sum(map(sum, m))
    return [[v / s for v in row] for row in m]


def model_probs(m, line):
    cells = [(i, j, m[i][j]) for i in range(len(m)) for j in range(len(m))]
    p = {"1x2:1": sum(v for i, j, v in cells if i > j), "1x2:X": sum(v for i, j, v in cells if i == j),
         "1x2:2": sum(v for i, j, v in cells if i < j), "ou:+2,5": sum(v for i, j, v in cells if i + j > 2),
         "btts": sum(v for i, j, v in cells if i and j)}
    p["ou:-2,5"] = 1 - p["ou:+2,5"]
    if line is not None:
        # "probabilidade" equivalente no AH: retorno esperado a odd 2,0 convertido em hipótese de ganhar
        for sid, sign in (("ah:casa", 1), ("ah:fora", -1)):
            ev = sum(v * ah_ret(sign * (i - j), sign * line, 2.0) for i, j, v in cells)
            p[sid] = (ev + 1) / 2
    top = sorted(cells, key=lambda c: -c[2])[:3]
    return p, [f"{i}-{j}" for i, j, _ in top], [round(v, 3) for *_, v in top]


def ah_model_ev(m, sel, line, odd):
    sign = 1 if sel == "ah:casa" else -1
    return sum(m[i][j] * ah_ret(sign * (i - j), sign * line, odd) for i in range(len(m)) for j in range(len(m)))


def form(gs):
    return [{"r": "V" if g["gf"] > g["ga"] else "E" if g["gf"] == g["ga"] else "D",
             "s": f"{dec(g['gf'], '.0')}-{dec(g['ga'], '.0')}", "loc": "C" if g["home"] else "F", "opp": g["opp"]} for g in gs[-5:]]


def summary(gs, home_only=None):
    gs = [g for g in gs if home_only is None or g["home"] == home_only]
    n = len(gs)
    if not n:
        return None
    xs = [g for g in gs if g["xgf"] is not None]
    return {"j": n, "gm": round(sum(g["gf"] for g in gs) / n, 2), "gs": round(sum(g["ga"] for g in gs) / n, 2),
            "xgf": round(sum(g["xgf"] for g in xs) / len(xs), 2) if xs else None,
            "xga": round(sum(g["xga"] for g in xs) / len(xs), 2) if xs else None,
            "sorte_m": round(sum(g["gf"] - g["xgf"] for g in xs), 1) if xs else None,
            "sorte_s": round(sum(g["ga"] - g["xga"] for g in xs), 1) if xs else None}


def dec(x, spec):
    return format(x, spec + 'f').replace('.', ',')


def pct(x):
    return f"{dec(x * 100, '.0')}%"


def analysis(game, rows, prev_rows, bank):
    """Acrescenta ao jogo a leitura do consultor. rows = época atual da liga, prev_rows = época anterior."""
    h, a = game["home"], game["away"]
    rt, tb = ratings(rows), table(rows)
    if not rt or h not in rt["att"] or a not in rt["att"]:
        return None
    lh = rt["avg"] * rt["att"][h] * rt["def"][a] * math.sqrt(rt["hfa"])
    la = rt["avg"] * rt["att"][a] * rt["def"][h] / math.sqrt(rt["hfa"])
    ah = next((m for m in game["markets"] if m["key"] == "ah"), None)
    line = ah["line"] if ah else None
    m = matrix(lh, la)
    probs, top, top_p = model_probs(m, line)
    gh, ga_ = team_games(rows, h), team_games(rows, a)
    teams = {}
    for t, gs, venue in ((h, gh, True), (a, ga_, False)):
        teams[t] = {"tabela": tb.get(t), "forma": form(gs), "total": summary(gs), "local": summary(gs, venue),
                    "ultimo_jogo": gs[-1]["date"].strftime("%d/%m") if gs else None}
    h2h = [f"{r['HomeTeam']} {r['FTHG']}-{r['FTAG']} {r['AwayTeam']}" for r in prev_rows + rows
           if f(r, "FTHG") is not None and {r["HomeTeam"], r["AwayTeam"]} == {h, a}][-4:]

    # leitura escrita a partir dos números
    notes = []
    for t in (h, a):
        s, tt = teams[t]["total"], teams[t]["tabela"]
        if not s:
            continue
        if s["sorte_m"] is not None and s["sorte_m"] <= -2.5:
            notes.append(f"{t} marcou {dec(-s['sorte_m'], '.1')} golos abaixo do xG: está a falhar ocasiões, tende a melhorar.")
        if s["sorte_m"] is not None and s["sorte_m"] >= 2.5:
            notes.append(f"{t} marcou {dec(s['sorte_m'], '.1')} golos acima do xG: rende mais do que cria, tende a baixar.")
        if s["sorte_s"] is not None and s["sorte_s"] <= -2.5:
            notes.append(f"{t} sofreu {dec(-s['sorte_s'], '.1')} golos menos do que o xG concedido: a defesa tem tido sorte"
                         f"{' e a posição na tabela (' + str(tt['pos']) + '.º) exagera o nível' if tt and tt['pos'] <= 6 else ''}.")
        if s["sorte_s"] is not None and s["sorte_s"] >= 2.5:
            notes.append(f"{t} sofreu {dec(s['sorte_s'], '.1')} golos mais do que o xG concedido: azar defensivo, tende a regressar.")
    lh_s, la_s = teams[h]["local"], teams[a]["local"]
    if lh_s and la_s:
        notes.append(f"{h} em casa: {dec(lh_s['gm'], '.1')} marcados e {dec(lh_s['gs'], '.1')} sofridos por jogo ({lh_s['j']}j). "
                     f"{a} fora: {dec(la_s['gm'], '.1')} e {dec(la_s['gs'], '.1')} ({la_s['j']}j).")
    mkt = {s["sel"]: s for mk in game["markets"] for s in mk["selections"]}
    diffs = []
    for sid, name in (("1x2:1", f"«{h} ganha»"), ("1x2:X", "«empate»"), ("1x2:2", f"«{a} ganha»"), ("ou:+2,5", "«mais de 2,5 golos»")):
        if sid in mkt:
            diffs.append((probs[sid] - mkt[sid]["p"], sid, name))
    big = max(diffs, key=lambda d: abs(d[0]), default=None)
    if big and abs(big[0]) >= OPINION_DIFF:
        notes.append(f"Os números da época dão {pct(probs[big[1]])} a {big[2]}; o mercado dá {pct(mkt[big[1]]['p'])}. "
                     + ("Os números da época não sustentam a confiança do mercado: o preço reflete nome e plantel."
                        if big[0] < 0 else "O mercado ainda não acompanhou o que a época está a mostrar."))
    else:
        notes.append("Modelo e mercado estão alinhados: os números da época não mostram nada que o preço não tenha já.")
    notes.append(f"Golos esperados {dec(lh, '.1')}–{dec(la, '.1')}; resultado mais provável {top[0]}.")
    if min(teams[h]["total"]["j"] if teams[h]["total"] else 0, teams[a]["total"]["j"] if teams[a]["total"] else 0) < 6:
        notes.append("Amostra curta (menos de 6 jogos): confiança baixa nos números.")

    # aposta de opinião: o modelo discorda do mercado e a melhor odd paga essa discordância
    cands = []
    for sid, s in mkt.items():
        if not s["best_odd"] or s["best_odd"] > OPINION_MAX_ODD or sid not in probs:
            continue
        ev = ah_model_ev(m, sid, line, s["best_odd"]) if sid.startswith("ah:") else probs[sid] * s["best_odd"] - 1
        if probs[sid] - s["p"] >= OPINION_DIFF and ev >= OPINION_EV:
            cands.append((ev, s))
    opinion = None
    if cands:
        ev, s = max(cands, key=lambda c: c[0])
        opinion = {"sel": s["sel"], "label": s["label"], "market": s["market"], "book": s["best_book"], "odd": s["best_odd"],
                   "p_model": round(probs[s["sel"]], 3), "p_market": s["p"], "ev": round(ev, 3),
                   "min_odd": round(1.02 / probs[s["sel"]], 2) if not s["sel"].startswith("ah:") else None,
                   "stake": round(OPINION_STAKE * bank, 2)}
    return {"teams": teams, "h2h": h2h, "model": {"lh": round(lh, 2), "la": round(la, 2),
            "p": {k: round(v, 3) for k, v in probs.items()}, "top": top, "top_p": top_p},
            "notes": notes, "opinion": opinion}


# --- seleção do dia -------------------------------------------------------------
W_MARKET = 0.7      # peso do mercado na probabilidade estimada (o mercado é o melhor preditor; o modelo acrescenta a época)
MIN_P, MIN_ODD, MAX_ODD_PICK = 0.50, 1.30, 3.0
CONF_RANK = {"Alta": 0, "Média": 1, "Baixa": 2}


def rate(s, p_mod, small):
    """Acerto estimado e confiança de uma seleção: mercado sem margem + modelo da época."""
    p = W_MARKET * s["p"] + (1 - W_MARKET) * p_mod if p_mod is not None else s["p"]
    d = abs(p_mod - s["p"]) if p_mod is not None else 0.10
    odd = s["best_odd"]
    ev = p * odd - 1 if odd else None
    if p >= 0.62 and d <= 0.05 and (ev is None or ev >= -0.03) and not small:
        conf = "Alta"
    elif p >= 0.55 and d <= 0.10 and (ev is None or ev >= -0.05):
        conf = "Média"
    else:
        conf = "Baixa"
    score = p - 0.6 * d + 0.5 * min(ev if ev is not None else -0.05, 0.05)
    return {"p_est": round(p, 3), "conf": conf, "ev": round(ev, 3) if ev is not None else None,
            "d": round(d, 3), "score": round(score, 4), "min_odd_est": round(1.02 / p, 2)}


def rate_game(game):
    """Acrescenta acerto estimado e confiança a todas as seleções de todos os mercados do jogo."""
    an = game.get("analise")
    model = an["model"]["p"] if an else {}
    small = bool(an) and min((t["total"] or {}).get("j", 0) for t in an["teams"].values()) < 6
    for mk in game["markets"]:
        for s in mk["selections"]:
            s.update(rate(s, model.get(s["sel"]), small))
    return small


def best_bet(game):
    """O melhor mercado deste jogo para entrar: probabilidade alta, modelo e mercado de acordo, odd não abaixo do justo."""
    an = game.get("analise")
    model = an["model"]["p"] if an else {}
    small = rate_game(game)
    best = None
    for mk in game["markets"]:
        for s in mk["selections"]:
            odd = s["best_odd"]
            if not odd or not MIN_ODD <= odd <= MAX_ODD_PICK or s["p_est"] < MIN_P:
                continue
            p, conf, ev, d, score = s["p_est"], s["conf"], s["ev"], s["d"], s["score"]
            p_mod = model.get(s["sel"])
            if not best or (CONF_RANK[conf], -score) < (CONF_RANK[best["confianca"]], -best["score"]):
                why = [f"Mercado {pct(s['p'])}" + (f", modelo da época {pct(p_mod)}" if p_mod is not None else "") + f": estimativa {pct(p)}."]
                why.append(f"{s['best_book']} paga {dec(odd, '.2')}; o justo é {dec(1 / p, '.2')}. " +
                           (f"Valor esperado {dec(ev * 100, '+.1')}%." if ev >= 0 else
                            f"Abaixo do justo ({dec(ev * 100, '+.1')}%): procura pelo menos {dec(1.02 / p, '.2')} na Betclic/22bet."))
                if d > 0.05 and p_mod is not None:
                    why.append("Modelo e mercado divergem: confiança reduzida.")
                if small:
                    why.append("Poucos jogos na época: confiança reduzida.")
                best = {"game_id": game["id"], "sel": s["sel"], "label": s["label"], "market": s["market"], "book": s["best_book"],
                        "odd": odd, "p": p, "fair_odd": round(1 / p, 2), "min_odd": round(1.02 / p, 2),
                        "ev": ev, "confianca": conf, "score": score, "porque": why, "line": mk.get("line")}
    return best


def selecao(games, today, n=5):
    """As até n apostas com mais confiança do dia (hoje; se já não houver jogos, o próximo dia com jogos)."""
    days = sorted({g["kickoff"][:10] for g in games if g["kickoff"][:10] >= today})
    if not days:
        return {"dia": None, "apostas": []}
    day = days[0]
    for g in games:
        rate_game(g)  # todos os jogos ficam com acerto e confiança, mesmo fora da seleção
    picks = [p for g in games if g["kickoff"][:10] == day for p in [best_bet(g)] if p and p["confianca"] != "Baixa"]
    picks.sort(key=lambda p: (CONF_RANK[p["confianca"]], -p["score"]))
    by_id = {g["id"]: g for g in games}
    for p in picks[:n]:
        p.update(narrativa(p, by_id[p["game_id"]]))
    return {"dia": day, "apostas": picks[:n]}


# --- texto humano para cada aposta aconselhada ---------------------------------------
def _n(x):
    return dec(x, ".1")


def _form_words(t):
    f = t["forma"]
    w, d = sum(x["r"] == "V" for x in f), sum(x["r"] == "D" for x in f)
    if not f:
        return "sem jogos na época"
    if w >= 4:
        return f"ganhou {w} dos últimos {len(f)}"
    if d >= 4:
        return f"perdeu {d} dos últimos {len(f)}"
    if d == 0:
        return f"sem perder nos últimos {len(f)}"
    plural = lambda n, a, b: f"{n} {a if n == 1 else b}"
    return f"{plural(w, 'vitória', 'vitórias')} e {plural(d, 'derrota', 'derrotas')} nos últimos {len(f)}"


def luck_signals(an):
    """Sinais de regressão: (equipa, texto, efeito na força da equipa, efeito nos golos do jogo)."""
    out = []
    for t, x in an["teams"].items():
        s = x["total"] or {}
        m, g = s.get("sorte_m"), s.get("sorte_s")
        if m is not None and m <= -2.5:
            out.append((t, f"o {t} tem marcado {_n(-m)} golos abaixo do que cria e deve melhorar na finalização", +1, +1))
        if m is not None and m >= 2.5:
            out.append((t, f"o {t} tem marcado {_n(m)} golos acima do que cria, um ritmo difícil de manter", -1, -1))
        if g is not None and g <= -2.5:
            out.append((t, f"a defesa do {t} tem sofrido {_n(-g)} golos menos do que mereceu, sinal de sorte", -1, +1))
        if g is not None and g >= 2.5:
            out.append((t, f"a defesa do {t} tem sofrido {_n(g)} golos mais do que mereceu e deve estabilizar", +1, -1))
    return out


def ah_words(line, team):
    """Explica a linha de handicap asiático sem jargão."""
    if line == 0:
        return f"ganhas se o {team} vencer; com empate recebes o dinheiro de volta"
    if line == -0.25:
        return f"ganhas se o {team} vencer; com empate perdes metade"
    if line == 0.25:
        return f"ganhas se o {team} vencer ou empatar (com empate ganhas metade)"
    if line == -0.5:
        return f"é o mesmo que apostar na vitória do {team}"
    if line == 0.5:
        return f"ganhas se o {team} não perder"
    if line == -0.75:
        return f"ganhas tudo se o {team} vencer por 2 ou mais; por 1 golo ganhas metade"
    if line == 0.75:
        return f"ganhas se o {team} não perder; se perder por 1 golo perdes só metade"
    if line == -1:
        return f"ganhas se o {team} vencer por 2 ou mais; por 1 golo recebes o dinheiro de volta"
    if line == 1:
        return f"ganhas se o {team} não perder; se perder por 1 golo recebes o dinheiro de volta"
    if line < 0:
        return f"o {team} tem de ganhar por mais de {dec(-line, '.2').rstrip('0').rstrip(',')} golos"
    return f"ganhas se o {team} não perder por mais de {dec(line, '.2').rstrip('0').rstrip(',')} golos"


def narrativa(pick, game):
    """Título, explicação e risco em linguagem de pessoa, a partir dos números do jogo."""
    an = game.get("analise")
    h, a = game["home"], game["away"]
    sel = pick["sel"]
    if not an:
        return {"titulo": pick["label"], "texto": "Escolha baseada só no preço do mercado: sem dados da época para explicar.",
                "risco": "Sem leitura da época, confia apenas no preço."}
    th, ta = an["teams"][h], an["teams"][a]
    lh, la = an["model"]["lh"], an["model"]["la"]
    hl, al = th["local"] or {}, ta["local"] or {}
    p = an["model"]["p"]
    pro, contra = [], []
    for t, txt, strength, goals in luck_signals(an):
        if sel in ("ou:+2,5", "ou:-2,5"):
            good = goals > 0 if sel == "ou:+2,5" else goals < 0
        elif sel == "1x2:X":
            continue
        else:
            mine = h if sel in ("1x2:1", "ah:casa") else a
            good = strength > 0 if t == mine else strength < 0
        (pro if good else contra).append(txt)
    if sel == "ou:+2,5":
        titulo = "Jogo para golos"
        texto = (f"Os números apontam para um jogo aberto: {_n(lh + la)} golos esperados. "
                 f"O {h} em casa marca {_n(hl.get('gm', 0))} e sofre {_n(hl.get('gs', 0))} por jogo; "
                 f"o {a} fora tem jogos com {_n(al.get('gm', 0) + al.get('gs', 0))} golos em média.")
        risco = "Se o primeiro golo demorar, o jogo pode fechar e ficar por 2 golos ou menos."
    elif sel == "ou:-2,5":
        titulo = "Jogo de poucos golos"
        texto = (f"Espera-se um jogo fechado: só {_n(lh + la)} golos esperados. "
                 f"O {h} em casa tem jogos com {_n(hl.get('gm', 0) + hl.get('gs', 0))} golos em média e "
                 f"o {a} fora {_n(al.get('gm', 0) + al.get('gs', 0))}.")
        risco = "Um golo cedo obriga uma das equipas a abrir e pode estragar a leitura."
    elif sel in ("1x2:1", "1x2:2"):
        t, o, tt, loc = (h, a, th, "em casa") if sel == "1x2:1" else (a, h, ta, "fora")
        tb = tt["tabela"] or {}
        titulo = f"Vitória do {t}"
        texto = (f"O {t} ({tb.get('pos', '?')}.º, {_form_words(tt)}) é o mais forte em campo e "
                 f"cria {_n(tt['total']['xgf'] or tt['total']['gm'])} golos esperados por jogo. ")
        texto += f"Os números da época dão-lhe {pct(p[sel])} de vitória {loc}."
        risco = f"O empate ({pct(p['1x2:X'])}) é o principal perigo."
    elif sel == "1x2:X":
        titulo = "Empate"
        texto = f"Duas equipas muito equilibradas: {_n(lh)} contra {_n(la)} golos esperados."
        risco = "Basta um golo para perder: é uma aposta de risco alto."
    else:
        side_home = sel == "ah:casa"
        t = h if side_home else a
        line = pick["line"] if side_home else -pick["line"]
        titulo = f"{t} com handicap {line_txt(line)}"
        texto = f"{ah_words(line, t).capitalize()}. O modelo espera {_n(lh)}–{_n(la)} em golos."
        risco = "Com handicap, um golo no fim pode mudar o resultado da aposta."
    if pro:
        texto += " A favor: " + pro[0] + "."
    if contra:
        risco += " Atenção: " + contra[0] + "."
    return {"titulo": titulo, "texto": texto, "risco": risco}


def line_txt(x):
    return "0" if x == 0 else format(x, "+g").replace(".", ",")


# --- especialista (v2, afinado): golo na 1.ª parte, cantos, amarelos, favorito -------------------
import json as _json
import os as _os
from features import entry, features, league_entry, negbin_over, num, poisson_over, predict_mu

MODELS_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "modelos.json")
ODD_FLOOR, ODD_PREF = 1.20, 1.30      # regra do utilizador: nada abaixo de 1,20; de preferência 1,30 ou mais
PICK_MIN, PICK_MAX = 0.74, 0.80  # linha-alvo: acerto calibrado 77–78% e odd mínima 1,28–1,38 (antes 72–85%, odds 1,20–1,25)
BLIND_MIN, BLIND_HIST = 0.90, 0.818    # boletim blindado: backtest 2025/26–2026/27, 77 dias, certo em 81,8%
CONF_ALTA, CONF_MEDIA = 0.80, 0.74
NAMES = {"ht+": "Golo na 1.ª parte", "g2+": "Golo na 2.ª parte", "hs": "Equipa da casa marca", "as": "Equipa de fora marca",
         "c+": "Cantos: mais de", "c-": "Cantos: menos de", "y+": "Amarelos: mais de", "y-": "Amarelos: menos de",
         "fav": "Favorito ganha", "dc": "Dupla hipótese"}
FAMILY = {"ht+": "Golos por parte", "g2+": "Golos por parte", "hs": "Equipa marca", "as": "Equipa marca", "c+": "Cantos",
          "c-": "Cantos", "y+": "Cartões", "y-": "Cartões", "fav": "Resultado", "dc": "Resultado"}
_poisson_over, _negbin_over = poisson_over, negbin_over


def load_cal():
    try:
        with open(MODELS_FILE, encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError):
        return {}


def calibrate(cal, name, p):
    pts = cal.get(name)
    if isinstance(pts, dict):
        pts = pts.get("cal")
    if not pts:
        return p
    xs, ys = [a for a, _ in pts], [b for _, b in pts]
    if p <= xs[0]:
        return ys[0]
    if p >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if p <= xs[i]:
            t = (p - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def _lt(x):
    return dec(x, ".1")


REF_K, REF_LAST, REF_EXTREME = 12, 40, 0.12   # extremos ≈ 10% mais brandos/rigorosos (desvio 0,09 em log)
REF_PENALTY = 0.04                              # backtest Premier League: árbitro brando −0,3 a −0,5 amarelos por jogo
REF_COEF = {"P1": 0.80, "I1": 0.90}  # teste fora da amostra, acerto nos amarelos: Portugal 81,2% -> 83,2%; Itália 85,0% -> 88,6%


def referee_profile(rows, referee):
    """Critério do árbitro: amarelos por falta (últimos 40 jogos) face à liga, encolhido para a média."""
    if not referee:
        return None
    ok = [r for r in rows if num(r, "HY") is not None and num(r, "HF") is not None]
    if len(ok) < 60:
        return None
    lg = ok[-380:]
    ly = sum(num(r, "HY") + num(r, "AY") for r in lg) / len(lg)
    lf = sum(num(r, "HF") + num(r, "AF") for r in lg) / len(lg)
    mine = [r for r in ok if (r.get("Referee") or "").strip() == referee.strip()][-REF_LAST:]
    ys = sum(num(r, "HY") + num(r, "AY") for r in mine)
    fs = sum(num(r, "HF") + num(r, "AF") for r in mine)
    rel = math.log(((ys + REF_K * ly) / (fs + REF_K * lf)) / (ly / lf))
    kind = "brando" if rel <= -REF_EXTREME else "rigoroso" if rel >= REF_EXTREME else "normal"
    return {"nome": referee.strip(), "jogos": len(mine), "rel": round(rel, 3), "tipo": kind,
            "amarelos_jogo": round(ys / len(mine), 1) if mine else None}


def especialista(game, rows, modelos, live=None):
    """Os mercados de especialista de um jogo, cada um na melhor linha, com acerto calibrado.

    rows = épocas anterior + atual da liga, por ordem cronológica; modelos = data/modelos.json.
    """
    if not modelos:
        return []
    h, a = game["home"], game["away"]
    H = [e for r in rows if h in (r["HomeTeam"], r["AwayTeam"]) for e in [entry(r, h)] if e]
    A = [e for r in rows if a in (r["HomeTeam"], r["AwayTeam"]) for e in [entry(r, a)] if e]
    L = [e for r in rows for e in [league_entry(r)] if e]
    mk = game.get("mk") or {}
    ft = features(H, A, L, mk)
    if not ft:
        return []
    M, cal = modelos["models"], modelos["cal"]
    mu = {k: predict_mu(M[k], ft) for k in ("ht", "c", "y", "g2", "hg", "ag") if k in M}
    game["mu"] = {k: round(v, 3) for k, v in mu.items()}  # o modelo do intervalo parte daqui
    ref = referee_profile(rows, game.get("referee"))
    if ref and game.get("div") in REF_COEF:
        mu["y"] *= math.exp(REF_COEF[game["div"]] * ref["rel"])  # critério do árbitro (cartões por falta)
    cands = {"ht+": [(0.5, 1 - math.exp(-mu["ht"]))], "c+": [], "c-": [], "y+": [], "y-": []}
    for key, fam in (("g2+", "g2"), ("hs", "hg"), ("as", "ag")):
        if fam in mu:
            cands[key] = [(0.5, 1 - math.exp(-mu[fam]))]
    for fam in ("c", "y"):
        for line in modelos["lines"][fam]:
            po = negbin_over(mu[fam], line, M[fam]["disp"])
            cands[fam + "+"].append((line, po))
            cands[fam + "-"].append((line, 1 - po))
    fav = None
    if mk.get("pH") is not None and mk.get("pA") is not None:
        fav = h if mk["pH"] >= mk["pA"] else a
        cands["fav"] = [(None, max(mk["pH"], mk["pA"]))]
        if mk.get("pD") is not None:
            cands["dc"] = [(None, max(mk["pH"], mk["pA"]) + mk["pD"])]
    last = lambda T, f_: [f_(x) for x in T[-10:]]
    ctx = {"ht_h": sum(last(H, lambda x: x["htf"] + x["hta"] > 0)), "ht_a": sum(last(A, lambda x: x["htf"] + x["hta"] > 0)),
           "c_h": sum(last(H, lambda x: x["cf"] + x["ca"])) / len(H[-10:]), "c_a": sum(last(A, lambda x: x["cf"] + x["ca"])) / len(A[-10:]),
           "y_h": sum(last(H, lambda x: x["yf"] + x["ya"])) / len(H[-10:]), "y_a": sum(last(A, lambda x: x["yf"] + x["ya"])) / len(A[-10:]),
           "f_h": sum(last(H, lambda x: x["ff"])) / len(H[-10:]), "f_a": sum(last(A, lambda x: x["ff"])) / len(A[-10:]),
           "mu": mu, "lam_tot": ft["_lam_tot"], "balance": ft["y_balance"], "fav": fav}
    ctx["ref"] = ref
    out = []
    for key, opts in cands.items():
        scored = []
        for line, p_raw in opts:
            p = calibrate(cal, key, p_raw)
            adj = (live or {}).get(NAMES[key])
            if adj:
                p = min(0.97, max(0.03, p + adj))  # correção aprendida com os resultados reais
            if ref and ((key == "y+" and ref["tipo"] == "brando") or (key == "y-" and ref["tipo"] == "rigoroso")):
                p = max(0.03, p - REF_PENALTY)  # filtro de risco: o árbitro joga contra esta aposta
            scored.append((line, p, p_raw))
        # a linha dentro da faixa-alvo; sem nenhuma lá dentro, a mais próxima dela
        line, p, p_raw = min(scored, key=lambda s: (max(PICK_MIN - s[1], s[1] - PICK_MAX, 0), -s[1]))
        label = {"ht+": "Há golo na 1.ª parte", "c+": f"Mais de {_lt(line)} cantos" if line else "",
                 "c-": f"Menos de {_lt(line)} cantos" if line else "", "y+": f"Mais de {_lt(line)} amarelos" if line else "",
                 "y-": f"Menos de {_lt(line)} amarelos" if line else "", "fav": f"{fav} ganha",
                 "g2+": "Há golo na 2.ª parte", "hs": f"{h} marca", "as": f"{a} marca", "dc": f"{fav} ou empate"}[key]
        band = None
        for lo, b in sorted(((float(k), v) for k, v in modelos.get("faixas", {}).get(key, {}).items()), reverse=True):
            if p >= lo:
                band = b
                break
        o = {"key": key + (format(line, "g") if line is not None and key not in ("hs", "as") else ""), "name": NAMES[key], "label": label,
             "linhas": [[ln, round(q, 3)] for ln, q, _ in scored] if len(scored) > 1 else None,  # escada para o caça-valor
             "family": FAMILY[key], "line": line, "p": round(p, 3), "p_raw": round(p_raw, 3),
             "conf": "Alta" if p >= CONF_ALTA else "Média" if p >= CONF_MEDIA else "Baixa",
             "fair_odd": round(1 / p, 2), "min_odd": round(1.02 / p, 2), "hist": band}
        o.update(_texto_especialista(o, key, game, ctx))
        if ref and ((key == "y+" and ref["tipo"] == "brando") or (key == "y-" and ref["tipo"] == "rigoroso")):
            o["veto"] = f"Árbitro {ref['tipo']} ({ref['nome']}): não aconselho esta aposta."
        out.append(o)
    return sorted(out, key=lambda o: -o["p"])


def _texto_especialista(o, key, g, c):
    h, a = g["home"], g["away"]
    hist = o["hist"]
    track = (f" No histórico, apostas destas acertaram {pct(hist['acerto'])} em {hist['n']} casos." if hist else "")
    if key == "g2+":
        return {"titulo": "Golo depois do intervalo",
                "texto": f"A 2.ª parte é onde caem mais golos. O mercado espera {_n(c['lam_tot'])} golos no jogo e "
                         f"para a 2.ª parte conto com {_n(c['mu']['g2'])}." + track,
                "risco": "Um jogo já resolvido ao intervalo pode adormecer na 2.ª parte."}
    if key in ("hs", "as"):
        t, lam = (h, c["mu"]["hg"]) if key == "hs" else (a, c["mu"]["ag"])
        return {"titulo": f"{t} marca",
                "texto": f"Pelos números da época e pelo que o mercado espera, {t} deve marcar {_n(lam)} golos neste jogo; "
                         f"basta um para a aposta ganhar." + track,
                "risco": "Um guarda-redes em noite inspirada chega para estragar a aposta."}
    if key == "dc":
        return {"titulo": "Sem perder",
                "texto": f"Ganhas se {c['fav']} vencer ou empatar. O mercado dá-lhe "
                         f"{round(o['p'] * 100)}% de não perder, e os números da época vão no mesmo sentido." + track,
                "risco": "A odd é baixa: é para juntar a um boletim ou só a partir da odd mínima."}
    if key == "ht+":
        return {"titulo": "Golo antes do intervalo",
                "texto": f"{h}: golo na 1.ª parte em {c['ht_h']} dos últimos 10 jogos. {a}: {c['ht_a']} em 10. "
                         f"O mercado espera {_n(c['lam_tot'])} golos no jogo; até ao intervalo conto com {_n(c['mu']['ht'])}." + track,
                "risco": "Equipas que entram cautelosas podem empurrar o primeiro golo para a 2.ª parte."}
    if key in ("c+", "c-"):
        return {"titulo": "Jogo de muitos cantos" if key == "c+" else "Poucos cantos",
                "texto": f"{h}: {_n(c['c_h'])} cantos por jogo nos últimos 10. {a}: {_n(c['c_a'])}. "
                         f"Espero cerca de {_n(c['mu']['c'])} cantos, o que deixa margem para a linha de {_lt(o['line'])}." + track,
                "risco": "Um golo cedo muda o padrão: quem perde ataca mais e gera cantos."}
    if key in ("y+", "y-"):
        extra = " Jogo equilibrado, o que costuma aquecer." if key == "y+" and c["balance"] > 0.8 else ""
        ref = c.get("ref")
        if ref:
            rtxt = {"brando": "brando: tira poucos amarelos por falta", "rigoroso": "rigoroso: tira muitos amarelos por falta",
                    "normal": "de critério normal"}[ref["tipo"]]
            extra += f" Árbitro: {ref['nome']}, {rtxt} ({ref['jogos']} jogos analisados)."
        return {"titulo": "Jogo quente" if key == "y+" else "Jogo limpo",
                "texto": f"{h}: {_n(c['y_h'])} amarelos e {_n(c['f_h'])} faltas por jogo nos últimos 10. "
                         f"{a}: {_n(c['y_a'])} e {_n(c['f_a'])}. Espero cerca de {_n(c['mu']['y'])} amarelos.{extra}" + track,
                "risco": "Um vermelho cedo ou um jogo resolvido cedo muda o padrão de cartões."
                         + ("" if ref else " Sem dados do árbitro para esta liga.")}
    return {"titulo": "O favorito resolve",
            "texto": (f"O mercado vê {c['fav']} como claramente mais forte, e os números da época não o contrariam." if o["p"] >= 0.7 else
                      f"{c['fav']} é favorito, mas sem margem folgada: o empate e a surpresa estão em jogo.") + track,
            "risco": "A odd é baixa: só compensa a partir da odd mínima, e um empate estraga a aposta."}


def stem(sel):
    """Mercado sem a linha: esp:y-4.5 -> esp:y-. É a unidade em que se aprende o preço das casas."""
    return re.sub(r"[\d.]+$", "", sel)


PRICE_MIN_N = 40  # odds registadas num mercado antes de o preço aprendido mexer na ordem


def selecao_especialista(games, today, n=4, precos=None):
    """Até n apostas por dia nos mercados de especialista (uma por jogo).

    precos = {mercado sem linha: (n, margem média da casa sobre a odd justa)}: os mercados onde a casa costuma pagar
    acima do justo vêm primeiro; sem odds suficientes, ordena só pelo acerto.
    """
    def edge(o):
        k_n, m = (precos or {}).get(stem("esp:" + o["key"]), (0, 0.0))
        return m if k_n >= PRICE_MIN_N else 0.0
    games = [g for g in games if g["minutes_to_ko"] > 0]  # só o que ainda se pode apostar
    days = sorted({g["kickoff"][:10] for g in games if g["kickoff"][:10] >= today})
    if not days:
        return {"dia": None, "apostas": [], "boletins": [], "blindado": []}
    day = days[0]
    best, blind = [], []
    for g in games:
        if g["kickoff"][:10] != day or not g.get("especialista"):
            continue
        ok = [o for o in g["especialista"] if not o.get("veto")]
        cands = [o for o in ok if PICK_MIN <= o["p"] <= PICK_MAX]
        if cands:
            top = min(cands, key=lambda o: (edge(o) < 0.02, -o["p"]))
            best.append({**top, "game_id": g["id"], "sel": "esp:" + top["key"], "market": top["family"], "valor_casa": edge(top) or None})
        # boletim blindado (≥90%) desligado: as odds dessas seleções ficam sempre abaixo de 1,20 (regra do utilizador)
    best.sort(key=lambda o: ((o["valor_casa"] or 0) < 0.02, -o["p"]))  # primeiro onde a casa paga ≥2% acima do justo
    blind.sort(key=lambda o: -o["p"])
    return {"dia": day, "apostas": best[:n], "blindado": blind[:3], "boletins": make_boletins(best[:n], blind[:3])}


def make_boletins(picks, blind=()):
    """Dupla e tripla com as apostas aconselhadas e o boletim blindado (3 seleções >= 90%). Pernas completas."""
    hist = load_cal().get("boletins", {})
    out = []
    for k, nome in ((2, "Dupla"), (3, "Tripla")):
        if len(picks) >= k:
            legs = picks[:k]
            out.append({"nome": nome, "pernas": legs, "p": round(math.prod(x["p"] for x in legs), 3),
                        "odd_min": round(math.prod(x["min_odd"] for x in legs), 2), "hist": hist.get(str(k))})
    if len(blind) == 3:
        out.append({"nome": "Blindado", "pernas": list(blind), "p": round(math.prod(x["p"] for x in blind), 3),
                    "odd_min": round(math.prod(x["min_odd"] for x in blind), 2), "hist": BLIND_HIST,
                    "nota": "Três seleções de 90% ou mais. Sozinhas pagam quase nada; juntas valem uma aposta de ~82%."})
    return out
