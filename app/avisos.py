"""Avisos no telemóvel via ntfy.sh (grátis, sem conta): o utilizador subscreve um canal secreto na app ntfy.

O servidor vigia os jogos de minuto a minuto e envia: leituras ao vivo ≥85%, onzes confirmados dos jogos
aconselhados ou com aposta, e lances (golo, cartão, canto) dos jogos com aposta aberta. Só envia depois de o
utilizador ativar (data/ntfy.json). O canal é público para quem souber o nome: por isso o nome é aleatório e longo.
"""
import json, os, secrets, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "data", "ntfy.json")
SEEN = os.path.join(HERE, "data", "ntfy_vistos.json")
SERVER = "https://ntfy.sh"


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False)


def config():
    return _load(CFG, {"ativo": False, "topic": None})


def set_active(on):
    c = config()
    if on and not c.get("topic"):
        c["topic"] = "bigodds-" + secrets.token_urlsafe(12).replace("_", "x").replace("-", "y").lower()
    c["ativo"] = bool(on)
    _save(CFG, c)
    return c


def send(title, body, tags=""):
    c = config()
    if not (c.get("ativo") and c.get("topic")):
        return False
    data = json.dumps({"topic": c["topic"], "title": title, "message": body, "tags": [t for t in tags.split(",") if t]}).encode()
    req = urllib.request.Request(SERVER, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10):
        return True


def events(games, bet_games, pick_ids, seen, lembretes=()):
    """Mensagens novas (título, texto, etiquetas) a partir do estado dos jogos. Atualiza `seen`.

    bet_games: {id do jogo: [rótulos das apostas abertas]}; pick_ids: jogos do boletim do dia.
    Na primeira vez que vê um jogo com aposta, guarda os lances já ocorridos sem avisar.
    """
    out = []
    for r in lembretes:
        k = f"lembrete|{r['game_id']}|{r['sel']}"
        if k not in seen:
            seen[k] = 1
            out.append((f"⏰ Faltam {r['minutos']} min: {r['home']} – {r['away']}",
                        f"{r['label']} · {round(r['p'] * 100)}% · entra a ≥ {r['min_odd']:.2f} ({r['porque']}). Ainda não registaste esta aposta.", "alarm_clock"))
    for g in games:
        gid, l, o = g["id"], g.get("live"), g.get("onzes")
        for s in g.get("ao_vivo") or []:
            k = f"live|{gid}|{s['key']}"
            if k not in seen:
                seen[k] = 1
                out.append((f"Bigodds ao vivo: {g['home']} – {g['away']}", f"{s['label']} · {round(s['p'] * 100)}% · entra só a ≥ {s['min_odd']:.2f}", "rotating_light"))
        if o and o.get("confirmado") and (gid in bet_games or gid in pick_ids) and f"onzes|{gid}" not in seen:
            seen[f"onzes|{gid}"] = 1
            out.append((f"Onzes: {g['home']} – {g['away']}", o["texto"], "warning" if o.get("atencao") else "white_check_mark"))
        if gid not in bet_games or not l:
            continue
        keys = [(f"{e['tipo']}|{e['lado']}|{e['min']}|{e['quem']}", e) for e in l.get("eventos") or []]
        for i, n in enumerate(l.get("cantos") or []):
            keys += [(f"canto|{i}|{c}", {"tipo": "canto", "lado": "away" if i else "home", "n": c}) for c in range(1, int(n or 0) + 1)]
        first = f"jogo|{gid}" not in seen
        seen[f"jogo|{gid}"] = 1
        for k, e in keys:
            k = f"ev|{gid}|{k}"
            if k in seen:
                continue
            seen[k] = 1
            if first:
                continue
            team = g["home"] if e["lado"] == "home" else g["away"]
            head = {"golo": f"⚽ Golo {'na própria baliza a favor de' if e.get('og') else 'de'} {team}", "amarelo": f"🟨 Amarelo para {team}",
                    "vermelho": f"🟥 Vermelho para {team}", "canto": f"⛳ Canto para {team} ({e.get('n')}.º)"}[e["tipo"]]
            if e.get("min"):
                head += f" · {e['min']}"
            body = (f"{e['quem'] + ' · ' if e.get('quem') else ''}{g['home']} {l['hg']}–{l['ag']} {g['away']} · "
                    f"{sum(l.get('amarelos') or [0])} amarelos · {sum(int(x or 0) for x in l.get('cantos') or [])} cantos · "
                    f"A tua aposta: {' + '.join(bet_games[gid])}")
            out.append((head, body, "soccer"))
    return out


def run_once(games, bet_games, pick_ids, lembretes=()):
    """Calcula e envia os avisos novos; devolve quantos enviou."""
    if not config().get("ativo"):
        return 0
    seen = _load(SEEN, {})
    msgs = events(games, bet_games, pick_ids, seen, lembretes)
    sent = 0
    for t, b, tags in msgs:
        try:
            sent += send(t, b, tags)
        except Exception:
            pass  # sem rede: este aviso perde-se, os seguintes continuam
    _save(SEEN, seen)
    return sent


def _self_test():
    g = {"id": "E0-1", "home": "Forest", "away": "Arsenal", "live": {"hg": 0, "ag": 0, "eventos": [], "cantos": ["1", "0"], "amarelos": [0, 0]}}
    seen = {}
    assert events([g], {"E0-1": ["Arsenal ganha"]}, set(), seen) == []  # primeira vista: só memoriza
    g["live"].update(ag=1, eventos=[{"tipo": "golo", "lado": "away", "min": "80'", "quem": "Madueke"}], cantos=["1", "1"])
    m = events([g], {"E0-1": ["Arsenal ganha"]}, set(), seen)
    assert [x[0] for x in m] == ["⚽ Golo de Arsenal · 80'", "⛳ Canto para Arsenal (1.º)"], m
    assert "A tua aposta: Arsenal ganha" in m[0][1] and events([g], {"E0-1": ["x"]}, set(), seen) == []
    g2 = {"id": "I1-2", "home": "Milan", "away": "Atalanta", "ao_vivo": [{"key": "k", "label": "Há golo na 2.ª parte", "p": 0.87, "min_odd": 1.17}],
          "onzes": {"confirmado": True, "texto": "Onzes confirmados.", "atencao": False}}
    m = events([g2], {}, {"I1-2"}, seen)
    assert len(m) == 2 and events([g2], {}, {"I1-2"}, seen) == []
    lr = [{"game_id": "x", "sel": "s", "home": "A", "away": "B", "label": "A ganha", "p": 0.8, "min_odd": 1.28, "porque": "aposta do dia", "minutos": 29}]
    assert events([], {}, set(), seen, lr)[0][0] == "⏰ Faltam 29 min: A – B" and events([], {}, set(), seen, lr) == []


if __name__ == "__main__":
    _self_test()
    print("ok")
