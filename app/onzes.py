"""Onzes confirmados (ESPN, ~1 h antes): quem dos titulares habituais fica de fora.

Titular habitual = começou pelo menos 4 dos últimos 5 jogos da liga. É informação nova (não histórico), mas o efeito
no acerto ainda não foi medido: serve de alerta para confirmares antes de entrar, não muda a probabilidade.
"""
import json, os, time
import live

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "data", "espn")
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={ev}"
SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/teams/{team}/schedule"
LAST_N, REGULAR = 5, 4
WINDOW_MIN = 90   # só procura o onze nos jogos que começam dentro de 90 min
_mem = {}


def _fetch(url, key, ttl):
    """JSON com cache: em memória (ttl s) e em disco para o que já não muda (jogos terminados, ttl=None)."""
    path = os.path.join(CACHE_DIR, key + ".json")
    if ttl is None and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    if key in _mem and ttl is not None and time.time() - _mem[key][0] < ttl:
        return _mem[key][1]
    import urllib.request
    data = live._get(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"}))
    _mem[key] = (time.time(), data)
    if ttl is None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"rosters": data.get("rosters", [])}, fh)  # só o que interessa, para não encher o disco
    return data


def starters(roster):
    return {p["athlete"]["id"]: (p["athlete"].get("shortName") or p["athlete"]["displayName"], (p.get("position") or {}).get("abbreviation", ""))
            for p in roster if p.get("starter")}


def regulars(div, team_id, before):
    """{id: (nome, posição, jogos como titular)} dos titulares habituais antes de uma data (iso)."""
    lg = live.SLUG[div]
    sched = _fetch(SCHEDULE.format(lg=lg, team=team_id), f"sched_{lg}_{team_id}", 12 * 3600)
    past = [e for e in sched.get("events", []) if e["date"] < before and e["competitions"][0]["status"]["type"]["state"] == "post"][-LAST_N:]
    count, info = {}, {}
    for e in past:
        r = next((x for x in _fetch(SUMMARY.format(lg=lg, ev=e["id"]), f"sum_{e['id']}", None).get("rosters", [])
                  if x["team"]["id"] == team_id), None)
        for pid, v in starters(r["roster"] if r else []).items():
            count[pid] = count.get(pid, 0) + 1
            info[pid] = v
    need = min(REGULAR, len(past) - 1) if past else 99
    return {pid: (*info[pid], n) for pid, n in count.items() if n >= need}, len(past)


def team_report(div, roster_entry, before):
    team = roster_entry["team"]
    xi = starters(roster_entry.get("roster", []))
    if len(xi) < 11:
        return None
    reg, n = regulars(div, team["id"], before)
    out = [{"nome": v[0], "pos": v[1], "jogos": v[2]} for pid, v in reg.items() if pid not in xi]
    gk_out = any(o["pos"] == "G" for o in out)
    return {"equipa": team["displayName"], "faltam": out, "gr_trocado": gk_out, "base": n}


def check(g, ev):
    """Relatório dos onzes de um jogo da agenda (ev = estado ESPN do live.match)."""
    lg = live.SLUG[g["div"]]
    data = _fetch(SUMMARY.format(lg=lg, ev=ev["espn"]), f"pre_{ev['espn']}", 300)
    rs = {r["homeAway"]: r for r in data.get("rosters", []) if r.get("homeAway")}
    if len(rs) < 2:
        return {"confirmado": False}
    before = data.get("header", {}).get("competitions", [{}])[0].get("date") or g["kickoff"]
    home, away = team_report(g["div"], rs["home"], before), team_report(g["div"], rs["away"], before)
    if not home or not away:
        return {"confirmado": False}
    alerta = [t for t in (home, away) if len(t["faltam"]) >= 3 or t["gr_trocado"]]
    n_txt = lambda n: "falta 1 titular habitual" if n == 1 else f"faltam {n} titulares habituais"
    txt = lambda t, name: (f"{name}: {n_txt(len(t['faltam']))} ({', '.join(o['nome'] for o in t['faltam'][:4])})"
                           + (", incluindo o guarda-redes" if t["gr_trocado"] else "") if t["faltam"] else f"{name}: o onze habitual")
    return {"confirmado": True, "casa": home, "fora": away, "atencao": bool(alerta),
            "texto": f"Onzes confirmados. {txt(home, g['home'])}. {txt(away, g['away'])}."
                     + (" Muitas mudanças: confirma se a aposta ainda faz sentido antes de entrar." if alerta else "")}


def _self_test():
    ro = {"team": {"id": "1", "displayName": "A"}, "roster": [{"starter": True, "athlete": {"id": str(i), "displayName": f"J{i}"},
                                                                "position": {"abbreviation": "G" if i == 0 else "M"}} for i in range(11)]}
    global regulars
    real, regulars = regulars, lambda div, t, b: ({"0": ("J0", "G", 5), "1": ("J1", "M", 5), "99": ("Craque", "F", 5)}, 5)
    try:
        r = team_report("E0", ro, "2026-10-18")
        assert [o["nome"] for o in r["faltam"]] == ["Craque"] and not r["gr_trocado"], r
        ro["roster"][0]["starter"] = False
        assert team_report("E0", ro, "2026-10-18") is None  # onze incompleto: ainda não saiu
    finally:
        regulars = real


if __name__ == "__main__":
    _self_test()
    print("ok")
