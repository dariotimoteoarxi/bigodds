"""Jogos ao vivo: placar público da ESPN (sem conta) e leituras ao intervalo validadas no backtest.

Modelo do intervalo (especialista_intervalo.py, teste 2025/26–2026/27): com confiança ≥85%,
"Há golo na 2.ª parte" acertou 85,4% (261 jogos) e "Menos de (intervalo + 2,5) golos" 85,1% (819 jogos).
"""
import difflib, gzip, json, math, re, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from arbitros import norm
from consultor import calibrate
from features import poisson_over

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/scoreboard?dates={d}"
SLUG = {"E0": "eng.1", "SP1": "esp.1", "I1": "ita.1", "D1": "ger.1", "F1": "fra.1", "P1": "por.1"}
CACHE_S = 60
LIVE_MIN = 0.85   # só sugere ao vivo acima disto (pedido do utilizador)
_cache = {}


def _get(req):
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)  # a ESPN às vezes comprime sem pedirmos


def scoreboard(div, day):
    """Eventos ESPN de uma liga num dia (aaaammdd), em cache 60 s; lista vazia se falhar a rede."""
    k = (div, day)
    if k in _cache and time.time() - _cache[k][0] < CACHE_S:
        return _cache[k][1]
    try:
        req = urllib.request.Request(ESPN.format(lg=SLUG[div], d=day), headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"})
        ev = _get(req).get("events") or []
    except Exception:
        ev = _cache.get(k, (0, []))[1]  # sem rede: fica o último placar conhecido
    _cache[k] = (time.time(), ev)
    return ev


def _state(e):
    c = e["competitions"][0]
    side = {t["homeAway"]: t for t in c["competitors"]}
    st = e["status"]
    stat = lambda t, n: next((s["displayValue"] for s in t.get("statistics", []) if s["name"] == n), None)
    reds, yellows, ev = {"home": 0, "away": 0}, {"home": 0, "away": 0}, []
    for d in c.get("details") or []:
        who = "home" if d.get("team", {}).get("id") == side["home"]["team"]["id"] else "away"
        tipo = "golo" if d.get("scoringPlay") else "vermelho" if d.get("redCard") else "amarelo" if d.get("yellowCard") else None
        if not tipo or d.get("shootout"):
            continue
        reds[who] += tipo == "vermelho"
        yellows[who] += tipo == "amarelo"
        ev.append({"tipo": tipo, "lado": who, "min": (d.get("clock") or {}).get("displayValue", ""), "og": bool(d.get("ownGoal")),
                   "pen": bool(d.get("penaltyKick")), "quem": next((a.get("shortName") or a.get("displayName") for a in d.get("athletesInvolved") or []), "")})
    goals = lambda: [sum(e["lado"] == x for e in ev if e["tipo"] == "golo") for x in ("home", "away")]
    if any(e["og"] for e in ev) and goals() != [int(side[x]["score"] or 0) for x in ("home", "away")]:
        for e in ev:  # a ESPN pode pôr o autogolo na equipa do jogador: acerta pelo placar
            if e["og"]:
                e["lado"] = "away" if e["lado"] == "home" else "home"
    return {"espn": e["id"], "estado": st["type"]["state"], "fase": st["type"]["name"], "detalhe": st["type"].get("shortDetail"),
            "minuto": st.get("displayClock"), "parte": st.get("period"),
            "hg": int(side["home"]["score"] or 0), "ag": int(side["away"]["score"] or 0),
            "cantos": [stat(side[s], "wonCorners") for s in ("home", "away")],
            "remates": [stat(side[s], "shotsOnTarget") for s in ("home", "away")],
            "posse": [stat(side[s], "possessionPct") for s in ("home", "away")],
            "vermelhos": [reds["home"], reds["away"]], "amarelos": [yellows["home"], yellows["away"]], "eventos": ev,
            "home_espn": side["home"]["team"]["displayName"], "away_espn": side["away"]["team"]["displayName"]}


def match(games, now, include_pre=False):
    """{id do jogo: estado ao vivo} para os jogos de hoje já começados (ou a começar)."""
    out = {}
    day = now.strftime("%Y%m%d")
    for div in {g["div"] for g in games if g["kickoff"][:10] == now.date().isoformat()}:
        evs = [_state(e) for e in scoreboard(div, day)]
        mine = [g for g in games if g["div"] == div and g["kickoff"][:10] == now.date().isoformat()]
        for s in evs:
            if s["estado"] == "pre" and not include_pre:
                continue
            sim = lambda g: (difflib.SequenceMatcher(None, norm(g["home"]), norm(s["home_espn"])).ratio()
                             + difflib.SequenceMatcher(None, norm(g["away"]), norm(s["away_espn"])).ratio())
            best = max(mine, key=sim, default=None)
            if best and sim(best) >= 1.1:  # as duas equipas têm de bater, não só uma
                out[best["id"]] = s
    return out


def leituras(g, s, modelo):
    """Sugestões ao intervalo com confiança ≥85%. Só ao intervalo e sem expulsões (o modelo não as conhece)."""
    mu0 = (g.get("mu") or {}).get("g2")
    if s["fase"] != "STATUS_HALFTIME" or not mu0 or not modelo or any(s["vermelhos"]):
        return []
    pH, pA = (g.get("mk") or {}).get("pH"), (g.get("mk") or {}).get("pA")
    fav_losing = float(pH is not None and pA is not None and (s["hg"] < s["ag"] if pH >= pA else s["ag"] < s["hg"]))
    x = {"log_mu": math.log(mu0), "ht_tot": s["hg"] + s["ag"], "ht_gd": abs(s["hg"] - s["ag"]), "fav_losing": fav_losing}
    mu = math.exp(modelo["intercept"] + sum(c * x[k] for k, c in zip(modelo["cols"], modelo["coef"])))
    tot = s["hg"] + s["ag"]
    cands = [("Há golo na 2.ª parte", "Há golo na 2.ª parte", 1 - math.exp(-mu)),
             ("Menos de (intervalo + 2,5) golos", f"Menos de {tot + 2},5 golos no jogo", 1 - poisson_over(mu, 2.5))]
    out = []
    for name, label, p_raw in cands:
        p = calibrate(modelo["cal"], name, p_raw)
        if p >= LIVE_MIN:
            out.append({"key": name, "label": label, "p": round(p, 3), "min_odd": round(1.02 / p, 2), "mu_2p": round(mu, 2),
                        "texto": f"Ao intervalo está {s['hg']}-{s['ag']}. Antes do jogo contava com {mu0:.1f} golos na 2.ª parte; "
                                 f"com o resultado de agora espero {mu:.1f}. Em jogos parecidos isto bateu {round(p * 100)}% das vezes. "
                                 f"Só entra se a 22bet ou a Betclic pagarem pelo menos {1.02 / p:.2f}."})
    return out


def _minute(txt):
    m = re.match(r"(\d+)'(?:\+(\d+))?", txt or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def prob_golo(g, s, modelo):
    """Probabilidade de ainda haver golo (no jogo e de cada equipa) até ao fim.

    Ritmo esperado antes do jogo (golos por parte do especialista); ao intervalo e na 2.ª parte usa o modelo do
    intervalo, que conhece o resultado aos 45'. shortcut: ritmo constante dentro de cada parte, só validado ao intervalo.
    """
    mu = g.get("mu") or {}
    if s["estado"] != "in" or not mu.get("ht") or not mu.get("g2"):
        return None
    base, _ = _minute(s.get("minuto"))
    first_half = s.get("parte") == 1 and s["fase"] != "STATUS_HALFTIME"
    if first_half:
        rem = mu["ht"] * max(0, 45 - base) / 45 + mu["g2"]
    else:
        ht = [sum(e["lado"] == x for e in s.get("eventos", []) if e["tipo"] == "golo" and _minute(e["min"])[0] <= 45) for x in ("home", "away")]
        mu2 = mu["g2"]
        if modelo:
            pH, pA = (g.get("mk") or {}).get("pH"), (g.get("mk") or {}).get("pA")
            losing = float(pH is not None and pA is not None and (ht[0] < ht[1] if pH >= pA else ht[1] < ht[0]))
            x = {"log_mu": math.log(mu["g2"]), "ht_tot": sum(ht), "ht_gd": abs(ht[0] - ht[1]), "fav_losing": losing}
            mu2 = math.exp(modelo["intercept"] + sum(c * x[k] for k, c in zip(modelo["cols"], modelo["coef"])))
        rem = mu2 * (1 if s["fase"] == "STATUS_HALFTIME" else max(0, 90 - base) / 45)
    sh = mu["hg"] / (mu["hg"] + mu["ag"]) if mu.get("hg") and mu.get("ag") else 0.5
    p = lambda lam: round(1 - math.exp(-lam), 3)
    return {"jogo": p(rem), "casa": p(rem * sh), "fora": p(rem * (1 - sh))}


def decided(pick, g, s):
    """1 ganha / 0 perdida / None ainda em aberto, para uma aposta do especialista, pelo placar ao vivo da ESPN.

    O fecho oficial continua a vir do football-data no dia seguinte; isto só antecipa o que já está decidido.
    """
    key, line, end = pick.get("key"), pick.get("line"), s["estado"] == "post"
    goals = [e for e in s.get("eventos") or [] if e["tipo"] == "golo"]
    if key == "ht+":
        return 1 if any(_minute(e["min"])[0] <= 45 for e in goals) else 0 if (end or s["fase"] == "STATUS_HALFTIME" or (s.get("parte") or 1) >= 2) else None
    if key == "g2+":
        return 1 if any(_minute(e["min"])[0] > 45 for e in goals) else 0 if end else None
    if key in ("hs", "as"):
        return 1 if (s["hg"] if key == "hs" else s["ag"]) else 0 if end else None
    if key and key[0] in "cy" and line is not None:
        cur = sum(s.get("amarelos") or [0]) if key[0] == "y" else sum(int(x or 0) for x in s.get("cantos") or [0])
        if key[1] == "+":
            return 1 if cur > line else 0 if end else None
        return 0 if cur > line else 1 if end else None
    if key in ("fav", "dc") and end:
        home = (pick.get("label") or "").startswith(g["home"])
        a, b = (s["hg"], s["ag"]) if home else (s["ag"], s["hg"])
        return int(a > b) if key == "fav" else int(a >= b)
    return None


def _self_test():
    m = {"cols": ["log_mu", "ht_tot", "ht_gd", "fav_losing"], "coef": [1, 0, 0, 0], "intercept": 0, "cal": {}}
    g = {"mu": {"g2": 2.2}, "mk": {"pH": 0.6, "pA": 0.2}}
    s = {"fase": "STATUS_HALFTIME", "hg": 1, "ag": 0, "vermelhos": [0, 0]}
    r = leituras(g, s, m)
    assert r and r[0]["label"] == "Há golo na 2.ª parte" and abs(r[0]["p"] - (1 - math.exp(-2.2))) < 1e-3, r
    assert leituras(g, dict(s, vermelhos=[1, 0]), m) == [] and leituras(g, dict(s, fase="STATUS_SECOND_HALF"), m) == []
    g2 = {"mu": {"ht": 1.0, "g2": 1.5, "hg": 1.5, "ag": 1.0}, "mk": {}}
    a = prob_golo(g2, {"estado": "in", "fase": "STATUS_FIRST_HALF", "parte": 1, "minuto": "0'"}, None)
    b = prob_golo(g2, {"estado": "in", "fase": "STATUS_SECOND_HALF", "parte": 2, "minuto": "80'", "eventos": []}, None)
    assert abs(a["jogo"] - (1 - math.exp(-2.5))) < 1e-3 and b["jogo"] < a["jogo"] and abs(b["casa"] - (1 - math.exp(-1.5 * 10 / 45 * 0.6))) < 1e-3, (a, b)
    assert _minute("45'+2'") == (45, 2) and _minute("") == (0, 0)
    st = {"estado": "post", "fase": "STATUS_FULL_TIME", "parte": 2, "hg": 3, "ag": 2, "cantos": ["4", "5"], "amarelos": [1, 2],
          "eventos": [{"tipo": "golo", "min": "24'"}]}
    gm = {"home": "Milan", "away": "Atalanta"}
    assert decided({"key": "c-", "line": 11.5}, gm, st) == 1 and decided({"key": "y+", "line": 3.5}, gm, st) == 0
    assert decided({"key": "fav", "label": "Milan ganha"}, gm, st) == 1 and decided({"key": "g2+"}, gm, st) == 0
    assert decided({"key": "c-", "line": 11.5}, gm, dict(st, estado="in", cantos=["3", "3"])) is None


if __name__ == "__main__":
    _self_test()
    print("ok")


# --- calendário: próximas semanas das 6 ligas e das taças europeias (a ESPN aceita um mês inteiro: dates=aaaamm) ---
CUPS = {"UCL": ("uefa.champions", "Liga dos Campeões"), "UEL": ("uefa.europa", "Liga Europa"), "UECL": ("uefa.europa.conf", "Conference League")}
CAL_S, CAL_DAYS = 6 * 3600, 28
TZ = ZoneInfo("Europe/Lisbon")


def calendario(games, leagues, now):
    """Jogos dos próximos 28 dias que ainda não estão na agenda (sem odds publicadas, logo sem análise)."""
    comps = {d: (SLUG[d], name) for d, name in leagues.items()} | CUPS
    months = {now.strftime("%Y%m"), (now.replace(day=1) + timedelta(days=32)).strftime("%Y%m")}
    known = {(g["kickoff"][:10], norm(g["home"])) for g in games}
    out = []
    for div, (slug, name) in comps.items():
        for m in months:
            k = ("cal", slug, m)
            if k not in _cache or time.time() - _cache[k][0] > CAL_S:
                try:
                    req = urllib.request.Request(ESPN.format(lg=slug, d=m) + "&limit=300", headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"})
                    _cache[k] = (time.time(), _get(req).get("events") or [])
                except Exception:
                    _cache.setdefault(k, (0, []))  # sem rede: tenta outra vez no próximo pedido
            for e in _cache[k][1]:
                ko = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(TZ)
                if not (now <= ko <= now + timedelta(days=CAL_DAYS)):  # jogos já começados só contam se estiverem na agenda
                    continue
                side = {t["homeAway"]: t["team"].get("shortDisplayName") or t["team"]["displayName"] for t in e["competitions"][0]["competitors"]}
                day = ko.date().isoformat()
                if any(d == day and difflib.SequenceMatcher(None, h, norm(side["home"])).ratio() > 0.6 for d, h in known):
                    continue  # já está na agenda com odds e análise
                item = {"id": "espn-" + e["id"], "div": div, "league": name, "kickoff": ko.isoformat(), "home": side["home"],
                        "away": side["away"], "taca": div in CUPS}
                if div in CUPS:
                    full = {t["homeAway"]: t["team"]["displayName"] for t in e["competitions"][0]["competitors"]}
                    try:
                        import elo  # Elo próprio (só ativo se elo_uefa.py o aprovou no teste)
                        item["elo"] = elo.cup_prediction(full["home"], full["away"], bool(e["competitions"][0].get("neutralSite")))
                    except Exception:
                        item["elo"] = None
                out.append(item)
    return sorted(out, key=lambda x: x["kickoff"])
