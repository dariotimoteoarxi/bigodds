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
def check_token():
    """Diz em português o que está mal no token, antes de tentar criar coisas."""
    import json, urllib.error, urllib.request
    tok, acc = "".join(os.environ["CLOUDFLARE_API_TOKEN"].split()), "".join(os.environ["CLOUDFLARE_ACCOUNT_ID"].split())
    print(f"token com {len(tok)} caracteres; começa por letra {'maiúscula' if tok[:1].isupper() else 'minúscula' if tok[:1].islower() else 'não-letra'}; "
          f"caracteres fora de [A-Za-z0-9_-]: {sum(1 for c in tok if not (c.isascii() and (c.isalnum() or c in '_-')))}")  # nada disto revela o token
    for path in (f"/accounts/{acc}/tokens/verify", "/user/tokens/verify"):  # tokens de conta e de utilizador
        req = urllib.request.Request("https://api.cloudflare.com/client/v4" + path, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                st = json.load(r)["result"]["status"]
            print(f"token válido ({st})")
            if st != "active":
                sys.exit("O token existe mas não está ativo: cria um novo na Cloudflare.")
            return
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode(errors="replace")
            print(f"verificação {path.split('/')[1]}: {e.code} {body}")  # a resposta da Cloudflare não contém o token
            continue
    sys.exit("A Cloudflare não reconhece o token: o segredo CLOUDFLARE_API_TOKEN não é um token válido (copiado incompleto, "
             "trocado com outro valor, ou o token foi apagado). Cria um token novo e volta a pô-lo no GitHub.")


check_token()
try:
    cf = CF(create=True)
except RuntimeError as e:
    if "Authentication error" in str(e) or " 403 " in str(e):
        sys.exit("O token é válido mas não tem as permissões precisas. No token da Cloudflare confirma: "
                 "Account · D1 · Edit, Account · Workers KV Storage · Edit, Account · Cloudflare Pages · Edit, "
                 "Account · Account Settings · Read, User · User Details · Read; e em Account Resources a tua conta.")
    raise
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
