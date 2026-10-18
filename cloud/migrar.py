"""Leva as tuas apostas do PC para a Cloudflare (uma vez, depois da primeira tarefa Publicar).

  export CLOUDFLARE_API_TOKEN=...   (o mesmo token que puseste no GitHub)
  export CLOUDFLARE_ACCOUNT_ID=...
  python3 cloud/migrar.py
"""
import json, os, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cf import CF  # noqa: E402
from sync import TABLES, insert_many  # noqa: E402

LOCAL = os.path.join(os.path.dirname(HERE), "app", "data", "apostas.sqlite")
cf = CF()
if cf.query("select count(*) n from bets")[0]["n"] and "--forcar" not in sys.argv:
    sys.exit("A Cloudflare já tem apostas: não migro outra vez (para não duplicar). Usa --forcar se tens a certeza.")
src = sqlite3.connect(LOCAL)
src.row_factory = sqlite3.Row
for t in TABLES:
    rows = [dict(r) for r in src.execute(f"select * from {t}")]
    insert_many(cf, t, rows)
    print(f"{t}: {len(rows)} linhas")
cfg = os.path.join(os.path.dirname(HERE), "app", "data", "ntfy.json")
if os.path.exists(cfg):
    cf.kv_put("ntfy", open(cfg).read())
    print("avisos do telemóvel: configuração copiada")
print("Migração feita. A partir de agora usa só o endereço da Cloudflare.")
