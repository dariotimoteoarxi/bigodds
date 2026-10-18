// Teste do worker com uma D1 e uma KV falsas (SQLite do Node e um Map): node cloud/test-worker.mjs
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { SCHEMA, handle } from './worker-core.js';

function fakeD1() {
  const s = new DatabaseSync(':memory:');
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, a),
    all: async () => ({ results: s.prepare(sql).all(...args) }),
    first: async () => s.prepare(sql).get(...args) ?? null,
    run: async () => s.prepare(sql).run(...args),
  });
  return { prepare: sql => stmt(sql), batch: async list => { s.exec('begin'); try { for (const x of list) await x.run(); s.exec('commit'); } catch (e) { s.exec('rollback'); throw e; } }, raw: s };
}
const kvMap = new Map();
const KV = { get: async (k, t) => (kvMap.has(k) ? (t === 'json' ? JSON.parse(kvMap.get(k)) : kvMap.get(k)) : null), put: async (k, v) => kvMap.set(k, v) };
const DB = fakeD1();
for (const q of SCHEMA) DB.raw.exec(q);
const env = { DB, KV, APP_KEY: 'segredo-de-teste' };
const call = (method, path, body, key = 'segredo-de-teste') => handle(new Request('https://x.pages.dev/api/' + path, {
  method, headers: { 'x-bigodds-chave': key, ...(body ? { 'content-type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined }), env);

assert.equal((await call('GET', 'apostas', null, 'errada')).status, 401);
assert.equal((await call('GET', 'agenda')).status, 503);
kvMap.set('agenda', '{"games":[]}');
assert.deepEqual(await (await call('GET', 'agenda')).json(), { games: [] });

const jogo = { div: 'P1', date: '19/10/2026', home: 'Sp Braga', away: 'Gil Vicente', kickoff: '2026-10-19T20:15:00+01:00' };
assert.equal((await call('POST', 'apostas', { action: 'add', ...jogo, sel: '1x2:1', label: 'Sp Braga ganha', market: 'Resultado (1X2)', book: 'Betclic', odd: '1.90', stake: '10', p_fair: '0.55' })).status, 200);
for (const badv of [{ odd: '1.0' }, { stake: '0' }, { sel: 'outra' }, { book: '' }, { date: '32/13/2026' }])
  assert.equal((await call('POST', 'apostas', { action: 'add', ...jogo, sel: '1x2:1', book: 'Betclic', odd: '2', stake: '1', ...badv })).status, 400, JSON.stringify(badv));
const L = (o, x) => ({ ...jogo, sel: 'esp:y-4.5', label: 'Menos de 4,5 amarelos', market: 'Cartões', odd: o, p: '0.8', ...x });
assert.equal((await call('POST', 'apostas', { action: 'add_multi', legs: [L('1.3'), L('1.2', { home: 'Porto', away: 'Arouca' })], stake: '5', book: '22bet' })).status, 200);
assert.equal((await call('POST', 'apostas', { action: 'add_multi', legs: [L('1.3')], stake: '5', book: '22bet' })).status, 400);
assert.equal((await call('POST', 'apostas', { action: 'odd', game_id: 'g', sel: 'esp:y-4.5', book: '22bet', odd: '1.25', p: '0.8' })).status, 200);
assert.equal((await call('POST', 'apostas', { action: 'odd', game_id: 'g', sel: 'esp:y-4.5', book: '22bet', odd: '1.25', p: '1.5' })).status, 400);

let r = await (await call('GET', 'apostas')).json();
const multi = r.bets.find(b => b.sel === 'multi'), single = r.bets.find(b => b.sel === '1x2:1');
assert.equal(multi.pernas.length, 2);
assert.equal(multi.odd, 1.56);
assert.ok(Math.abs(multi.p_fair - 0.64) < 1e-9);
assert.equal(r.summary.total, 2);
assert.equal(r.summary.n_valor, 2);
assert.equal(DB.raw.prepare('select count(*) n from odds').get().n, 4);  // 1 simples + 2 pernas + 1 verificação

assert.equal((await call('POST', 'apostas', { action: 'resultado', id: single.id, result: 'ganha' })).status, 200);
r = await (await call('GET', 'apostas')).json();
assert.equal(r.summary.lucro, 9);
assert.equal(r.summary.liquidadas, 1);
const raw = new Uint8Array(await (await call('GET', 'apostas.csv')).arrayBuffer()), csv = new TextDecoder().decode(raw);  // o decoder tira o BOM
assert.deepEqual([...raw.slice(0, 3)], [0xef, 0xbb, 0xbf]);
assert.ok(csv.startsWith('id;criada;tipo') && csv.includes('perna') && csv.includes('Porto - Arouca'));
assert.equal((await call('POST', 'apostas', { action: 'apagar', id: multi.id })).status, 200);
assert.equal(DB.raw.prepare('select count(*) n from legs').get().n, 0);
assert.equal((await call('POST', 'apostas', '{nope')).status, 400);

let sent = null;
const { avisos } = await import('./worker-core.js');
const c = await avisos(KV, { ativo: true, teste: true }, async (u, o) => { sent = JSON.parse(o.body); });
assert.ok(c.ativo && /^bigodds-[a-z2-7]{16}$/.test(c.topic) && sent.topic === c.topic);
assert.deepEqual(await (await call('GET', 'avisos')).json(), c);
console.log('worker ok');
