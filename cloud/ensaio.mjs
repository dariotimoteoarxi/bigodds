// Ensaio local da versão Cloudflare (sem conta): páginas de app/web + /api do worker com D1 e KV a partir de ficheiros.
//   python3 cloud/test_sync.py /tmp/x   (cria /tmp/x.kv.json e /tmp/x.d1.sqlite)
//   node cloud/ensaio.mjs /tmp/x 8788
import http from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { handle } from './worker-core.js';

const [base, port = '8788'] = process.argv.slice(2);
const s = new DatabaseSync(base + '.d1.sqlite');
const stmt = (sql, args = []) => ({ bind: (...a) => stmt(sql, a), all: async () => ({ results: s.prepare(sql).all(...args) }),
  first: async () => s.prepare(sql).get(...args) ?? null, run: async () => s.prepare(sql).run(...args) });
const DB = { prepare: sql => stmt(sql), batch: async l => { for (const x of l) await x.run(); } };
const kv = JSON.parse(readFileSync(base + '.kv.json', 'utf8'));
const KV = { get: async (k, t) => (k in kv ? (t === 'json' ? JSON.parse(kv[k]) : kv[k]) : null), put: async (k, v) => { kv[k] = v; } };
const env = { DB, KV, APP_KEY: 'ensaio' };
const WEB = fileURLToPath(new URL('../app/web/', import.meta.url));  // o caminho tem acentos
const TYPES = { '.html': 'text/html; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.js': 'text/javascript' };

http.createServer(async (req, res) => {
  if (req.url.startsWith('/api/')) {
    const chunks = []; for await (const c of req) chunks.push(c);
    const r = await handle(new Request('http://localhost' + req.url, { method: req.method, headers: req.headers, body: chunks.length ? Buffer.concat(chunks) : undefined }), env);
    res.writeHead(r.status, Object.fromEntries(r.headers)); res.end(Buffer.from(await r.arrayBuffer())); return;
  }
  const f = join(WEB, normalize(req.url.split('?')[0] === '/' ? 'index.html' : req.url.split('?')[0]).replace(/^(\.\.[/\\])+/, ''));
  if (!f.startsWith(WEB) || !existsSync(f)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'Content-Type': TYPES[extname(f)] || 'application/octet-stream' }); res.end(readFileSync(f));
}).listen(+port, '127.0.0.1', () => console.log(`Ensaio Cloudflare em http://127.0.0.1:${port} (palavra-passe: ensaio)`));
