"""Teste da tarefa do GitHub contra uma Cloudflare falsa (SQLite + dicionário), com uma cópia das apostas locais.
Uso: python3 cloud/test_sync.py   (precisa de rede: vai buscar jogos e placares como a tarefa real)
"""
import json, os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
import sync  # noqa: E402

SCHEMA = [s.strip() for s in open(os.path.join(HERE, "worker-core.js")).read().split("export const SCHEMA = [")[1].split("];")[0].split("`") if s.strip().startswith("create")]


class FakeCF:
    def __init__(self, seed):
        self.d1 = sqlite3.connect(":memory:")
        self.d1.row_factory = sqlite3.Row
        for q in SCHEMA:
            self.d1.execute(q)
        src = sqlite3.connect(seed)
        src.row_factory = sqlite3.Row
        for t in sync.TABLES:
            for r in src.execute(f"select * from {t}"):
                self.d1.execute(f"insert into {t}({', '.join(r.keys())}) values({', '.join('?' * len(r.keys()))})", tuple(r))
        self.kv, self.calls = {}, 0

    def query(self, sql, params=()):
        self.calls += 1
        assert len(params) <= 100, "a D1 só aceita 100 parâmetros"
        cur = self.d1.execute(sql, params)
        self.d1.commit()
        return [dict(r) for r in cur.fetchall()] if cur.description else []

    def kv_get(self, k):
        return self.kv.get(k)

    def kv_keys(self, prefix):
        return [k for k in self.kv if k.startswith(prefix)]

    def kv_put(self, k, v):
        assert isinstance(v, str)
        self.kv[k] = v


cf = FakeCF(os.path.join(os.path.dirname(HERE), "app", "data", "apostas.sqlite"))
for t in ("bets", "legs", "odds"):
    cf.query(f"update {t} set dono='Dário'")  # como depois do migrar.py
cf.query("insert into bets(created, div, date, home, away, kickoff, sel, label, market, book, odd, stake, dono) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
         ["2026-10-18T10:00", "SP1", "18/10/2026", "Real Madrid", "Sevilla", "2026-10-18T20:00:00+01:00", "1x2:1", "Real Madrid ganha", "Resultado (1X2)", "Betclic", 1.3, 2, "Ana"])
cf.kv["ntfy:Ana"] = json.dumps({"ativo": True, "topic": "bigodds-teste"})
import avisos  # noqa: E402
sent_to = []
avisos.send = lambda t, b, tags="": sent_to.append(avisos.config()["topic"]) or True  # nada sai para a internet no teste
n_bets = cf.query("select count(*) n from bets")[0]["n"]
cf.query("delete from preds where date like '18/10/2026'")  # força previsões novas a voltar para a D1
sync.completo(cf)
assert {"agenda", "live", "calendario", "relatorio"} <= set(cf.kv), cf.kv.keys()
ag = json.loads(cf.kv["agenda"])
assert ag["games"] and "selecao" in ag
assert cf.query("select count(*) n from preds")[0]["n"] > 0
assert cf.query("select count(*) n from bets")[0]["n"] == n_bets  # a tarefa nunca cria nem apaga apostas
rel = json.loads(cf.kv["relatorio"])
assert {"aprendizagem", "equipas", "historico"} <= set(rel)
assert "relatorio:Dário" in cf.kv and "relatorio:Ana" in cf.kv
eq = lambda k: {x["equipa"]: x for x in json.loads(cf.kv[k])["equipas"]["equipas"]}
assert "Real Madrid" in eq("relatorio:Ana") and eq("relatorio:Ana")["Real Madrid"]["apostas"]["n"] in (0, 1)  # 1 se a ESPN já deu o jogo como terminado
assert all(x["apostas"]["n"] == 0 for x in eq("relatorio").values())  # o geral não tem apostas de ninguém
assert "ntfy_vistos:Ana" in cf.kv and "ntfy_vistos:Dário" not in cf.kv  # só quem ligou os avisos
assert set(sent_to) <= {"bigodds-teste"}
sync.aovivo(cf)
assert "_lembretes" in json.loads(cf.kv["live"])
print("sync ok ·", cf.calls, "pedidos à D1")
if len(sys.argv) > 1:  # guarda o resultado para o servidor de ensaio (cloud/ensaio.mjs)
    json.dump(cf.kv, open(sys.argv[1] + ".kv.json", "w"), ensure_ascii=False)
    out = sqlite3.connect(sys.argv[1] + ".d1.sqlite")
    cf.d1.backup(out)
    out.close()
