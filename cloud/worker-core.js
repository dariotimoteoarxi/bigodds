// Bigodds na Cloudflare: o registo de apostas (D1) e os dados publicados pela tarefa do GitHub (KV).
// Mesmas regras do app/server.py (bets_action, bets_report, bets_csv); o cálculo pesado corre no GitHub Actions.
// Plano grátis: 10 ms de CPU por pedido, por isso aqui só há leituras, validação e escritas pequenas.

export const SCHEMA = [
  `create table if not exists bets(id integer primary key, created text, div text, date text, home text,
    away text, kickoff text, sel text, label text, market text, line real, book text, odd real, stake real, p_fair real,
    result text default 'pendente', profit real, closing_p real, clv real, dono text)`,
  `create table if not exists legs(bet_id integer, div text, date text, home text, away text, kickoff text,
    sel text, label text, market text, line real, odd real, p real, result text default 'pendente', dono text)`,
  `create table if not exists preds(game_id text, name text, key text, label text, div text, date text,
    home text, away text, kickoff text, p real, p_raw real, outcome integer, primary key(game_id, name))`,
  `create table if not exists published(day text, game_id text, ord integer, pick text, published_at text,
    version text, primary key(day, game_id))`,
  `create table if not exists odds(ts text, game_id text, sel text, label text, market text, book text,
    odd real, p real, kickoff text, origem text, dono text)`,
];
// bases criadas antes das contas separadas: acrescenta a coluna (o erro "duplicate column" é ignorado)
export const MIGRATIONS = ['alter table bets add column dono text', 'alter table legs add column dono text', 'alter table odds add column dono text'];

const SELS = new Set(['1x2:1', '1x2:X', '1x2:2', 'ou:+2,5', 'ou:-2,5', 'ah:casa', 'ah:fora']);
const ESP_SEL = /^esp:(ht\+0\.5|g2\+0\.5|hs|as|dc|[cy][+-]\d{1,2}\.5|y1[+-]\d\.5|fav)$/;  // y1: amarelos na 1.ª parte
const RESULTS = { ganha: 1, 'meio-ganha': 0.5, anulada: 0, 'meio-perdida': -0.5, perdida: -1 };
const VALUE_MIN = 1.02;
const WON = new Set(['ganha', 'meio-ganha']);

const bad = msg => { const e = new Error(msg); e.status = 400; throw e; };
const num = v => (v === null || v === undefined || v === '' ? NaN : Number(String(v).replace(',', '.')));
const validSel = s => SELS.has(s) || ESP_SEL.test(String(s));
const str = (v, n) => String(v ?? '').slice(0, n);
function checkDate(d) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(d || ''));
  if (!m || +m[2] < 1 || +m[2] > 12 || +m[1] < 1 || +m[1] > 31) bad('Data inválida.');
}
const nowIso = () => new Date().toISOString();

function logOdd(db, dono, gameId, sel, label, market, book, odd, p, kickoff, origem) {
  return db.prepare('insert into odds(ts, game_id, sel, label, market, book, odd, p, kickoff, origem, dono) values(?,?,?,?,?,?,?,?,?,?,?)')
    .bind(nowIso(), gameId, sel, str(label, 80), str(market, 60), book, odd, p ?? null, kickoff, origem, dono);
}

export async function betsAction(db, p, dono) {
  const act = p.action, stmts = [];
  if (act === 'add') {
    const odd = num(p.odd), stk = num(p.stake), book = str(p.book, 30).trim();
    if (!(odd > 1 && stk > 0 && book && validSel(p.sel))) bad('Aposta inválida: confirma a odd, o stake e a casa.');
    checkDate(p.date);
    const line = p.line === null || p.line === undefined || p.line === '' ? null : num(p.line);
    if (String(p.sel).startsWith('ah:') && line === null) bad('Falta a linha do handicap.');
    const pf = p.p_fair ? num(p.p_fair) : null;
    stmts.push(db.prepare(`insert into bets(created, div, date, home, away, kickoff, sel, label, market, line, book, odd, stake, p_fair, dono)
                           values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
      .bind(nowIso(), str(p.div, 5), p.date, str(p.home, 60), str(p.away, 60), str(p.kickoff, 30), p.sel, str(p.label, 80), str(p.market, 60), line, book, odd, stk, pf, dono));
    stmts.push(logOdd(db, dono, `${p.div}-${p.date}-${p.home}`, p.sel, p.label, p.market, book, odd, pf, p.kickoff, 'aposta'));
  } else if (act === 'add_multi') {
    const legs = p.legs || [], stk = num(p.stake), book = str(p.book, 30).trim();
    if (!(legs.length >= 2 && legs.length <= 12 && stk > 0 && book)) bad('Um boletim precisa de 2 a 12 seleções, casa e valor.');
    const clean = legs.map(l => {
      const odd = num(l.odd);
      if (!(odd > 1 && validSel(l.sel))) bad(`Seleção inválida no boletim: ${l.label || '?'} (falta a odd?)`);
      checkDate(l.date);
      return { div: str(l.div, 5), date: l.date, home: str(l.home, 60), away: str(l.away, 60), kickoff: str(l.kickoff, 30), sel: l.sel,
               label: str(l.label, 80), market: str(l.market, 60), line: l.line === null || l.line === undefined || l.line === '' ? null : num(l.line),
               odd, p: l.p ? num(l.p) : null };
    });
    const total = num(p.odd_total) > 1 ? num(p.odd_total) : clean.reduce((a, c) => a * c.odd, 1);
    const pf = clean.every(c => c.p !== null) ? clean.reduce((a, c) => a * c.p, 1) : null;
    const last = clean.reduce((a, c) => (c.kickoff > a.kickoff ? c : a));
    const id = Date.now();  // id explícito: as pernas precisam dele no mesmo lote
    stmts.push(db.prepare(`insert into bets(id, created, div, date, home, away, kickoff, sel, label, market, line, book, odd, stake, p_fair, dono)
                           values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
      .bind(id, nowIso(), last.div, last.date, last.home, last.away, last.kickoff, 'multi',
            (`Boletim de ${clean.length}: ` + clean.map(c => c.label).join(' + ')).slice(0, 220), 'Boletim', null, book,
            Math.round(total * 1000) / 1000, stk, pf, dono));
    for (const c of clean) {
      stmts.push(db.prepare('insert into legs(bet_id, div, date, home, away, kickoff, sel, label, market, line, odd, p, dono) values(?,?,?,?,?,?,?,?,?,?,?,?,?)')
        .bind(id, c.div, c.date, c.home, c.away, c.kickoff, c.sel, c.label, c.market, c.line, c.odd, c.p, dono));
      stmts.push(logOdd(db, dono, `${c.div}-${c.date}-${c.home}`, c.sel, c.label, c.market, book, c.odd, c.p, c.kickoff, 'aposta'));
    }
  } else if (act === 'odd') {
    const odd = num(p.odd), book = str(p.book, 30).trim(), pr = p.p === null || p.p === undefined || p.p === '' ? null : num(p.p);
    if (!(odd > 1 && odd < 100 && book && validSel(p.sel) && (pr === null || (pr > 0 && pr < 1)))) bad('Odd inválida.');
    stmts.push(logOdd(db, dono, str(p.game_id, 80), p.sel, p.label, p.market, book, odd, pr, str(p.kickoff, 30), 'verificação'));
  } else if (act === 'resultado') {
    if (!(p.result in RESULTS)) bad('Resultado inválido.');
    const b = await db.prepare('select * from bets where id=? and dono=?').bind(Number(p.id), dono).first();
    if (!b) bad('Aposta não encontrada.');
    const f = RESULTS[p.result], profit = b.stake * (f > 0 ? f * (b.odd - 1) : f);
    stmts.push(db.prepare('update bets set result=?, profit=? where id=?').bind(p.result, Math.round(profit * 100) / 100, b.id));
  } else if (act === 'apagar') {
    const b = await db.prepare('select id from bets where id=? and dono=?').bind(Number(p.id), dono).first();
    if (!b) bad('Aposta não encontrada.');  // só apagas as tuas
    stmts.push(db.prepare('delete from legs where bet_id=?').bind(b.id), db.prepare('delete from bets where id=?').bind(b.id));
  } else bad('Ação desconhecida.');
  await db.batch(stmts);
  return { ok: true };
}

export async function betsReport(db, kv, dono) {
  const bets = (await db.prepare('select * from bets where dono=? order by kickoff desc, id desc').bind(dono).all()).results;
  const legs = (await db.prepare('select * from legs where dono=? order by kickoff').bind(dono).all()).results;
  for (const b of bets) if (b.sel === 'multi') b.pernas = legs.filter(l => l.bet_id === b.id);
  const done = bets.filter(b => b.result !== 'pendente');
  const staked = done.reduce((s, b) => s + b.stake, 0), profit = done.reduce((s, b) => s + (b.profit || 0), 0);
  const clvs = bets.filter(b => b.clv !== null && b.clv !== undefined).map(b => b.clv), priced = bets.filter(b => b.p_fair);
  const byBook = {};
  for (const b of done) {
    const x = (byBook[b.book] ||= { apostas: 0, investido: 0, lucro: 0 });
    x.apostas++; x.investido += b.stake; x.lucro += b.profit || 0;
  }
  const r4 = x => Math.round(x * 1e4) / 1e4;
  // calculado pela tarefa do GitHub: o teu (as tuas apostas por equipa, odds, CLV) ou, sem apostas fechadas, o geral
  const rel = (await kv.get('relatorio:' + dono, 'json')) || (await kv.get('relatorio', 'json')) || {};
  return {
    dono, bets, warning: rel.aviso || null, aprendizagem: rel.aprendizagem || {}, odds: rel.odds || [], precos: rel.precos || [], equipas: rel.equipas || { equipas: [] },
    clv_mercados: rel.clv_mercados || [], historico: rel.historico || null,
    summary: {
      total: bets.length, pendentes: bets.length - done.length, liquidadas: done.length, investido: Math.round(staked * 100) / 100,
      lucro: Math.round(profit * 100) / 100, roi: staked ? r4(profit / staked) : null,
      clv_medio: clvs.length ? r4(clvs.reduce((a, b) => a + b, 0) / clvs.length) : null, clv_n: clvs.length,
      clv_positivo: clvs.length ? Math.round(clvs.filter(c => c > 0).length / clvs.length * 1000) / 1000 : null,
      acerto: done.length ? Math.round(done.filter(b => (b.profit || 0) > 0).length / done.length * 1000) / 1000 : null,
      com_valor: priced.length ? Math.round(priced.filter(b => b.odd * b.p_fair >= VALUE_MIN).length / priced.length * 1000) / 1000 : null,
      margem_media: priced.length ? r4(priced.reduce((s, b) => s + b.odd * b.p_fair - 1, 0) / priced.length) : null, n_valor: priced.length,
      por_casa: byBook,
    },
  };
}

export async function betsCsv(db, dono) {
  const esc = v => { const s = v === null || v === undefined ? '' : String(v); return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const rows = [['id', 'criada', 'tipo', 'casa', 'jogo', 'inicio', 'selecao', 'mercado', 'odd', 'stake', 'prob_estimada', 'resultado', 'lucro', 'clv']];
  const bets = (await db.prepare('select * from bets where dono=? order by kickoff, id').bind(dono).all()).results;
  const legs = (await db.prepare('select * from legs where dono=? order by kickoff').bind(dono).all()).results;
  for (const b of bets) {
    rows.push([b.id, b.created, b.sel === 'multi' ? 'boletim' : 'simples', b.book, `${b.home} - ${b.away}`, b.kickoff, b.label, b.market, b.odd, b.stake, b.p_fair, b.result, b.profit, b.clv]);
    if (b.sel === 'multi') for (const l of legs.filter(x => x.bet_id === b.id))
      rows.push([b.id, '', 'perna', '', `${l.home} - ${l.away}`, l.kickoff, l.label, l.market, l.odd, '', l.p, l.result, '', '']);
  }
  return '﻿' + rows.map(r => r.map(esc).join(';')).join('\r\n') + '\r\n';
}

function randomTopic() {
  const a = 'abcdefghijklmnopqrstuvwxyz234567', b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return 'bigodds-' + [...b].map(x => a[x % 32]).join('');
}

export async function avisos(kv, dono, body, fetchFn = fetch) {
  const key = 'ntfy:' + dono;  // cada conta tem o seu canal
  const c = (await kv.get(key, 'json')) || { ativo: false, topic: null };
  if (body === undefined) return c;
  if (body.ativo === true && !c.topic) c.topic = randomTopic();
  c.ativo = body.ativo === true;
  await kv.put(key, JSON.stringify(c));
  if (c.ativo && body.teste) {
    try {
      await fetchFn('https://ntfy.sh', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: c.topic, title: 'Bigodds ligado', message: 'A partir de agora recebes aqui as leituras ao vivo, os onzes e os lances das tuas apostas.', tags: ['white_check_mark'] }) });
    } catch (e) { return { ...c, erro: `Não consegui enviar a mensagem de teste: ${e.message}` }; }
  }
  return c;
}

function same(a, b) {  // compara a chave sem dar pistas pelo tempo de resposta
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

// APP_USERS: uma conta por linha (ou separadas por ";"), no formato  Nome:palavra-passe
export function accounts(env) {
  return (env.APP_USERS || '').split(/[;\r\n]+/).map(l => l.trim()).filter(l => l.includes(':'))
    .map(l => ({ nome: l.slice(0, l.indexOf(':')).trim(), chave: l.slice(l.indexOf(':') + 1).trim() })).filter(a => a.nome && a.chave);
}
function whoIs(request, env) {
  const k = request.headers.get('x-bigodds-chave') || '';
  let found = null;
  for (const a of accounts(env)) if (same(k, a.chave)) found = a.nome;  // percorre todas: o tempo não denuncia qual acertou
  return found;
}

const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } });

export async function handle(request, env) {
  const url = new URL(request.url), path = url.pathname.replace(/^\/api\//, '');
  const dono = whoIs(request, env);
  if (!dono) {
    const n = accounts(env).length;  // diz o que falha sem revelar nomes nem palavras-passe
    return json(401, { error: n ? 'Palavra-passe errada. Escreve só a palavra-passe (sem o nome nem os dois pontos).'
                                : 'Não há contas configuradas: o segredo BIGODDS_UTILIZADORES tem de ser Nome:palavra-passe;Nome2:palavra-passe2', contas: n });
  }
  try {
    if (request.method === 'GET') {
      if (path === 'agenda' || path === 'calendario' || path === 'live') {
        const v = await env.KV.get(path);
        return v ? new Response(v, { headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } })
                 : json(503, { error: 'Ainda sem dados: a primeira análise do GitHub corre dentro de 30 minutos.' });
      }
      if (path === 'apostas.csv') return new Response(await betsCsv(env.DB, dono), { headers: { 'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="bigodds-apostas.csv"' } });
      if (path === 'apostas') return json(200, await betsReport(env.DB, env.KV, dono));
      if (path === 'avisos') return json(200, await avisos(env.KV, dono));
      if (path === 'eu') return json(200, { dono });
      return json(404, { error: 'não encontrado' });
    }
    if (request.method === 'POST') {
      if (!(request.headers.get('content-type') || '').startsWith('application/json')) bad('Pedido tem de ser JSON.');
      const text = await request.text();
      if (text.length > 10000) bad('Pedido demasiado grande.');
      const body = JSON.parse(text || '{}');
      if (path === 'apostas') return json(200, await betsAction(env.DB, body, dono));
      if (path === 'avisos') return json(200, await avisos(env.KV, dono, body));
      return json(404, { error: 'não encontrado' });
    }
    return json(405, { error: 'método não suportado' });
  } catch (e) {
    return json(e.status || (e instanceof SyntaxError ? 400 : 502), { error: e.message });
  }
}
