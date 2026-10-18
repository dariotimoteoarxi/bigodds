"""Prepara a Cloudflare (tarefa Publicar do GitHub): cria a base de dados D1 e o espaço KV "bigodds" se faltarem,
aplica as tabelas e escreve o wrangler.toml com os identificadores. Pode correr as vezes que quiseres.
"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cf import CF  # noqa: E402

SCHEMA = [s.strip() for s in open(os.path.join(HERE, "worker-core.js")).read().split("export const SCHEMA = [")[1].split("];")[0].split("`")
          if s.strip().startswith("create")]

MIGRATIONS = re.findall(r"'(alter table [^']+)'", open(os.path.join(HERE, "worker-core.js")).read())
cf = CF(create=True)
for q in SCHEMA:
    cf.query(q)
for q in MIGRATIONS:  # bases antigas, sem a coluna dono
    try:
        cf.query(q)
    except RuntimeError as e:
        if "duplicate column" not in str(e):
            raise
with open(os.path.join(os.path.dirname(HERE), "wrangler.toml"), "w") as fh:
    fh.write(f'''name = "bigodds"
pages_build_output_dir = "app/web"
compatibility_date = "2025-01-01"

[[d1_databases]]
binding = "DB"
database_name = "bigodds"
database_id = "{cf.db}"

[[kv_namespaces]]
binding = "KV"
id = "{cf.kv}"
''')
print("Cloudflare pronta: base de dados, KV e tabelas.")
