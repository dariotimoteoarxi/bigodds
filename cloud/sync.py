"""Tarefa do GitHub Actions: corre o Bigodds em Python e publica na Cloudflare.

  python3 cloud/sync.py completo   análise do dia, boletim, fecho das apostas, calendário e relatório (de 30 em 30 min)
  python3 cloud/sync.py aovivo     placar, leituras ao intervalo, onzes, lembretes e avisos (de 5 em 5 min à hora dos jogos)

Traz as tabelas da D1 para um SQLite temporário, corre o código de sempre (app/server.py) e devolve à D1 só o que
mudou e é dela (previsões, boletins publicados, fecho das apostas). As apostas são escritas pela app, nunca aqui,
por isso uma aposta registada a meio da tarefa não se perde. Não escreve apostas nem canais nos registos (repositório público).
"""
import json, os, sys, tempfile, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, HERE)

TABLES = {"bets": "id", "legs": None, "preds": ("game_id", "name"), "published": ("day", "game_id"), "odds": None}
BATCH_PARAMS = 90  # a D1 aceita até 100 parâmetros por pedido


def pull(cf, con, tables):
    for t in tables:
        rows = cf.query(f"select rowid as _rid, * from {t}")
        for r in rows:
            cols = [c for c in r if c != "_rid"]
            con.execute(f"insert or replace into {t}(rowid, {', '.join(cols)}) values(?{', ?' * len(cols)})", [r["_rid"]] + [r[c] for c in cols])
    con.commit()


def snapshot(con):
    return {"preds": {(r["game_id"], r["name"]): dict(r) for r in con.execute("select * from preds")},
            "published": {(r["day"], r["game_id"]): dict(r) for r in con.execute("select * from published")},
            "bets": {r["id"]: (r["result"], r["profit"], r["closing_p"], r["clv"]) for r in con.execute("select * from bets")},
            "legs": {r["_rid"]: r["result"] for r in con.execute("select rowid as _rid, result from legs")}}


def insert_many(cf, table, rows):
    """Insere linhas novas em lotes (insert or ignore: chaves primárias evitam duplicados)."""
    if not rows:
        return
    cols = list(rows[0])
    per = max(1, BATCH_PARAMS // len(cols))
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        ph = ", ".join("(" + ", ".join("?" * len(cols)) + ")" for _ in chunk)
        cf.query(f"insert or ignore into {table}({', '.join(cols)}) values {ph}", [r[c] for r in chunk for c in cols])


def push(cf, before, after):
    """Devolve à D1 o que a análise mudou. Devolve quantas alterações enviou."""
    n = 0
    new_preds = [v for k, v in after["preds"].items() if k not in before["preds"]]
    insert_many(cf, "preds", new_preds)
    n += len(new_preds)
    for k, v in after["preds"].items():
        if k in before["preds"] and before["preds"][k]["outcome"] != v["outcome"]:
            cf.query("update preds set outcome=? where game_id=? and name=?", [v["outcome"], k[0], k[1]])
            n += 1
    new_pub = [v for k, v in after["published"].items() if k not in before["published"]]
    insert_many(cf, "published", new_pub)
    n += len(new_pub)
    for k, v in after["published"].items():  # republicado com regras novas (mesmo jogo, aposta diferente)
        if k in before["published"] and before["published"][k] != v:
            cf.query("update published set ord=?, pick=?, published_at=?, version=? where day=? and game_id=?",
                     [v["ord"], v["pick"], v["published_at"], v["version"], k[0], k[1]])
            n += 1
    for k in set(before["published"]) - set(after["published"]):  # já não faz parte do boletim do dia
        cf.query("delete from published where day=? and game_id=?", list(k))
        n += 1
    for bid, v in after["bets"].items():
        if bid in before["bets"] and before["bets"][bid] != v:
            cf.query("update bets set result=?, profit=?, closing_p=?, clv=? where id=?", list(v) + [bid])
            n += 1
    for rid, res in after["legs"].items():
        if rid in before["legs"] and before["legs"][rid] != res:
            cf.query("update legs set result=? where rowid=?", [res, rid])
            n += 1
    return n


def age_cached_files():
    """Os ficheiros vêm do checkout com a hora de agora: envelhecê-los força a atualização das épocas e dos árbitros."""
    old = time.time() - 7 * 86400
    for d in (os.path.join(ROOT, "app", "data"), os.path.join(ROOT, "data", "arbitros")):
        for f in os.listdir(d):
            if f.endswith(".csv"):
                os.utime(os.path.join(d, f), (old, old))


OWNED = ("bets", "legs", "odds")  # tabelas com dono (contas separadas)


def setup_local(cf, tables):
    import server
    server.DB = os.path.join(tempfile.mkdtemp(), "apostas.sqlite")
    con = server.db()
    pull(cf, con, tables)
    return server, con


def user_con(server, src, dono):
    """Cópia só com as apostas de uma conta (dono=None: nenhuma aposta), mais as previsões e boletins de todos."""
    path, old = os.path.join(tempfile.mkdtemp(), "conta.sqlite"), server.DB
    server.DB = path
    con = server.db()
    server.DB = old
    for t in TABLES:
        rows = src.execute(f"select * from {t}" + (" where dono=?" if t in OWNED else ""), (dono,) if t in OWNED else ()).fetchall()
        for r in rows:
            con.execute(f"insert into {t}({', '.join(r.keys())}) values({', '.join('?' * len(r.keys()))})", tuple(r))
    con.commit()
    return con


def owners(cf, con):
    """Contas a servir: quem tem apostas e quem ligou os avisos no telemóvel."""
    found = {r[0] for r in con.execute("select distinct dono from bets where dono is not null")}
    return sorted(found | {k.split(":", 1)[1] for k in cf.kv_keys("ntfy:")})


def send_alerts(cf, server, con, games, now):
    """Avisos ntfy de cada conta: o seu canal, os lances das suas apostas e os seus lembretes."""
    import avisos
    day = now.date().isoformat()
    picks = {r["game_id"].split("|")[0] for r in con.execute("select game_id from published where day=?", (day,))}
    sent, tmp = 0, tempfile.mkdtemp()
    for dono in owners(cf, con):
        cfg = cf.kv_get("ntfy:" + dono)
        if not cfg or not json.loads(cfg).get("ativo"):
            continue
        avisos.CFG, avisos.SEEN = os.path.join(tmp, "cfg.json"), os.path.join(tmp, "vistos.json")
        with open(avisos.CFG, "w", encoding="utf-8") as fh:
            fh.write(cfg)
        with open(avisos.SEEN, "w", encoding="utf-8") as fh:
            fh.write(cf.kv_get("ntfy_vistos:" + dono) or "{}")
        cu = user_con(server, con, dono)
        sent += avisos.run_once(games, server.open_bet_games(cu), picks, server.lembretes(cu, games, now))
        with open(avisos.SEEN, encoding="utf-8") as fh:
            cf.kv_put("ntfy_vistos:" + dono, fh.read())
    return sent


def report(server, con, games):
    return {"aprendizagem": server.learning(con), "odds": server.odds_report(con), "equipas": server.teams_report(con),
            "clv_mercados": server.clv_markets(con), "historico": server.track_record(con, games),
            "precos": server.book_prices(con)}


def live_payload(server, con, games, now):
    """Estado ao vivo para a app; os lembretes vão sem filtro de conta (a app esconde os que já registaste)."""
    state = server.live_state(games, now)
    state["_lembretes"] = server.lembretes(user_con(server, con, None), games, now)
    return state


def completo(cf):
    import live
    server, con = setup_local(cf, list(TABLES))
    age_cached_files()
    before = snapshot(con)
    now = datetime.now(server.TZ)
    agenda = server.agenda(100, now=now)
    warning = server.bets_report(now)["warning"]  # fecha as apostas de todas as contas
    con = server.db()
    after = snapshot(con)
    changed = push(cf, before, after)
    games = server._LAST["games"]
    cf.kv_put("agenda", json.dumps(agenda, ensure_ascii=False))
    cf.kv_put("live", json.dumps(live_payload(server, con, games, now), ensure_ascii=False))
    cf.kv_put("calendario", json.dumps(live.calendario(games, server.LEAGUES, now), ensure_ascii=False))
    extra = {"aviso": warning, "atualizado": now.isoformat()}
    cf.kv_put("relatorio", json.dumps(report(server, user_con(server, con, None), games) | extra, ensure_ascii=False))
    for dono in owners(cf, con):
        cf.kv_put("relatorio:" + dono, json.dumps(report(server, user_con(server, con, dono), games) | extra, ensure_ascii=False))
    sent = send_alerts(cf, server, con, games, now)
    n_bets = con.execute("select count(*) from bets").fetchone()[0]
    print(f"completo: {len(agenda['games'])} jogos · {n_bets} apostas em {len(owners(cf, con))} contas · {changed} alterações na D1 · {sent} avisos")


def aovivo(cf):
    server, con = setup_local(cf, ["bets", "legs", "published", "odds"])
    raw = cf.kv_get("agenda")
    if not raw:
        print("aovivo: ainda sem agenda publicada")
        return
    games = json.loads(raw)["games"]
    now = datetime.now(server.TZ)
    for g in games:  # minutos até ao início, como se a agenda tivesse sido calculada agora
        g["minutes_to_ko"] = round((datetime.fromisoformat(g["kickoff"]) - now).total_seconds() / 60)
    server._LAST["games"] = games
    before = snapshot(con)
    server.settle_pending(con, now, official=False)  # fecha pela ESPN o que já é certo (o oficial fica para a completa)
    con.commit()
    state = live_payload(server, con, games, now)  # antes do envio: as leituras ao intervalo ficam como previsões
    settled = push(cf, before, snapshot(con))
    cf.kv_put("live", json.dumps(state, ensure_ascii=False))
    sent = send_alerts(cf, server, con, games, now)
    print(f"aovivo: {sum(1 for k in state if not k.startswith('_'))} jogos com estado · {settled} apostas fechadas · {sent} avisos")


if __name__ == "__main__":
    from cf import CF
    mode = sys.argv[1] if len(sys.argv) > 1 else "completo"
    {"completo": completo, "aovivo": aovivo}[mode](CF())
