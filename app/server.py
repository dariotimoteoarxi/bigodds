"""Bigodds local: consultor de apostas no browser.

Correr:  python3 server.py   e abrir http://localhost:8765
Só usa Python de base e dados públicos sem conta (football-data.co.uk/fixtures.csv).
"""
import csv, json, math, os, re, sqlite3, time, urllib.request
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from zoneinfo import ZoneInfo

import threading

import arbitros, avisos, live as aovivo, onzes
from consultor import PICK_MIN, ah_ret, analysis, dec, especialista, load_cal, make_boletins, selecao, selecao_especialista

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"
CACHE = os.path.join(HERE, "fixtures.csv")
LEAGUES = {"E0": "Premier League", "SP1": "La Liga", "I1": "Serie A", "D1": "Bundesliga", "F1": "Ligue 1", "P1": "Liga Portugal"}
BOOKS = {"B365": "Bet365", "BFD": "Betfred", "BV": "BetVictor", "BW": "Bwin", "PP": "Paddy Power", "SKB": "Sky Bet"}
TZ = ZoneInfo("Europe/Lisbon")  # o football-data usa hora do Reino Unido, igual à de Portugal
MIN_EDGE = 0.02   # vantagem mínima sobre o preço justo (backtest: CLV +3% a partir de 2%)
MAX_ODD = 3.5     # acima disto o viés favorito/outsider come o valor
LINEUP_MIN = 75   # os onzes saem ~75 min antes do início
LIVE_WINDOW = 150  # jogos começados ficam na lista até ~2,5 h depois do início


def fair_power(odds):
    """Probabilidades justas pelo método de potência: p_i = (1/o_i)^k com soma 1."""
    q = [1 / o for o in odds]
    lo, hi = 1.0, 3.0
    for _ in range(50):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if sum(x ** k for x in q) > 1 else (lo, k)
    k = (lo + hi) / 2
    return [x ** k for x in q]


def stake(p, odd, bank, cap=0.02):
    """Kelly a 1/4 com teto de 2% da banca."""
    f = (p * odd - 1) / (odd - 1) / 4
    return round(max(0.0, min(f, cap)) * bank, 2)


def num(row, key):
    try:
        v = float(row.get(key) or "")
        return v if v > 1 else None
    except ValueError:
        return None


def line_txt(x):
    return "0" if x == 0 else f"{x:+g}".replace(".", ",")


def market(row, key, title, sels, ref_cols, books):
    """Avalia um mercado. sels: [(id, nome, sufixo)]; books: {nome: prefixo}; preço justo da Betfair (ou média)."""
    ref, ref_name = [num(row, c.format("BFE")) for c in ref_cols], "Betfair Exchange"
    if None in ref:
        ref, ref_name = [num(row, c.format("Avg")) for c in ref_cols], "média do mercado"
    if None in ref:
        return None
    fair = fair_power(ref)
    out = []
    for i, (sid, label, col) in enumerate(sels):
        offers = sorted(((num(row, col.format(p)), name) for name, p in books.items() if num(row, col.format(p))), reverse=True)
        best_odd, best_book = offers[0] if offers else (None, None)
        edge = best_odd * fair[i] - 1 if best_odd else None
        max_odd = num(row, col.format("Max"))
        out.append({"sel": f"{key}:{sid}", "short": sid, "label": label, "market": title, "p": round(fair[i], 4),
                    "fair_odd": round(1 / fair[i], 2), "min_odd": round((1 + MIN_EDGE) / fair[i], 2),
                    "best_odd": best_odd, "best_book": best_book, "edge": round(edge, 4) if edge is not None else None,
                    "offers": [{"book": n, "odd": o} for o, n in offers]
                              + ([{"book": "Melhor odd do mercado", "odd": max_odd, "info": True}] if max_odd else [])})
    return {"key": key, "title": title, "ref_name": ref_name, "selections": out}


def analyse(row, bank, now):
    ko = datetime.strptime(f"{row['Date']} {row['Time']}", "%d/%m/%Y %H:%M").replace(tzinfo=TZ)
    home, away = row["HomeTeam"], row["AwayTeam"]
    one_x_two = {name: b for b, name in BOOKS.items()}
    mkts = [market(row, "1x2", "Resultado (1X2)",
                   [("1", home, "{}H"), ("X", "Empate", "{}D"), ("2", away, "{}A")],
                   ["{}H", "{}D", "{}A"], one_x_two),
            market(row, "ou", "Golos 2,5",
                   [("+2,5", "Mais de 2,5 golos", "{}>2.5"), ("-2,5", "Menos de 2,5 golos", "{}<2.5")],
                   ["{}>2.5", "{}<2.5"], {"Bet365": "B365"})]
    try:
        line = float(row.get("AHh") or "")  # não usa num(): a linha pode ser 0 ou negativa
    except ValueError:
        line = None
    if line is not None:
        ah = market(row, "ah", f"Handicap asiático ({line_txt(line)})",
                    [("casa", f"{home} {line_txt(line)}", "{}AHH"), ("fora", f"{away} {line_txt(-line)}", "{}AHA")],
                    ["{}AHH", "{}AHA"], {"Bet365": "B365"})
        if ah:
            ah["line"] = line
        mkts.append(ah)
    mkts = [m for m in mkts if m]
    if not mkts:
        return None
    sels = [s for m in mkts for s in m["selections"]]
    ok = [x for x in sels if x["edge"] is not None and x["edge"] >= MIN_EDGE and x["best_odd"] <= MAX_ODD]
    mins = (ko - now).total_seconds() / 60
    if ok:
        pick = max(ok, key=lambda x: x["edge"])
        pick["stake"] = stake(pick["p"], pick["best_odd"], bank)
        verdict = "entrar" if mins <= LINEUP_MIN else "esperar"
        reason = (f"{pick['best_book']} paga {dec(pick['best_odd'], '.2')} em {pick['label']} ({pick['market']}), "
                  f"acima do justo {dec(pick['fair_odd'], '.2')} (+{dec(pick['edge'] * 100, '.1')}%).")
    else:
        pick = None
        verdict = "nao"
        best = max((x for x in sels if x["edge"] is not None), key=lambda x: x["edge"], default=None)
        reason = ("Nenhuma casa paga acima do preço justo." if not best or best["edge"] < 0 else
                  f"Melhor vantagem só {dec(best['edge'] * 100, '+.1')}% ({best['label']})." if best["edge"] < MIN_EDGE else
                  f"Valor só em odd alta ({best['label']} a {dec(best['best_odd'], '.2')}): zona de outsider, excluída.")
    mk = {}
    q = [num(row, c) for c in ("AvgH", "AvgD", "AvgA")]
    if None not in q:
        s3 = sum(1 / x for x in q)
        mk.update(pH=1 / q[0] / s3, pD=1 / q[1] / s3, pA=1 / q[2] / s3)
    q = [num(row, c) for c in ("Avg>2.5", "Avg<2.5")]
    if None not in q:
        mk["po"] = (1 / q[0]) / (1 / q[0] + 1 / q[1])
    return {"id": f"{row['Div']}-{row['Date']}-{home}", "league": LEAGUES[row["Div"]], "div": row["Div"], "mk": mk,
            "kickoff": ko.isoformat(), "date": row["Date"], "home": home, "away": away, "referee": row.get("Referee") or None,
            "markets": mkts, "pick": pick, "verdict": verdict, "reason": reason, "minutes_to_ko": round(mins)}


def load_fixtures(force=False):
    if force or not os.path.exists(CACHE) or time.time() - os.path.getmtime(CACHE) > 3600:
        with urllib.request.urlopen(FIXTURES_URL, timeout=30) as r:
            data = r.read()
        with open(CACHE, "wb") as f:
            f.write(data)
    with open(CACHE, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f)), datetime.fromtimestamp(os.path.getmtime(CACHE), TZ)


GAP_ALERTA = 0.10  # o mercado acredita no favorito 10+ pontos acima dos números da época


def alerta(g):
    """Grande equipa em má forma: o mercado confia no favorito muito acima do que a época mostra.

    Backtest 2021/22–2025/26 (835 jogos): o favorito ganhou 67,5% contra 63,6% previstos no fecho e 61,2% na
    abertura, acima do mercado em 4 de 5 épocas. Sinal em observação.
    """
    an = g.get("analise")
    mk = {s["sel"]: s for m in g["markets"] for s in m["selections"]}
    if not an or "1x2:1" not in mk or "1x2:2" not in mk:
        return None
    side = "1x2:1" if mk["1x2:1"]["p"] >= mk["1x2:2"]["p"] else "1x2:2"
    p_mkt, p_mod = mk[side]["p"], an["model"]["p"][side]
    if p_mkt < 0.5 or p_mkt - p_mod < GAP_ALERTA:
        return None
    team = g["home"] if side == "1x2:1" else g["away"]
    return {"equipa": team, "p_mercado": round(p_mkt, 3), "p_epoca": round(p_mod, 3),
            "texto": f"Os números da época dão a {team} só {int(p_mod * 100 + 0.5)}% de vitória, mas o mercado dá-lhe "
                     f"{int(p_mkt * 100 + 0.5)}%. Em 835 casos assim, o favorito ganhou 67,5%, mais do que o mercado previa. "
                     f"Não apostes contra {team}; se quiseres entrar, é a favor e cedo, porque a odd tende a baixar até ao jogo.",
            "estado": "em observação"}


def agenda(bank, force=False, now=None):
    rows, fetched = load_fixtures(force)
    now = now or datetime.now(TZ)
    games = [g for r in rows if r.get("Div") in LEAGUES
             for g in [analyse(r, bank, now)] if g and g["minutes_to_ko"] > -LIVE_WINDOW]
    games.sort(key=lambda g: g["kickoff"])
    notes = {}
    try:
        with open(NOTES, encoding="utf-8") as fh:
            notes = json.load(fh)
    except (OSError, ValueError):
        pass
    seasons, warning = {}, None
    cal, con, noms = load_cal(), db(), {}
    try:
        settle_preds(con, now)
    except Exception:
        pass  # sem rede: aprende na próxima vez
    live = {k: v["ajuste"] for k, v in learning(con).items()}
    for g in games:
        try:
            cur = season_of(g["date"])
            prev = f"{int(cur[:2]) - 1:02d}{cur[:2]}"
            for s in (cur, prev):
                if (g["div"], s) not in seasons:
                    seasons[(g["div"], s)] = season_rows(g["div"], s)
            g["analise"] = analysis(g, seasons[(g["div"], cur)], seasons[(g["div"], prev)], bank)
            rows_lg = seasons[(g["div"], prev)] + seasons[(g["div"], cur)]
            if g["div"] in ("P1", "I1"):  # árbitros: nomeações oficiais (Liga Portugal, Lega Serie A) ligadas aos jogos
                if g["div"] not in noms:
                    try:
                        arbitros.refresh(now, g["div"])
                    except Exception:
                        pass  # sem rede: usa o que já está guardado
                    noms[g["div"]] = arbitros.load(g["div"])
                arbitros.attach(rows_lg, noms[g["div"]])
                g["referee"] = g.get("referee") or arbitros.referee_for(arbitros._index(noms[g["div"]]), g["kickoff"][:10], g["home"])
            g["especialista"] = especialista(g, rows_lg, cal, live)
            if g["minutes_to_ko"] > 0:
                con.executemany("insert or ignore into preds(game_id, name, key, label, div, date, home, away, kickoff, p, p_raw) values(?,?,?,?,?,?,?,?,?,?,?)",
                                [(g["id"], o["name"], o["key"], o["label"], g["div"], g["date"], g["home"], g["away"], g["kickoff"], o["p"], o["p_raw"])
                                 for o in g["especialista"]])
        except Exception as e:  # sem histórico não há leitura, mas o preço continua a valer
            g["analise"], warning = None, f"Sem dados da época para a análise: {e}"
        g["nota"] = notes.get(g["id"])
        g["alerta"] = alerta(g)
        if g["alerta"] and g["minutes_to_ko"] > 0:  # o alerta também é medido: o favorito ganha acima do mercado?
            con.execute("insert or ignore into preds(game_id, name, key, label, div, date, home, away, kickoff, p, p_raw) values(?,?,?,?,?,?,?,?,?,?,?)",
                        (g["id"], "Atenção: favorito subvalorizado", "fav", f"{g['alerta']['equipa']} ganha", g["div"], g["date"],
                         g["home"], g["away"], g["kickoff"], g["alerta"]["p_mercado"], g["alerta"]["p_mercado"]))
        op = (g["analise"] or {}).get("opinion")
        if g["verdict"] == "nao" and op:
            g["verdict"] = "opiniao"
            g["reason"] = (f"Leitura do modelo: {op['label']} ({op['market']}) a {dec(op['odd'], '.2')} na {op['book']}; "
                           f"modelo {dec(op['p_model'] * 100, '.0')}% contra mercado {dec(op['p_market'] * 100, '.0')}%.")
    con.commit()
    _LAST["games"] = games
    live_state(games, now)
    selecao(games, now.date().isoformat())  # mantém acerto e confiança em todos os mercados de preço
    sel = publish(con, selecao_especialista(games, now.date().isoformat()), games, now)
    # todos os jogos da lista, mesmo os já começados: servem para ler boletins por foto
    todos = []
    for r in rows:
        if r.get("Div") in LEAGUES:
            try:
                ko = datetime.strptime(f"{r['Date']} {r['Time']}", "%d/%m/%Y %H:%M").replace(tzinfo=TZ)
            except ValueError:
                continue
            todos.append({"id": f"{r['Div']}-{r['Date']}-{r['HomeTeam']}", "div": r["Div"], "date": r["Date"],
                          "kickoff": ko.isoformat(), "home": r["HomeTeam"], "away": r["AwayTeam"], "league": LEAGUES[r["Div"]]})
    return {"fetched": fetched.isoformat(), "source": FIXTURES_URL, "games": games, "todos": todos, "risco": risco(games, now, paused={c["mercado"] for c in clv_markets(con) if c["pausa"]}), "warning": warning, "selecao": sel, "aprendizagem": learning(con),
            "rules": {"min_edge": MIN_EDGE, "max_odd": MAX_ODD, "lineup_min": LINEUP_MIN}}


RISK_ODDS = (1.80, 2.50)  # valor_risco.py: margem ≥2% nestas odds deu ROI +19,5% e CLV +3,9% (42 apostas, 2021/22–2025/26)


CLV_MIN_N, CLV_PAUSE = 30, -0.02  # com 30+ apostas fechadas, CLV médio abaixo de −2% põe o mercado em pausa


def clv_markets(con):
    """CLV por mercado das tuas apostas simples (1X2, golos 2,5, handicap: os únicos com odd de fecho pública)."""
    out = {}
    for r in con.execute("select market, clv from bets where clv is not null"):
        m = r["market"].split(" (")[0]  # "Handicap asiático (−0,75)" e "(+0,5)" contam como o mesmo mercado
        x = out.setdefault(m, {"mercado": m, "n": 0, "soma": 0.0, "pos": 0})
        x["n"] += 1
        x["soma"] += r["clv"]
        x["pos"] += r["clv"] > 0
    return [{"mercado": x["mercado"], "n": x["n"], "clv": round(x["soma"] / x["n"], 4), "positivo": round(x["pos"] / x["n"], 3),
             "pausa": x["n"] >= CLV_MIN_N and x["soma"] / x["n"] < CLV_PAUSE} for x in out.values()]


def risco(games, now, n=6, paused=()):
    """Apostas de maior risco: preço justo (Betfair ou média) com odd mínima entre 1,80 e 2,50, ordenadas pela margem."""
    out = []
    for g in games:
        if not (0 < g["minutes_to_ko"] <= 48 * 60):
            continue
        for m in g["markets"]:
            if m.get("title", "").split(" (")[0] in paused:
                continue  # o teu CLV neste mercado está negativo: pausa até mudar
            for x in m["selections"]:
                if RISK_ODDS[0] <= x["min_odd"] <= RISK_ODDS[1]:
                    out.append({"game_id": g["id"], "home": g["home"], "away": g["away"], "kickoff": g["kickoff"], "league": g["league"],
                                "sel": x["sel"], "label": x["label"], "market": x["market"], "p": x["p"], "min_odd": x["min_odd"],
                                "fair_odd": x["fair_odd"], "best_odd": x["best_odd"], "best_book": x["best_book"], "edge": x["edge"],
                                "valor": bool(x["edge"] is not None and x["edge"] >= MIN_EDGE),
                                "stake": stake(x["p"], max(x["best_odd"] or 0, x["min_odd"]), 100, cap=0.01)})
    out.sort(key=lambda x: (not x["valor"], -(x["edge"] if x["edge"] is not None else -1)))
    return out[:n]


REMIND_MIN = 30  # lembrete: falta meia hora e a aposta com valor ainda não está registada


def lembretes(con, games, now):
    """Apostas com valor a ≤30 min do início que ainda não registaste: as do dia, as de risco com valor confirmado
    e as odds que verificaste e tinham valor."""
    reg = {(f"{r['div']}-{r['date']}-{r['home']}", r["sel"]) for r in
           con.execute("select div, date, home, sel from bets where sel != 'multi' union all select div, date, home, sel from legs")}
    cands = [(p["game_id"], p["sel"], p["label"], p["p"], p["min_odd"], "aposta do dia")
             for p in (json.loads(r["pick"]) for r in con.execute("select pick from published where day=?", (now.date().isoformat(),)))]
    cands += [(x["game_id"], x["sel"], x["label"], x["p"], x["min_odd"], f"valor confirmado: {x['best_book']} paga {x['best_odd']:.2f}")
              for x in risco(games, now, n=100) if x["valor"]]
    cands += [(r["game_id"], r["sel"], r["label"], r["p"], round(VALUE_MIN / r["p"], 2), f"a {r['book']} pagava {r['odd']:.2f}")
              for r in con.execute("select * from odds where origem='verificação' and p is not null and odd * p >= ?", (VALUE_MIN,))]
    by_id, out, done = {g["id"]: g for g in games}, [], set()
    for gid, sel, label, p, mn, why in cands:
        g = by_id.get(gid)
        if not g or (gid, sel) in reg or (gid, sel) in done:
            continue
        mins = (datetime.fromisoformat(g["kickoff"]) - now).total_seconds() / 60
        if 0 < mins <= REMIND_MIN:
            done.add((gid, sel))
            out.append({"game_id": gid, "sel": sel, "home": g["home"], "away": g["away"], "label": label, "p": p, "min_odd": mn,
                        "porque": why, "minutos": round(mins)})
    return out


_LAST = {"games": []}  # último cálculo da agenda: o placar ao vivo atualiza-se sem refazer a análise


def live_state(games, now=None):
    """Placar ESPN e sugestões ao intervalo (≥85%) nos jogos começados."""
    now = now or datetime.now(TZ)
    soon = [g for g in games if datetime.fromisoformat(g["kickoff"]) <= now + timedelta(minutes=onzes.WINDOW_MIN)]
    found = aovivo.match(soon, now, include_pre=True) if soon else {}
    for g in soon:
        ev = found.get(g["id"])
        if ev and ev["estado"] != "post" and not (g.get("onzes") or {}).get("confirmado"):
            try:
                g["onzes"] = onzes.check(g, ev)
            except Exception:
                pass  # sem rede ou ESPN mudou: tenta no próximo minuto
    states = {k: v for k, v in found.items() if v["estado"] != "pre"}
    modelo = (load_cal() or {}).get("intervalo")
    for g in games:
        s = states.get(g["id"])
        g["live"] = s
        g["ao_vivo"] = aovivo.leituras(g, s, modelo) if s else []
        if s:
            s["prob_golo"] = aovivo.prob_golo(g, s, modelo)
    out = {g["id"]: {"live": g["live"], "ao_vivo": g["ao_vivo"], "onzes": g.get("onzes")} for g in games if g["live"] or g.get("onzes")}
    try:
        out["_lembretes"] = lembretes(db(), games, now)
    except Exception:
        out["_lembretes"] = []
    return out


# --- registo de apostas -------------------------------------------------------
DB = os.path.join(HERE, "data", "apostas.sqlite")
NOTES = os.path.join(HERE, "data", "notas.json")  # notas do consultor por jogo (id do jogo -> texto)
SEASON_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
SELS = {"1x2:1", "1x2:X", "1x2:2", "ou:+2,5", "ou:-2,5", "ah:casa", "ah:fora"}
ESP_SEL = re.compile(r"^esp:(ht\+0\.5|g2\+0\.5|hs|as|dc|[cy][+-]\d{1,2}\.5|y1[+-]\d\.5|fav)$")  # y1: amarelos na 1.ª parte
RESULTS = {"ganha": 1.0, "meio-ganha": 0.5, "anulada": 0.0, "meio-perdida": -0.5, "perdida": -1.0}
MODEL_VERSION = "especialista v2.5 (18/10/2026) · odd mínima 1,20 · árbitros PT e IT · golos por parte, equipa marca, dupla hipótese"
LEG_SCHEMA = """create table if not exists legs(bet_id integer, div text, date text, home text, away text, kickoff text,
  sel text, label text, market text, line real, odd real, p real, result text default 'pendente', dono text)"""
PUB_SCHEMA = """create table if not exists published(day text, game_id text, ord integer, pick text, published_at text,
  version text, primary key(day, game_id))"""


def publish(con, sel, games, now):
    """Congela o boletim do dia na primeira vez que é calculado; depois só assinala revisões, com motivo."""
    day = sel["dia"]
    if not day:
        return sel
    rows = con.execute("select * from published where day=? order by ord", (day,)).fetchall()
    by_id = {g["id"]: g for g in games}
    if rows and rows[0]["version"] != MODEL_VERSION and all(
            datetime.fromisoformat(json.loads(r["pick"])["jogo"]["kickoff"]) > now for r in rows):
        con.execute("delete from published where day=?", (day,))  # regras novas e nenhum jogo começou: publica de novo
        rows = []
    if not rows:
        for i, p in enumerate(sel["apostas"] + sel.get("blindado", [])):
            g = by_id[p["game_id"]]
            p["jogo"] = {k: g.get(k) for k in ("id", "home", "away", "kickoff", "league", "nota", "div", "date")}
            ord_ = i if p.get("grupo") != "blindado" else 100 + i
            con.execute("insert or ignore into published values(?,?,?,?,?,?)",
                        (day, p["game_id"] + ("|b" if p.get("grupo") == "blindado" else ""), ord_,
                         json.dumps(p, ensure_ascii=False), now.isoformat(), MODEL_VERSION))
        con.commit()
        rows = con.execute("select * from published where day=? order by ord", (day,)).fetchall()
    picks, blind = [], []
    for r in rows:
        p = json.loads(r["pick"])
        p["publicado"], p["versao"] = r["published_at"], r["version"]
        g = by_id.get(p["game_id"])
        if g:
            cur = next((o for o in g.get("especialista") or [] if o["key"] == p["key"]), None)
            floor = 0.87 if p.get("grupo") == "blindado" else PICK_MIN - 0.03
            if cur is None:
                p["revisao"] = "Já não tenho dados suficientes para manter esta leitura."
            elif cur.get("veto"):
                p["revisao"] = cur["veto"]
            elif cur["p"] < floor:
                p["revisao"] = f"A confiança desceu de {round(p['p'] * 100)}% para {round(cur['p'] * 100)}% com a informação mais recente."
            p["p_atual"] = cur["p"] if cur else None
            p["jogo"]["nota"] = g.get("nota")
        p["confianca"] = p["conf"]
        (blind if p.get("grupo") == "blindado" else picks).append(p)
    return {"dia": day, "apostas": picks, "blindado": blind, "boletins": make_boletins(picks, blind),
            "publicado": rows[0]["published_at"], "versao": rows[0]["version"]}


PRED_SCHEMA = """create table if not exists preds(game_id text, name text, key text, label text, div text, date text,
  home text, away text, kickoff text, p real, p_raw real, outcome integer, primary key(game_id, name))"""
LIVE_PRIOR = 150   # previsões fechadas necessárias para a correção aprendida pesar metade


def esp_outcome(key, row, label, home):
    """1 se a previsão de especialista se confirmou, 0 se falhou, None se faltam dados. key: ht+0.5, c+8.5, y-4.5, fav."""
    g = lambda k: f(row, k)
    if key.startswith("y1"):
        return None  # o football-data não tem cartões por parte: fecha pelo placar ao vivo (settle_pending)
    try:
        if key == "fav":
            return int(row.get("FTR") == ("H" if label.removesuffix(" ganha") == home else "A"))
        if key == "dc":  # "X ou empate": falha só se o outro ganhar
            return int(row.get("FTR") != ("A" if label.removesuffix(" ou empate") == home else "H"))
        if key in ("hs", "as"):
            return int(g("FTHG" if key == "hs" else "FTAG") > 0)
        if key.startswith("g2"):
            return int(g("FTHG") + g("FTAG") - g("HTHG") - g("HTAG") > float(key[3:]))
        fam = "ht" if key.startswith("ht") else key[0]
        side = key[len(fam)]
        line = float(key[len(fam) + 1:])
        a_, b_ = {"ht": ("HTHG", "HTAG"), "c": ("HC", "AC"), "y": ("HY", "AY")}[fam]
        total = g(a_) + g(b_)  # só as colunas deste mercado
        return int(total > line) if side == "+" else int(total < line)
    except (TypeError, ValueError, KeyError, IndexError):
        return None


def f(row, k):
    try:
        return float(row.get(k) or "")
    except ValueError:
        return None


BET_SCHEMA = """create table if not exists bets(id integer primary key, created text, div text, date text, home text,
  away text, kickoff text, sel text, label text, market text, line real, book text, odd real, stake real, p_fair real,
  result text default 'pendente', profit real, closing_p real, clv real, dono text)"""


ODDS_SCHEMA = """create table if not exists odds(ts text, game_id text, sel text, label text, market text, book text,
  odd real, p real, kickoff text, origem text, dono text)"""
VALUE_MIN = 1.02  # odd x probabilidade: abaixo disto a entrada não tem margem


def log_odd(con, game_id, sel, label, market, book, odd, p, kickoff, origem):
    """Cada odd que o utilizador vê ou aposta fica guardada: é o histórico de preços da 22bet e da Betclic."""
    con.execute("insert into odds(ts, game_id, sel, label, market, book, odd, p, kickoff, origem) values(?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(TZ).isoformat(), game_id, sel, str(label)[:80], str(market or "")[:60], book, odd, p, kickoff, origem))


def odds_report(con):
    """Por mercado e casa: quantas odds registadas, odd média e quantas tinham valor (odd x prob. ≥ 1,02)."""
    out = {}
    for r in con.execute("select market, book, odd, p from odds where p is not null"):
        x = out.setdefault((r["market"] or "Outro", r["book"]), {"mercado": r["market"] or "Outro", "casa": r["book"], "n": 0, "odd": 0.0, "valor": 0, "margem": 0.0})
        x["n"] += 1
        x["odd"] += r["odd"]
        x["valor"] += r["odd"] * r["p"] >= VALUE_MIN
        x["margem"] += r["odd"] * r["p"] - 1
    return sorted(({**x, "odd": round(x["odd"] / x["n"], 3), "valor": round(x["valor"] / x["n"], 3), "margem": round(x["margem"] / x["n"], 4)}
                   for x in out.values()), key=lambda x: -x["n"])


def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute(BET_SCHEMA)
    con.execute(PRED_SCHEMA)
    con.execute(PUB_SCHEMA)
    con.execute(LEG_SCHEMA)
    con.execute(ODDS_SCHEMA)
    for t in ("bets", "legs", "odds"):  # dono: contas separadas na Cloudflare (no PC fica vazio)
        try:
            con.execute(f"alter table {t} add column dono text")
        except sqlite3.OperationalError:
            pass  # já existe
    return con


def settle_return(sel, line, odd, hg, ag):
    """Lucro por unidade apostada, dado o resultado final."""
    win = {"1x2:1": hg > ag, "1x2:X": hg == ag, "1x2:2": hg < ag, "ou:+2,5": hg + ag > 2.5, "ou:-2,5": hg + ag < 2.5}
    if sel in win:
        return odd - 1 if win[sel] else -1.0
    return ah_ret(hg - ag, line, odd) if sel == "ah:casa" else ah_ret(ag - hg, -line, odd)


def result_label(ret, odd):
    if ret == 0:
        return "anulada"
    if ret > 0:
        return "ganha" if abs(ret - (odd - 1)) < 1e-9 else "meio-ganha"
    return "perdida" if ret <= -1 + 1e-9 else "meio-perdida"


def closing_p(sel, line, row):
    """Probabilidade justa de fecho (Betfair, ou média do mercado) para medir o CLV."""
    cols = {"1x2": ["{}CH", "{}CD", "{}CA"], "ou": ["{}C>2.5", "{}C<2.5"], "ah": ["{}CAHH", "{}CAHA"]}
    key, sid = sel.split(":")
    if key == "ah":
        try:
            if float(row.get("AHCh") or "nan") != line:
                return None  # a linha mudou até ao fecho: o CLV não é comparável
        except ValueError:
            return None
    for prefix in ("BFE", "Avg"):
        odds = [num(row, c.format(prefix)) for c in cols[key]]
        if None not in odds:
            idx = {"1": 0, "X": 1, "2": 2, "+2,5": 0, "-2,5": 1, "casa": 0, "fora": 1}[sid]
            return fair_power(odds)[idx]
    return None


def season_of(date):
    d = datetime.strptime(date, "%d/%m/%Y")
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def season_rows(div, season):
    path = os.path.join(HERE, "data", f"{div}_{season}.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 6 * 3600:
        with urllib.request.urlopen(SEASON_URL.format(season=season, div=div), timeout=30) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def leg_return(b, row):
    """Lucro por unidade de uma aposta simples (ou perna de boletim) e prob. justa de fecho; (None, None) sem dados."""
    if b["sel"].startswith("esp:"):
        won = esp_outcome(b["sel"][4:], row, b["label"], b["home"])
        return (None, None) if won is None else ((b["odd"] - 1 if won else -1.0), None)  # sem odds de fecho públicas
    return settle_return(b["sel"], b["line"], b["odd"], int(row["FTHG"]), int(row["FTAG"])), closing_p(b["sel"], b["line"], row)


ESP_KEY = re.compile(r"^(ht\+|g2\+|y1[+-]|[cy][+-])(\d+(?:\.\d)?)$")


def espn_return(b):
    """Lucro por unidade pela ESPN: mercados do especialista logo que o resultado é certo (golo aos 3' fecha
    "Há golo na 1.ª parte"), 1X2/golos/handicap no apito final. None se ainda está em aberto ou não encontro o jogo."""
    if b["div"] not in aovivo.SLUG:
        return None
    try:
        day = datetime.strptime(b["date"], "%d/%m/%Y").strftime("%Y%m%d")
        evs = [aovivo._state(e) for e in aovivo.scoreboard(b["div"], day)]
    except Exception:
        return None
    from difflib import SequenceMatcher
    sim = lambda s: (SequenceMatcher(None, arbitros.norm(b["home"]), arbitros.norm(s["home_espn"])).ratio()
                     + SequenceMatcher(None, arbitros.norm(b["away"]), arbitros.norm(s["away_espn"])).ratio())
    s = max(evs, key=sim, default=None)
    if not s or sim(s) < 1.1 or s["estado"] == "pre":
        return None
    if not b["sel"].startswith("esp:"):
        return settle_return(b["sel"], b["line"], b["odd"], s["hg"], s["ag"]) if s["estado"] == "post" else None
    m = ESP_KEY.match(b["sel"][4:])
    pick = {"key": m.group(1), "line": float(m.group(2)), "label": b["label"]} if m else {"key": b["sel"][4:], "label": b["label"]}
    won = aovivo.decided(pick, {"home": b["home"], "away": b["away"]}, s)
    return None if won is None else (b["odd"] - 1 if won else -1.0)


def settle_pending(con, now, official=True):
    """Liquida apostas e pernas de boletins cujos jogos já acabaram e já estão publicados no football-data."""
    cutoff = (now - timedelta(hours=2, minutes=30)).isoformat()
    cache = {}

    def row_for(b):
        key = (b["div"], season_of(b["date"]))
        if key not in cache:
            cache[key] = season_rows(*key)
        r = next((r for r in cache[key] if r.get("Date") == b["date"] and r.get("HomeTeam") == b["home"]), None)
        return r if r and r.get("FTHG") else None

    live_by_id = {g["id"]: g for g in _LAST["games"] if g.get("live")}

    def by_halves(b):
        """Amarelos na 1.ª parte: decide-se ao intervalo pelos cartões da ESPN (com o minuto de cada um)."""
        g = live_by_id.get(f"{b['div']}-{b['date']}-{b['home']}")
        won = aovivo.decided({"key": b["sel"][4:7], "line": float(b["sel"][7:])}, g, g["live"]) if g else None
        return None if won is None else (b["odd"] - 1 if won else -1.0)

    # resultado final da ESPN: fecha no próprio dia (o football-data só publica no dia seguinte)
    espn_cut = now.isoformat()  # já começou: a ESPN diz se está decidido
    for b in con.execute("select * from bets where result='pendente' and sel != 'multi' and kickoff < ?", (espn_cut,)).fetchall():
        ret = espn_return(b)
        if ret is not None:
            con.execute("update bets set result=?, profit=? where id=?", (result_label(ret, b["odd"]), round(ret * b["stake"], 2), b["id"]))
    for l in con.execute("select rowid, * from legs where result='pendente' and kickoff < ?", (espn_cut,)).fetchall():
        ret = espn_return(l)
        if ret is not None:
            con.execute("update legs set result=? where rowid=?", (result_label(ret, l["odd"]), l["rowid"]))
    for b in con.execute("select * from bets where result='pendente' and sel like 'esp:y1%'").fetchall():
        ret = by_halves(b)
        if ret is not None:
            con.execute("update bets set result=?, profit=? where id=?", (result_label(ret, b["odd"]), round(ret * b["stake"], 2), b["id"]))
    for l in con.execute("select rowid, * from legs where result='pendente' and sel like 'esp:y1%'").fetchall():
        ret = by_halves(l)
        if ret is not None:
            con.execute("update legs set result=? where rowid=?", (result_label(ret, l["odd"]), l["rowid"]))
    for b in (con.execute("select * from bets where result='pendente' and sel != 'multi' and kickoff < ?", (cutoff,)).fetchall() if official else []):
        row = row_for(b)
        ret, cp = leg_return(b, row) if row else (None, None)
        if ret is None:
            continue
        con.execute("update bets set result=?, profit=?, closing_p=?, clv=? where id=?",
                    (result_label(ret, b["odd"]), round(ret * b["stake"], 2), cp,
                     round(b["odd"] * cp - 1, 4) if cp else None, b["id"]))
    for l in (con.execute("select rowid, * from legs where result='pendente' and kickoff < ?", (cutoff,)).fetchall() if official else []):
        row = row_for(l)
        ret, _ = leg_return(l, row) if row else (None, None)
        if ret is not None:
            con.execute("update legs set result=? where rowid=?", (result_label(ret, l["odd"]), l["rowid"]))
    # boletim fecha quando todas as pernas fecharem: perdida = 0, anulada = odd 1, meia = metade
    factor = {"ganha": lambda o: o, "meio-ganha": lambda o: (o + 1) / 2, "anulada": lambda o: 1.0,
              "meio-perdida": lambda o: 0.5, "perdida": lambda o: 0.0}
    for b in con.execute("select * from bets where result='pendente' and sel='multi'").fetchall():
        legs = con.execute("select * from legs where bet_id=?", (b["id"],)).fetchall()
        if legs and any(l["result"] == "perdida" for l in legs):  # uma perna perdida chega: não espera pelas outras
            con.execute("update bets set result='perdida', profit=? where id=?", (round(-b["stake"], 2), b["id"]))
            continue
        if not legs or any(l["result"] == "pendente" for l in legs):
            continue
        prod_legs = math.prod(l["odd"] for l in legs)
        mult = math.prod(factor[l["result"]](l["odd"]) for l in legs) * (b["odd"] / prod_legs)  # respeita odd total da casa
        profit = b["stake"] * (mult - 1)
        res = "perdida" if mult == 0 else "ganha" if all(l["result"] == "ganha" for l in legs) else "anulada" if abs(mult - 1) < 1e-9 else \
              ("meio-ganha" if profit > 0 else "meio-perdida")
        con.execute("update bets set result=?, profit=? where id=?", (res, round(profit, 2), b["id"]))
    con.commit()


def settle_preds(con, now):
    """Confronta as previsões publicadas com o que aconteceu."""
    pend = con.execute("select * from preds where outcome is null and kickoff < ?",
                       ((now - timedelta(hours=2, minutes=30)).isoformat(),)).fetchall()
    cache = {}
    for p in pend:
        key = (p["div"], season_of(p["date"]))
        if key not in cache:
            cache[key] = season_rows(*key)
        row = next((r for r in cache[key] if r.get("Date") == p["date"] and r.get("HomeTeam") == p["home"]), None)
        if row and row.get("FTHG"):
            o = esp_outcome(p["key"], row, p["label"], p["home"])
            if o is not None:
                con.execute("update preds set outcome=? where game_id=? and name=?", (o, p["game_id"], p["name"]))
    con.commit()


def learning(con):
    """Por mercado: acerto previsto vs real nas últimas 300 previsões fechadas e a correção a aplicar."""
    out = {}
    for (name,) in con.execute("select distinct name from preds where outcome is not null"):
        rs = con.execute("select p, outcome from preds where name=? and outcome is not null order by kickoff desc limit 300", (name,)).fetchall()
        n = len(rs)
        mp, hit = sum(r["p"] for r in rs) / n, sum(r["outcome"] for r in rs) / n
        top = [r for r in rs if r["p"] >= 0.72]
        out[name] = {"n": n, "previsto": round(mp, 3), "real": round(hit, 3), "ajuste": round((hit - mp) * n / (n + LIVE_PRIOR), 3),
                     "n_conf": len(top), "real_conf": round(sum(r["outcome"] for r in top) / len(top), 3) if top else None}
    return out


TEAMS_FILE = os.path.join(HERE, "data", "equipas.json")  # especialista_equipas.py: acerto do modelo por equipa (teste)
WON = {"ganha", "meio-ganha"}


def teams_report(con):
    """Acerto por equipa: histórico do modelo (fora da amostra), previsões da app já fechadas e as tuas apostas.

    Testado: corrigir a confiança pelo historial da equipa piora a previsão (especialista_equipas.py), por isso isto
    é contexto para ti, não mexe nas probabilidades.
    """
    try:
        with open(TEAMS_FILE, encoding="utf-8") as fh:
            hist = json.load(fh)
    except (OSError, ValueError):
        hist = {"equipas": {}, "ligas": {}}
    out = {}
    row = lambda t: out.setdefault(t, {"equipa": t, "liga": LEAGUES.get(hist["ligas"].get(t), ""), "hist": None,
                                       "previsoes": {"n": 0, "p": 0.0, "certas": 0}, "apostas": {"n": 0, "ganhas": 0, "lucro": 0.0}})
    for t, fams in hist["equipas"].items():
        n = sum(x["n"] for x in fams.values())
        best = max((x for x in fams.items() if x[1]["n"] >= 20), key=lambda x: x[1]["real"], default=None)
        row(t)["hist"] = {"n": n, "previsto": round(sum(x["previsto"] * x["n"] for x in fams.values()) / n, 3),
                          "real": round(sum(x["hit"] for x in fams.values()) / n, 3),
                          "melhor": {"mercado": best[0], "real": best[1]["real"], "n": best[1]["n"]} if best else None}
    for r in con.execute("select home, away, div, p, outcome from preds where outcome is not null"):
        for t in (r["home"], r["away"]):
            x = row(t)
            x["liga"] = x["liga"] or LEAGUES.get(r["div"], "")
            x["previsoes"]["n"] += 1
            x["previsoes"]["p"] += r["p"]
            x["previsoes"]["certas"] += r["outcome"]
    singles = con.execute("select div, home, away, label, result, profit from bets where sel != 'multi' and result != 'pendente'").fetchall()
    legs = con.execute("select div, home, away, label, result, null as profit from legs where result != 'pendente'").fetchall()
    for r in list(singles) + list(legs):
        # uma linha por aposta: a equipa em que apostaste, ou o jogo nos mercados do jogo inteiro (cantos, cartões, golos)
        lab = r["label"] or ""
        x = row(r["home"] if lab.startswith(r["home"]) else r["away"] if lab.startswith(r["away"]) else f"{r['home']} – {r['away']}")
        x["liga"] = x["liga"] or LEAGUES.get(r["div"], "")
        x["apostas"]["n"] += 1
        x["apostas"]["ganhas"] += r["result"] in WON
        x["apostas"]["lucro"] += r["profit"] or 0
    for x in out.values():
        pv = x["previsoes"]
        p_sum = pv.pop("p")
        pv["previsto"] = round(p_sum / pv["n"], 3) if pv["n"] else None
        x["apostas"]["lucro"] = round(x["apostas"]["lucro"], 2)
    return {"fonte": hist.get("fonte"), "equipas": sorted(out.values(), key=lambda x: x["equipa"])}


def track_record(con, games=()):
    """Histórico à vista: calibração (teste e app) por faixa de confiança e cada boletim do dia publicado."""
    try:
        with open(TEAMS_FILE, encoding="utf-8") as fh:
            test = json.load(fh).get("calibracao", [])
    except (OSError, ValueError):
        test = []
    bins = [(0.72, 0.76), (0.76, 0.80), (0.80, 0.84), (0.84, 0.88), (0.88, 1.01)]
    rows = con.execute("select p, outcome from preds where outcome is not null and p >= 0.72").fetchall()
    app = [{"faixa": f"{int(a * 100)}–{min(int(b * 100), 100)}%", "n": len(k), "previsto": round(sum(r["p"] for r in k) / len(k), 3),
            "real": round(sum(r["outcome"] for r in k) / len(k), 3)} for a, b in bins for k in [[r for r in rows if a <= r["p"] < b]] if k]
    outc = {(r["game_id"], r["name"]): r["outcome"] for r in con.execute("select game_id, name, outcome from preds")}
    live_by_id = {g["id"]: g for g in games if g.get("live")}
    days = {}
    for r in con.execute("select day, game_id, pick from published order by day desc, ord"):
        p = json.loads(r["pick"])
        d = days.setdefault(r["day"], {"dia": r["day"], "apostas": 0, "certas": 0, "falhadas": 0, "blindado": 0})
        if p.get("grupo") == "blindado":
            d["blindado"] += 1
            continue
        o = outc.get((p["game_id"], p.get("name")))
        g = live_by_id.get(p["game_id"])
        if o is None and g:
            o = aovivo.decided(p, g, g["live"])  # já decidido no placar ao vivo; o oficial chega no dia seguinte
        d["apostas"] += 1
        d["certas"] += o == 1
        d["falhadas"] += o == 0
    return {"teste": test, "app": app, "dias": list(days.values())[:30]}


def bets_report(now=None):
    con = db()
    warning = None
    try:
        settle_pending(con, now or datetime.now(TZ))
        settle_preds(con, now or datetime.now(TZ))
    except Exception as e:  # sem rede: mostra o que há e avisa
        warning = f"Não consegui atualizar resultados: {e}"
    bets = [dict(b) for b in con.execute("select * from bets order by kickoff desc, id desc")]
    for b in bets:
        if b["sel"] == "multi":
            b["pernas"] = [dict(l) for l in con.execute("select * from legs where bet_id=? order by kickoff", (b["id"],))]
    done = [b for b in bets if b["result"] != "pendente"]
    staked = sum(b["stake"] for b in done)
    profit = sum(b["profit"] or 0 for b in done)
    clvs = [b["clv"] for b in bets if b["clv"] is not None]
    priced = [b for b in bets if b["p_fair"]]
    by_book = {}
    for b in done:
        x = by_book.setdefault(b["book"], {"apostas": 0, "investido": 0.0, "lucro": 0.0})
        x["apostas"] += 1
        x["investido"] += b["stake"]
        x["lucro"] += b["profit"] or 0
    return {"bets": bets, "warning": warning, "aprendizagem": learning(con), "odds": odds_report(con), "equipas": teams_report(con), "clv_mercados": clv_markets(con), "historico": track_record(con, _LAST["games"]), "summary": {
        "total": len(bets), "pendentes": len(bets) - len(done), "liquidadas": len(done), "investido": round(staked, 2),
        "lucro": round(profit, 2), "roi": round(profit / staked, 4) if staked else None,
        "clv_medio": round(sum(clvs) / len(clvs), 4) if clvs else None, "clv_n": len(clvs),
        "clv_positivo": round(sum(c > 0 for c in clvs) / len(clvs), 3) if clvs else None,
        "acerto": round(sum((b["profit"] or 0) > 0 for b in done) / len(done), 3) if done else None,
        "com_valor": round(sum(b["odd"] * b["p_fair"] >= VALUE_MIN for b in priced) / len(priced), 3) if priced else None,
        "margem_media": round(sum(b["odd"] * b["p_fair"] - 1 for b in priced) / len(priced), 4) if priced else None, "n_valor": len(priced),
        "por_casa": by_book}}


def bets_csv():
    """O registo completo (apostas e pernas dos boletins) em CSV, para guardares ou abrires no Excel."""
    import io
    con, buf = db(), io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "criada", "tipo", "casa", "jogo", "inicio", "selecao", "mercado", "odd", "stake", "prob_estimada", "resultado", "lucro", "clv"])
    for b in con.execute("select * from bets order by kickoff, id"):
        w.writerow([b["id"], b["created"], "boletim" if b["sel"] == "multi" else "simples", b["book"], f"{b['home']} - {b['away']}", b["kickoff"],
                    b["label"], b["market"], b["odd"], b["stake"], b["p_fair"], b["result"], b["profit"], b["clv"]])
        for l in con.execute("select * from legs where bet_id=? order by kickoff", (b["id"],)) if b["sel"] == "multi" else []:
            w.writerow([b["id"], "", "perna", "", f"{l['home']} - {l['away']}", l["kickoff"], l["label"], l["market"], l["odd"], "", l["p"], l["result"], "", ""])
    return "\ufeff" + buf.getvalue()  # BOM: o Excel abre os acentos bem


def bets_action(p):
    """Altera o registo. Valida tudo o que vem do browser."""
    con = db()
    act = p.get("action")
    if act == "add":
        odd, stk = float(p["odd"]), float(p["stake"])
        book = str(p.get("book", "")).strip()[:30]
        if not (odd > 1 and stk > 0 and book and (p.get("sel") in SELS or ESP_SEL.match(str(p.get("sel"))))):
            raise ValueError("Aposta inválida: confirma a odd, o stake e a casa.")
        datetime.strptime(p["date"], "%d/%m/%Y")
        line = float(p["line"]) if p.get("line") not in (None, "") else None
        if p["sel"].startswith("ah:") and line is None:
            raise ValueError("Falta a linha do handicap.")
        con.execute("""insert into bets(created, div, date, home, away, kickoff, sel, label, market, line, book, odd, stake, p_fair)
                       values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (datetime.now(TZ).isoformat(), p["div"], p["date"], p["home"], p["away"], p["kickoff"], p["sel"],
                     str(p.get("label", ""))[:80], str(p.get("market", ""))[:60], line, book, odd, stk,
                     float(p["p_fair"]) if p.get("p_fair") else None))
        log_odd(con, f"{p['div']}-{p['date']}-{p['home']}", p["sel"], p.get("label", ""), p.get("market"), book, odd,
                float(p["p_fair"]) if p.get("p_fair") else None, p["kickoff"], "aposta")
    elif act == "odd":
        odd, book, p_ = float(p["odd"]), str(p.get("book", "")).strip()[:30], float(p["p"]) if p.get("p") not in (None, "") else None
        if not (1 < odd < 100 and book and (p.get("sel") in SELS or ESP_SEL.match(str(p.get("sel")))) and (p_ is None or 0 < p_ < 1)):
            raise ValueError("Odd inválida.")
        log_odd(con, str(p["game_id"])[:80], p["sel"], p.get("label", ""), p.get("market"), book, odd, p_, str(p.get("kickoff", ""))[:30], "verificação")
    elif act == "resultado":
        if p.get("result") not in RESULTS:
            raise ValueError("Resultado inválido.")
        b = con.execute("select * from bets where id=?", (int(p["id"]),)).fetchone()
        if not b:
            raise ValueError("Aposta não encontrada.")
        f = RESULTS[p["result"]]
        profit = b["stake"] * (f * (b["odd"] - 1) if f > 0 else f)
        con.execute("update bets set result=?, profit=? where id=?", (p["result"], round(profit, 2), b["id"]))
    elif act == "add_multi":
        legs, stk, book = p.get("legs") or [], float(p["stake"]), str(p.get("book", "")).strip()[:30]
        if not (2 <= len(legs) <= 12 and stk > 0 and book):
            raise ValueError("Um boletim precisa de 2 a 12 seleções, casa e valor.")
        clean = []
        for l in legs:
            odd = float(l["odd"])
            if not (odd > 1 and (l.get("sel") in SELS or ESP_SEL.match(str(l.get("sel"))))):
                raise ValueError(f"Seleção inválida no boletim: {l.get('label', '?')} (falta a odd?)")
            datetime.strptime(l["date"], "%d/%m/%Y")
            line = float(l["line"]) if l.get("line") not in (None, "") else None
            clean.append((l["div"], l["date"], l["home"], l["away"], l["kickoff"], l["sel"], str(l.get("label", ""))[:80],
                          str(l.get("market", ""))[:60], line, odd, float(l["p"]) if l.get("p") else None))
        total = float(p.get("odd_total") or 0) or math.prod(c[9] for c in clean)
        ps = [c[10] for c in clean]
        last = max(clean, key=lambda c: c[4])
        cur = con.execute("""insert into bets(created, div, date, home, away, kickoff, sel, label, market, line, book, odd, stake, p_fair)
                             values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (datetime.now(TZ).isoformat(), last[0], last[1], last[2], last[3], last[4], "multi",
                           f"Boletim de {len(clean)}: " + " + ".join(c[6] for c in clean)[:200], "Boletim", None, book,
                           round(total, 3), stk, math.prod(ps) if None not in ps else None))
        con.executemany("insert into legs(bet_id, div, date, home, away, kickoff, sel, label, market, line, odd, p) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(cur.lastrowid,) + c for c in clean])
        for c in clean:
            log_odd(con, f"{c[0]}-{c[1]}-{c[2]}", c[5], c[6], c[7], book, c[9], c[10], c[4], "aposta")
    elif act == "apagar":
        con.execute("delete from legs where bet_id=?", (int(p["id"]),))
        con.execute("delete from bets where id=?", (int(p["id"]),))
    else:
        raise ValueError("Ação desconhecida.")
    con.commit()
    return {"ok": True}


def open_bet_games(con):
    """{id do jogo: [rótulos]} das apostas e pernas por decidir."""
    out = {}
    for b in con.execute("select * from bets where result='pendente'"):
        legs = con.execute("select * from legs where bet_id=? and result='pendente'", (b["id"],)).fetchall() if b["sel"] == "multi" else [b]
        for l in legs:
            out.setdefault(f"{l['div']}-{l['date']}-{l['home']}", []).append(l["label"])
    return out


def watcher(every=60):
    """Vigia os jogos sem a página aberta e envia os avisos para o telemóvel (só com o ntfy ativo)."""
    last = 0
    while True:
        try:
            if avisos.config().get("ativo"):
                if not _LAST["games"] or time.time() - last > 1800:
                    agenda(100)  # recalcula a análise de meia em meia hora; o placar vai a cada minuto
                    last = time.time()
                else:
                    live_state(_LAST["games"])
                con = db()
                day = datetime.now(TZ).date().isoformat()
                picks = {r["game_id"].split("|")[0] for r in con.execute("select game_id from published where day=?", (day,))}
                avisos.run_once(_LAST["games"], open_bet_games(con), picks, lembretes(con, _LAST["games"], datetime.now(TZ)))
        except Exception:
            pass  # sem rede: tenta no minuto seguinte
        time.sleep(every)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(HERE, "web"), **kw)

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        try:
            if self.path.startswith("/api/agenda"):
                q = parse_qs(urlparse(self.path).query)
                return self.send_json(200, agenda(float(q.get("banca", ["100"])[0]), force="refresh" in q))
            if self.path.startswith("/api/live"):
                return self.send_json(200, live_state(_LAST["games"]))
            if self.path.startswith("/api/calendario"):
                return self.send_json(200, aovivo.calendario(_LAST["games"], LEAGUES, datetime.now(TZ)))
            if self.path.startswith("/api/apostas.csv"):
                body = bets_csv().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="bigodds-apostas.csv"')
                self.end_headers()
                return self.wfile.write(body)
            if self.path.startswith("/api/apostas"):
                return self.send_json(200, bets_report())
            if self.path.startswith("/api/avisos"):
                return self.send_json(200, avisos.config())
        except Exception as e:  # sem rede ou ficheiro inválido: a página mostra o erro
            return self.send_json(502, {"error": str(e)})
        super().do_GET()

    def do_POST(self):
        if not self.path.startswith(("/api/apostas", "/api/avisos")):
            return self.send_json(404, {"error": "não encontrado"})
        try:
            # exigir JSON obriga o browser a pedir autorização (CORS) a outros sites: só a própria página escreve
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                raise ValueError("Pedido tem de ser JSON.")
            n = int(self.headers.get("Content-Length", 0))
            if n > 10_000:
                raise ValueError("Pedido demasiado grande.")
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path.startswith("/api/avisos"):
                c = avisos.set_active(body.get("ativo") is True)
                if c["ativo"] and body.get("teste"):
                    try:
                        avisos.send("Bigodds ligado", "A partir de agora recebes aqui as leituras ao vivo, os onzes e os lances das tuas apostas.", "white_check_mark")
                    except Exception as e:  # sem rede: fica ativo na mesma
                        c = {**c, "erro": f"Não consegui enviar a mensagem de teste: {e}"}
                return self.send_json(200, c)
            self.send_json(200, bets_action(body))
        except (ValueError, KeyError, TypeError) as e:
            self.send_json(400, {"error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8765))
    print(f"Bigodds em http://localhost:{port}")
    threading.Thread(target=watcher, daemon=True).start()
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
