"""Cliente mínimo da API da Cloudflare (D1 e KV), só com Python de base.

Precisa de CLOUDFLARE_API_TOKEN e CLOUDFLARE_ACCOUNT_ID no ambiente. A base de dados e o espaço KV chamam-se
"bigodds" e são encontrados pelo nome, por isso não há identificadores a copiar à mão.
"""
import json, os, urllib.error, urllib.parse, urllib.request

API = "https://api.cloudflare.com/client/v4"
NAME = "bigodds"


class CF:
    def __init__(self, token=None, account=None, create=False):
        self.token = "".join((token or os.environ["CLOUDFLARE_API_TOKEN"]).split())  # espaços ou linhas a mais ao colar
        self.acc = "".join((account or os.environ["CLOUDFLARE_ACCOUNT_ID"]).split())
        self.db = self._find_db(create)
        self.kv = self._find_kv(create)

    def _req(self, method, path, body=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == "GET":
                return None
            raise RuntimeError(f"Cloudflare {method} {path.split('?')[0]}: {e.code} {e.read()[:300]!r}") from None

    def _json(self, method, path, body=None):
        out = json.loads(self._req(method, path, body) or b"{}")
        if not out.get("success", True):
            raise RuntimeError(f"Cloudflare: {out.get('errors')}")
        return out.get("result")

    def _find_db(self, create):
        found = [d for d in self._json("GET", f"/accounts/{self.acc}/d1/database?name={NAME}") or [] if d.get("name") == NAME]
        if found:
            return found[0]["uuid"]
        if not create:
            raise RuntimeError("Não encontrei a base de dados 'bigodds' na Cloudflare: corre primeiro a tarefa Publicar.")
        return self._json("POST", f"/accounts/{self.acc}/d1/database", {"name": NAME})["uuid"]

    def _find_kv(self, create):
        found = [n for n in self._json("GET", f"/accounts/{self.acc}/storage/kv/namespaces?per_page=100") or [] if n.get("title") == NAME]
        if found:
            return found[0]["id"]
        if not create:
            raise RuntimeError("Não encontrei o espaço KV 'bigodds' na Cloudflare: corre primeiro a tarefa Publicar.")
        return self._json("POST", f"/accounts/{self.acc}/storage/kv/namespaces", {"title": NAME})["id"]

    def query(self, sql, params=()):
        res = self._json("POST", f"/accounts/{self.acc}/d1/database/{self.db}/query", {"sql": sql, "params": list(params)})
        return (res or [{}])[0].get("results") or []

    def kv_get(self, key):
        raw = self._req("GET", f"/accounts/{self.acc}/storage/kv/namespaces/{self.kv}/values/{urllib.parse.quote(key)}")
        return raw.decode() if raw is not None else None

    def kv_keys(self, prefix):
        res = self._json("GET", f"/accounts/{self.acc}/storage/kv/namespaces/{self.kv}/keys?prefix={urllib.parse.quote(prefix)}&limit=1000")
        return [k["name"] for k in res or []]

    def kv_put(self, key, value):
        self._req("PUT", f"/accounts/{self.acc}/storage/kv/namespaces/{self.kv}/values/{urllib.parse.quote(key)}",
                  raw=value.encode(), ctype="text/plain; charset=utf-8")
