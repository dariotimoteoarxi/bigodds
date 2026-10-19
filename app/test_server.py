from datetime import datetime
from server import TZ, analyse, fair_power, stake

p = fair_power([1.5, 4.2, 6.5])
assert abs(sum(p) - 1) < 1e-9
assert p[2] < (1 / 6.5) / (1 / 1.5 + 1 / 4.2 + 1 / 6.5)  # tira mais margem ao outsider que o proporcional
assert stake(0.5, 2.1, 100) == 1.14 and stake(0.4, 2.0, 100) == 0  # Kelly 1/4; sem valor, sem stake

noon = datetime(2026, 10, 19, 12, 0, tzinfo=TZ)
row = {"Div": "P1", "Date": "19/10/2026", "Time": "20:15", "HomeTeam": "Sp Braga", "AwayTeam": "Gil Vicente",
       "BFEH": "1.60", "BFED": "4.20", "BFEA": "6.40", "B365H": "1.72", "B365D": "3.90", "B365A": "5.50", "BWH": "1.65"}
early = analyse(row, 100, noon)
assert early["pick"]["sel"] == "1x2:1" and early["pick"]["best_book"] == "Bet365" and early["verdict"] == "esperar"
assert analyse(row, 100, datetime(2026, 10, 19, 19, 30, tzinfo=TZ))["verdict"] == "entrar"  # onzes já saíram
row2 = {**row, "B365H": "1.58", "BWH": "1.60", "B365A": "8.00"}  # valor só no outsider: excluído
assert analyse(row2, 100, noon)["verdict"] == "nao"

# Over/Under e handicap: o valor pode estar noutro mercado; a linha 0 e negativa é lida
row3 = {**row2, "BFE>2.5": "2.00", "BFE<2.5": "1.95", "B365>2.5": "2.12", "B365<2.5": "1.75", "Max>2.5": "2.15",
        "AHh": "-0.75", "BFEAHH": "1.98", "BFEAHA": "1.96", "B365AHH": "1.90", "B365AHA": "2.00"}
g = analyse(row3, 100, noon)
assert [m["key"] for m in g["markets"]] == ["1x2", "ou", "ah"]
assert g["pick"]["sel"] == "ou:+2,5" and g["verdict"] == "esperar"
assert g["markets"][2]["selections"][1]["label"] == "Gil Vicente +0,75"
assert any(o.get("info") for o in g["markets"][1]["selections"][0]["offers"])  # melhor odd do mercado só como informação
assert analyse({**row2, "AHh": "0", "BFEAHH": "1.9", "BFEAHA": "2.0"}, 100, noon)["markets"][-1]["title"].endswith("(0)")
print("ok")

# --- registo de apostas ---
import os, tempfile
import server
from server import bets_action, bets_report, closing_p, result_label, season_of, settle_return

assert settle_return("1x2:1", None, 2.0, 2, 1) == 1.0 and settle_return("1x2:X", None, 3.4, 1, 1) == 2.4
assert settle_return("ou:-2,5", None, 1.9, 2, 1) == -1.0
assert settle_return("ah:casa", -0.25, 2.0, 1, 1) == -0.5 and result_label(-0.5, 2.0) == "meio-perdida"
assert settle_return("ah:fora", -0.75, 2.0, 2, 1) == -0.5  # fora +0,75 perde por 1: metade perde, metade devolvida
assert settle_return("ah:casa", -0.75, 2.0, 2, 1) == 0.5 and result_label(0.5, 2.0) == "meio-ganha"  # casa -0,75 ganha por 1
assert settle_return("ah:casa", -1.0, 1.9, 2, 1) == 0 and result_label(0, 1.9) == "anulada"
assert season_of("18/10/2026") == "2627" and season_of("10/05/2027") == "2627"
fecho = {"BFECH": "1.80", "BFECD": "3.80", "BFECA": "5.00", "AHCh": "-0.5", "BFECAHH": "1.95", "BFECAHA": "1.95"}
assert abs(closing_p("ah:casa", -0.5, fecho) - 0.5) < 1e-9 and closing_p("ah:casa", -0.25, fecho) is None

server.DB = os.path.join(tempfile.mkdtemp(), "t.sqlite")
jogo = {"div": "P1", "date": "19/10/2026", "home": "Sp Braga", "away": "Gil Vicente", "kickoff": "2026-10-19T20:15:00+01:00"}
bets_action({"action": "add", **jogo, "sel": "1x2:1", "label": "Sp Braga", "book": "Betclic", "odd": "1.90", "stake": "10", "p_fair": "0.55"})
bets_action({"action": "add", **jogo, "sel": "ah:fora", "label": "Gil Vicente +0,5", "line": "-0.5", "book": "22bet", "odd": "2.10", "stake": "5"})
for bad in ({"odd": "1.0"}, {"stake": "0"}, {"sel": "outra"}, {"book": ""}):
    try:
        bets_action({"action": "add", **jogo, "sel": "1x2:1", "book": "Betclic", "odd": "2", "stake": "1", **bad}); raise SystemExit("aceitou aposta inválida")
    except ValueError:
        pass
server.season_rows = lambda div, season: [{"Date": "19/10/2026", "HomeTeam": "Sp Braga", "FTHG": "2", "FTAG": "0", **fecho}]
r = bets_report(now=datetime(2026, 10, 20, 9, 0, tzinfo=TZ))
by = {b["sel"]: b for b in r["bets"]}
assert by["1x2:1"]["result"] == "ganha" and by["1x2:1"]["profit"] == 9.0
assert abs(by["1x2:1"]["clv"] - (1.90 * closing_p("1x2:1", None, fecho) - 1)) < 1e-3
assert by["ah:fora"]["result"] == "perdida" and by["ah:fora"]["profit"] == -5.0 and by["ah:fora"]["clv"] is not None
s = r["summary"]
assert s["liquidadas"] == 2 and s["lucro"] == 4.0 and s["investido"] == 15.0 and abs(s["roi"] - 4 / 15) < 1e-3
bets_action({"action": "resultado", "id": by["1x2:1"]["id"], "result": "anulada"})
assert bets_report()["summary"]["lucro"] == -5.0
bets_action({"action": "apagar", "id": by["ah:fora"]["id"]})
assert bets_report()["summary"]["total"] == 1
print("registo ok")

# --- especialista ---
from consultor import calibrate, _negbin_over, _poisson_over
from server import esp_outcome
row = {"HTHG": "0", "HTAG": "1", "HC": "5", "AC": "4", "HY": "2", "AY": "1", "FTR": "A"}
assert esp_outcome("ht+0.5", row, "", "X") == 1 and esp_outcome("c+8.5", row, "", "X") == 1 and esp_outcome("c-10.5", row, "", "X") == 1
assert esp_outcome("c+9.5", row, "", "X") == 0 and esp_outcome("y+3.5", row, "", "X") == 0 and esp_outcome("y-4.5", row, "", "X") == 1
assert esp_outcome("y+2.5", row, "", "X") == 1 and esp_outcome("zz", row, "", "X") is None
assert esp_outcome("ht-1.5", row, "", "X") == 1 and esp_outcome("ht-0.5", row, "", "X") == 0  # 0-1 ao intervalo
assert esp_outcome("hc-5.5", row, "", "X") == 1 and esp_outcome("ac-3.5", row, "", "X") == 0 and esp_outcome("hy-1.5", row, "", "X") == 0  # HC 5, AC 4, HY 2
from server import ESP_SEL, ESP_KEY
assert ESP_SEL.match("esp:hc-4.5") and ESP_SEL.match("esp:hy-1.5") and not ESP_SEL.match("esp:hc+4.5") and ESP_KEY.match("ac-3.5").groups() == ("ac-", "3.5")
assert esp_outcome("fav", row, "Braga ganha", "Braga") == 0 and esp_outcome("fav", row, "Gil ganha", "Braga") == 1
cal = {"m": {"cal": [(0.5, 0.6), (0.8, 0.75)]}}
assert calibrate(cal, "m", 0.3) == 0.6 and calibrate(cal, "m", 0.9) == 0.75 and abs(calibrate(cal, "m", 0.65) - 0.675) < 1e-9
assert abs(_negbin_over(4.0, 3.5, 1.0) - _poisson_over(4.0, 3.5)) < 1e-12 and _negbin_over(4.0, 3.5, 1.5) < _poisson_over(4.0, 3.5)
from server import ESP_SEL
assert ESP_SEL.match("esp:c+10.5") and ESP_SEL.match("esp:fav") and not ESP_SEL.match("esp:c+10") and not ESP_SEL.match("esp:x")
print("especialista ok")

# --- árbitro como filtro ---
from consultor import referee_profile
base = [{"HY": "2", "AY": "2", "HF": "10", "AF": "10", "Referee": "Outro"} for _ in range(100)]
brando = [{"HY": "0", "AY": "1", "HF": "12", "AF": "12", "Referee": "Brando"} for _ in range(30)]
p = referee_profile(base + brando, "Brando")
assert p["tipo"] == "brando" and p["jogos"] == 30 and p["rel"] < -0.12
assert referee_profile(base, "Novo")["tipo"] == "normal"  # sem jogos: encolhe para a média da liga
assert referee_profile(base, None) is None
print("árbitro ok")

# --- boletim congelado ---
import sqlite3 as _sq
from server import publish, PUB_SCHEMA
_c = _sq.connect(":memory:"); _c.row_factory = _sq.Row; _c.execute(PUB_SCHEMA)
_g = {"id": "G1", "home": "A", "away": "B", "kickoff": "2026-10-19T20:00:00+01:00", "league": "L", "nota": None,
      "especialista": [{"key": "y-4.5", "p": 0.82}]}
_p = {"game_id": "G1", "key": "y-4.5", "label": "Menos de 4,5 amarelos", "p": 0.82, "min_odd": 1.24, "conf": "Alta"}
_now = datetime(2026, 10, 19, 10, 0, tzinfo=TZ)
s1 = publish(_c, {"dia": "2026-10-19", "apostas": [_p], "boletins": []}, [_g], _now)
# o modelo mudou de ideias: o boletim publicado mantém-se e a mudança aparece como revisão
_g["especialista"] = [{"key": "y-4.5", "p": 0.60}, {"key": "c-10.5", "p": 0.85}]
s2 = publish(_c, {"dia": "2026-10-19", "apostas": [{**_p, "key": "c-10.5"}], "boletins": []}, [_g], _now)
assert s2["apostas"][0]["key"] == "y-4.5" and "desceu de 82% para 60%" in s2["apostas"][0]["revisao"]
assert s1["publicado"] == s2["publicado"]
print("boletim ok")

# --- árbitros Portugal ---
import arbitros
noms = [{"season": "20262027", "round": "2", "date": "2026-10-19", "home": "SC Braga", "away": "Gil Vicente FC", "referee": "Gustavo Correia"},
        {"season": "20262027", "round": "8", "date": "2026-10-09", "home": "Moreirense FC", "away": "Gil Vicente FC", "referee": "Miguel Nogueira"}]
fd = [{"Date": "19/10/2026", "HomeTeam": "Sp Braga"}, {"Date": "09/10/2026", "HomeTeam": "Moreirense"}, {"Date": "10/10/2026", "HomeTeam": "Porto"}]
arbitros.attach(fd, noms)
assert [r["Referee"] for r in fd] == ["Gustavo Correia", "Miguel Nogueira", ""]
assert arbitros.norm("Sporting CP") == "sp lisbon" and arbitros.norm("Vitória SC") == "guimaraes"
print("árbitros PT ok")

# --- mercados acrescentados ---
r2 = {"HTHG": "1", "HTAG": "0", "FTHG": "1", "FTAG": "1", "FTR": "D"}
assert esp_outcome("g2+0.5", r2, "", "X") == 1 and esp_outcome("hs", r2, "", "X") == 1
assert esp_outcome("as", {**r2, "FTAG": "0"}, "", "X") == 0
assert esp_outcome("go+1.5", r2, "", "X") == 1 and esp_outcome("go-1.5", r2, "", "X") == 0 and ESP_SEL.match("esp:go+1.5")  # 1-1
assert esp_outcome("g2-2.5", r2, "", "X") == 1 and esp_outcome("g2-0.5", r2, "", "X") == 0  # 1 golo na 2.ª parte
import sqlite3 as _sq
from server import PRED_SCHEMA, log_live_preds
_c = _sq.connect(":memory:"); _c.execute(PRED_SCHEMA)
_g = {"id": "I1-x", "div": "I1", "date": "19/10/2026", "home": "A", "away": "B", "kickoff": "2026-10-19T19:45:00+01:00",
      "ao_vivo": [{"key": "Há golo na 2.ª parte", "label": "Mais de 1,5 golos no jogo", "p": 0.7},
                  {"key": "Menos de (intervalo + 2,5) golos", "label": "Menos de 3,5 golos no jogo", "p": 0.72}]}
log_live_preds(_c, [_g]); log_live_preds(_c, [_g])  # a segunda leitura do mesmo intervalo não duplica
assert sorted(r[0] for r in _c.execute("select key from preds")) == ["g2+0.5", "g2-2.5"]
assert esp_outcome("dc", r2, "Braga ou empate", "Braga") == 1 and esp_outcome("dc", {**r2, "FTR": "A"}, "Braga ou empate", "Braga") == 0
assert esp_outcome("dc", {**r2, "FTR": "H"}, "Gil ou empate", "Braga") == 0
assert ESP_SEL.match("esp:g2+0.5") and ESP_SEL.match("esp:hs") and ESP_SEL.match("esp:dc")
print("mercados novos ok")

# --- boletim (múltipla) ---
server.DB = os.path.join(tempfile.mkdtemp(), "m.sqlite")
L1 = {**jogo, "sel": "esp:hs", "label": "Sp Braga marca", "market": "Equipa marca", "odd": "1.20", "p": "0.88"}
L2 = {"div": "P1", "date": "19/10/2026", "home": "Porto", "away": "Arouca", "kickoff": "2026-10-19T18:00:00+01:00",
      "sel": "esp:y-4.5", "label": "Menos de 4,5 amarelos", "market": "Cartões", "odd": "1.30", "p": "0.80"}
try:
    bets_action({"action": "add_multi", "legs": [L1], "stake": "5", "book": "22bet"}); raise SystemExit("aceitou boletim de 1")
except ValueError:
    pass
bets_action({"action": "add_multi", "legs": [L1, L2], "stake": "5", "book": "22bet"})
server.season_rows = lambda div, season: [
    {"Date": "19/10/2026", "HomeTeam": "Sp Braga", "FTHG": "2", "FTAG": "0", "HTHG": "1", "HTAG": "0", "HY": "2", "AY": "2"},
    {"Date": "19/10/2026", "HomeTeam": "Porto", "FTHG": "1", "FTAG": "1", "HTHG": "0", "HTAG": "0", "HY": "3", "AY": "3"}]
r = bets_report(now=datetime(2026, 10, 20, 9, 0, tzinfo=TZ))
m = r["bets"][0]
assert m["sel"] == "multi" and abs(m["odd"] - 1.56) < 1e-9 and abs(m["p_fair"] - 0.704) < 1e-9
assert [l["result"] for l in m["pernas"]] == ["perdida", "ganha"] and m["result"] == "perdida" and m["profit"] == -5.0
print("boletim múltiplo ok")

# --- odds registadas (preço da casa vs probabilidade) ---
bets_action({"action": "odd", "game_id": "P1-19/10/2026-Porto", "sel": "esp:y-4.5", "label": "Menos de 4,5 amarelos", "market": "Cartões",
             "book": "22bet", "odd": "1.20", "p": "0.80", "kickoff": "2026-10-19T18:00:00+01:00"})
for bad in ({"odd": "1"}, {"sel": "x"}, {"p": "1.5"}, {"book": ""}):
    try:
        bets_action({"action": "odd", "game_id": "g", "sel": "esp:y-4.5", "book": "22bet", "odd": "1.3", "p": "0.8", **bad}); raise SystemExit("aceitou odd inválida")
    except ValueError:
        pass
o = {(x["mercado"], x["casa"]): x for x in bets_report()["odds"]}[("Cartões", "22bet")]
assert o["n"] == 2 and abs(o["odd"] - 1.25) < 1e-3 and o["valor"] == 0.5  # perna do boletim 1,30 x 0,80 tem valor; 1,20 não
print("odds ok")

# --- módulos ao vivo (testes próprios) e apostas abertas por jogo ---
import avisos, live, onzes
live._self_test(); onzes._self_test(); avisos._self_test()
import elo; elo._self_test()
from server import db, open_bet_games
og = open_bet_games(db())
assert all("-" in k and v for k, v in og.items())
print("ao vivo, onzes e avisos ok")

# --- maior risco: odd mínima 1,80–2,50, primeiro as que já têm valor ---
from server import risco
mk = lambda sel, p, best, edge: {"sel": sel, "label": sel, "market": "m", "p": p, "fair_odd": round(1 / p, 2), "min_odd": round(1.02 / p, 2),
                                 "best_odd": best, "best_book": "Bet365", "edge": edge}
gr = {"id": "x", "home": "A", "away": "B", "kickoff": "2026-10-19T20:00:00+01:00", "league": "L", "minutes_to_ko": 600,
      "markets": [{"selections": [mk("a", 0.50, 2.00, -0.0), mk("b", 0.48, 2.20, 0.056), mk("c", 0.70, 1.50, 0.05), mk("d", 0.30, 3.5, 0.05)]}]}
rk = risco([gr, {**gr, "id": "y", "minutes_to_ko": -10}], None)
assert [r["sel"] for r in rk] == ["b", "a"] and rk[0]["valor"] and not rk[1]["valor"], rk
print("risco ok")

# --- lembrete a 30 min: aposta do dia com valor ainda não registada ---
import json as _json
from datetime import timedelta
from server import lembretes, MODEL_VERSION
con = db()
t0 = datetime(2026, 10, 20, 19, 40, tzinfo=TZ)
gl = {"id": "P1-20/10/2026-Porto", "home": "Porto", "away": "Arouca", "kickoff": (t0 + timedelta(minutes=20)).isoformat(), "markets": [], "minutes_to_ko": 20, "league": "L"}
con.execute("insert into published values(?,?,?,?,?,?)", ("2026-10-20", gl["id"], 0, _json.dumps({"game_id": gl["id"], "sel": "esp:y-4.5", "label": "Menos de 4,5 amarelos", "p": 0.8, "min_odd": 1.28}), t0.isoformat(), MODEL_VERSION))
con.commit()
lr = lembretes(con, [gl], t0)
assert len(lr) == 1 and lr[0]["minutos"] == 20 and lr[0]["porque"] == "aposta do dia", lr
assert lembretes(con, [gl], t0 - timedelta(minutes=30)) == []  # ainda falta mais de meia hora
bets_action({"action": "add", "div": "P1", "date": "20/10/2026", "home": "Porto", "away": "Arouca", "kickoff": gl["kickoff"], "sel": "esp:y-4.5",
             "label": "Menos de 4,5 amarelos", "market": "Cartões", "book": "Betclic", "odd": "1.3", "stake": "2", "p_fair": "0.8"})
assert lembretes(db(), [gl], t0) == []  # já registada: não lembra
print("lembretes ok")

# --- acerto por equipa: apostas fechadas contam para as duas equipas do jogo ---
from server import teams_report
tr = {x["equipa"]: x for x in teams_report(db())["equipas"]}
assert tr["Sp Braga"]["apostas"]["n"] >= 1 and tr["Porto – Arouca"]["apostas"]["n"] >= 1, tr.get("Sp Braga")  # "Sp Braga" ganha; amarelos = jogo
assert tr["Gil Vicente"]["apostas"]["n"] == 0 if "Gil Vicente" in tr else True
assert all(set(x) >= {"hist", "previsoes", "apostas"} for x in tr.values())
print("equipas ok")

# --- exportar CSV ---
from server import bets_csv
c = bets_csv()
assert c.startswith("﻿id;criada;tipo") and "perna" in c and "Porto - Arouca" in c
print("csv ok")

# --- CLV por mercado: 30 apostas com CLV −3% põem o mercado em pausa ---
from server import clv_markets
con = db()
for i in range(30):
    con.execute("insert into bets(created, div, date, home, away, kickoff, sel, label, market, book, odd, stake, result, clv) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-10-01", "E0", "01/10/2026", "A", "B", "2026-10-01T15:00", "1x2:1", "A", "Resultado (1X2)", "Betclic", 2.0, 1, "perdida", -0.03))
con.commit()
cm = {x["mercado"]: x for x in clv_markets(con)}
assert cm["Resultado"]["pausa"] and cm["Resultado"]["n"] >= 30, cm
print("clv por mercado ok")

# --- histórico: boletim publicado conta certas pelas previsões fechadas ---
from server import track_record
con = db()
con.execute("insert into preds(game_id, name, key, label, div, date, home, away, kickoff, p, p_raw, outcome) values(?,?,?,?,?,?,?,?,?,?,?,?)",
            (gl["id"], "Amarelos: menos de", "y-", "Menos de 4,5 amarelos", "P1", "20/10/2026", "Porto", "Arouca", gl["kickoff"], 0.8, 0.8, 1))
con.execute("update published set pick=? where day='2026-10-20'", (_json.dumps({"game_id": gl["id"], "name": "Amarelos: menos de", "sel": "esp:y-4.5"}),))
con.commit()
h = track_record(con)
assert h["dias"][0]["dia"] == "2026-10-20" and h["dias"][0]["certas"] == 1 and h["app"][0]["n"] >= 1, h
print("histórico ok")

# --- fecho pelo resultado final da ESPN (no próprio dia) ---
import live as _live
from server import espn_return
ev = {"id": "1", "status": {"type": {"state": "post", "name": "STATUS_FULL_TIME", "shortDetail": "FT"}, "displayClock": "90'", "period": 2},
      "competitions": [{"competitors": [{"homeAway": "home", "score": "0", "team": {"id": "a", "displayName": "Málaga"}, "statistics": [{"name": "wonCorners", "displayValue": "4"}]},
                                        {"homeAway": "away", "score": "2", "team": {"id": "b", "displayName": "Real Sociedad"}, "statistics": [{"name": "wonCorners", "displayValue": "3"}]}],
                        "details": [{"scoringPlay": True, "team": {"id": "b"}, "clock": {"displayValue": "3'"}}, {"scoringPlay": True, "team": {"id": "b"}, "clock": {"displayValue": "26'"}},
                                    {"yellowCard": True, "team": {"id": "b"}, "clock": {"displayValue": "37'"}}]}]}
_live.scoreboard = lambda div, day: [ev]
leg = lambda sel, label, line=None, odd=1.5: {"div": "SP1", "date": "18/10/2026", "home": "Malaga", "away": "Sociedad", "sel": sel, "label": label, "line": line, "odd": odd}
assert abs(espn_return(leg("esp:ht+0.5", "Há golo na 1.ª parte", odd=1.275)) - 0.275) < 1e-9
assert espn_return(leg("esp:hs", "Malaga marca")) == -1.0
assert espn_return(leg("esp:y-5.5", "Menos de 5,5 amarelos", 5.5)) == 0.5
assert espn_return(leg("1x2:2", "Sociedad ganha", odd=2.0)) == 1.0
assert espn_return({**leg("esp:hs", "x"), "home": "Barcelona", "away": "Girona"}) is None  # outro jogo
ev["status"]["type"]["state"] = "in"
ev["status"]["type"]["name"] = "STATUS_FIRST_HALF"; ev["status"]["period"] = 1; ev["status"]["displayClock"] = "30'"
assert abs(espn_return(leg("esp:ht+0.5", "Há golo na 1.ª parte", odd=1.275)) - 0.275) < 1e-9  # golo aos 3': já é certo
assert espn_return(leg("esp:hs", "Malaga marca")) is None  # ainda pode marcar
assert espn_return(leg("1x2:2", "Sociedad ganha", odd=2.0)) is None  # resultado só no fim
print("fecho ESPN ok")

# linha-alvo 74–80% e preço aprendido: com ≥40 odds e a casa a pagar acima do justo, esse mercado passa à frente
from consultor import selecao_especialista
esp = lambda gid, p, key: {"id": gid, "minutes_to_ko": 60, "kickoff": "2026-10-19T20:00",
                           "especialista": [{"key": key, "p": p, "family": "X", "label": "L", "min_odd": round(1.02 / p, 2)}]}
jogos = [esp("a", 0.79, "y-4.5"), esp("b", 0.75, "c+8.5"), esp("c", 0.83, "ht+0.5")]
assert [x["game_id"] for x in selecao_especialista(jogos, "2026-10-19")["apostas"]] == ["a", "b"]  # 83% fica de fora
assert [x["game_id"] for x in selecao_especialista(jogos, "2026-10-19", precos={"esp:c+": (50, 0.06)})["apostas"]] == ["b", "a"]
assert [x["game_id"] for x in selecao_especialista(jogos, "2026-10-19", precos={"esp:c+": (10, 0.06)})["apostas"]] == ["a", "b"]
assert selecao_especialista([esp("d", 0.77, "g2+0.5")], "2026-10-19")["apostas"] == []  # não existe sempre na 22bet

# taças europeias: sem cantos nem 2.ª parte (não testados), percentagens com a correção europeia
import json as _js, os as _os
from consultor import especialista as _esp
_M = _js.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "modelos.json")))
assert _M["uefa"]["jogos"] >= 500 and {"y-", "y+", "hy-", "ht+", "hs", "as", "dc"} <= set(_M["uefa"])
