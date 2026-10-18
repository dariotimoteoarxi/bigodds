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


def setup_local(cf, tables):
    import avisos, server
    server.DB = os.path.join(tempfile.mkdtemp(), "apostas.sqlite")
    con = server.db()
    pull(cf, con, tables)
    for key, path in (("ntfy", avisos.CFG), ("ntfy_vistos", avisos.SEEN)):
        v = cf.kv_get(key)
        if v:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(v)
    return server, con


def send_alerts(cf, server, con, games, now):
    import avisos
    if not avisos.config().get("ativo"):
        return 0
    day = now.date().isoformat()
    picks = {r["game_id"].split("|")[0] for r in con.execute("select game_id from published where day=?", (day,))}
    sent = avisos.run_once(games, server.open_bet_games(con), picks, server.lembretes(con, games, now))
    with open(avisos.SEEN, encoding="utf-8") as fh:
        cf.kv_put("ntfy_vistos", fh.read())
    return sent


def completo(cf):
    import live
    server, con = setup_local(cf, list(TABLES))
    age_cached_files()
    before = snapshot(con)
    now = datetime.now(server.TZ)
    agenda = server.agenda(100, now=now)
    report = server.bets_report(now)
    after = snapshot(server.db())
    changed = push(cf, before, after)
    games = server._LAST["games"]
    cf.kv_put("agenda", json.dumps(agenda, ensure_ascii=False))
    cf.kv_put("live", json.dumps(server.live_state(games, now), ensure_ascii=False))
    cf.kv_put("calendario", json.dumps(live.calendario(games, server.LEAGUES, now), ensure_ascii=False))
    cf.kv_put("relatorio", json.dumps({k: report[k] for k in ("aprendizagem", "odds", "equipas", "clv_mercados", "historico")}
                                      | {"aviso": report.get("warning"), "atualizado": now.isoformat()}, ensure_ascii=False))
    sent = send_alerts(cf, server, server.db(), games, now)
    print(f"completo: {len(agenda['games'])} jogos · {changed} alterações na D1 · {sent} avisos")


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
    state = server.live_state(games, now)
    cf.kv_put("live", json.dumps(state, ensure_ascii=False))
    sent = send_alerts(cf, server, con, games, now)
    print(f"aovivo: {sum(1 for k in state if not k.startswith('_'))} jogos com estado · {sent} avisos")


if __name__ == "__main__":
    from cf import CF
    mode = sys.argv[1] if len(sys.argv) > 1 else "completo"
    {"completo": completo, "aovivo": aovivo}[mode](CF())
