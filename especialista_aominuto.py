"""Leituras ao minuto: "ainda há golo / já não há golo" até ao intervalo e até ao fim, a partir do ritmo esperado.

Testa, em jogos reais de 2025/26 e 2026/27 (minutos dos golos da ESPN), se a probabilidade prevista a cada minuto
bate com o que aconteceu. 1.ª parte: ritmo antes do jogo (modelo ht); 2.ª parte: modelo do intervalo (sabe o resultado
aos 45'). Uso: python3 especialista_aominuto.py
"""
import difflib, gzip, json, math, os, re, sys, urllib.request
from datetime import datetime
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
from features import predict_mu  # noqa: E402
from live import SLUG  # noqa: E402

CACHE = os.path.join(HERE, "results", "espn_golos")
STOP1, STOP2 = 2, 4  # descontos médios assumidos (min)


def month(lg, y, m):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{lg}_{y}{m:02d}.json")
    if not os.path.exists(path):
        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{SLUG[lg]}/scoreboard?dates={y}{m:02d}&limit=400"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept-Encoding": "gzip"}), timeout=60) as r:
            raw = r.read()
        raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        open(path, "wb").write(raw)
    out = []
    for e in json.load(open(path, encoding="utf-8")).get("events", []):
        c = e["competitions"][0]
        if c["status"]["type"]["name"] != "STATUS_FULL_TIME":
            continue
        side = {x["homeAway"]: x for x in c["competitors"]}
        goals = []
        for d in c.get("details") or []:
            if d.get("scoringPlay"):
                mm = re.match(r"(\d+)'", d.get("clock", {}).get("displayValue", ""))
                if mm:
                    goals.append(int(mm.group(1)))
        if len(goals) != int(side["home"]["score"]) + int(side["away"]["score"]):
            continue  # golos sem minuto: fica de fora
        out.append({"L": lg, "day": datetime.fromisoformat(e["date"].replace("Z", "+00:00")).date(),
                    "home": side["home"]["team"]["displayName"], "away": side["away"]["team"]["displayName"],
                    "g1": sorted(x for x in goals if x <= 45), "g2": sorted(x for x in goals if x > 45)})
    return out


norm = lambda s: re.sub(r"\b(fc|cf|ac|as|ssc|sc|ss|us|afc|cd|ud|rc|club|calcio|de|la|1\.)\b", " ", s.lower()).strip()
sim = lambda a, b: difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()

def main():
    M = json.load(open(os.path.join(HERE, "app", "data", "modelos.json")))
    D = v2.build()
    D = D[D.S.isin({"2526", "2627"})].reset_index(drop=True)
    D["mu_ht"] = [predict_mu(M["models"]["ht"], r) for r in D.to_dict("records")]
    D["mu_g2"] = [predict_mu(M["models"]["g2"], r) for r in D.to_dict("records")]
    I = M["intervalo"]
    E = [g for lg in SLUG for y, m in [(2025, k) for k in range(8, 13)] + [(2026, k) for k in range(1, 11)] for g in month(lg, y, m)]
    rows = []
    for g in E:
        cand = D[(D.L == g["L"]) & (abs((pd.to_datetime(D.dt).dt.date - g["day"]).apply(lambda x: x.days)) <= 1)]
        if cand.empty:
            continue
        sc = cand.apply(lambda r: sim(r.home, g["home"]) + sim(r.away, g["away"]), axis=1)
        if sc.max() < 1.1:
            continue
        r = cand.loc[sc.idxmax()]
        ht = len(g["g1"])
        # 1.ª parte
        for mnt in range(10, 45, 5):
            lam = r.mu_ht * (45 + STOP1 - mnt) / 45
            rows.append({"S": r.S, "parte": 1, "min": mnt, "p_nao": math.exp(-lam), "nao": int(not any(x >= mnt for x in g["g1"]))})
        # 2.ª parte: modelo do intervalo com o resultado aos 45'
        h1 = sum(1 for x in g["g1"])  # golos ao intervalo (sem saber de quem: só o total e a diferença importam pouco aqui)
        x = {"log_mu": math.log(r.mu_g2), "ht_tot": ht, "ht_gd": 0, "fav_losing": 0.0}
        mu2 = math.exp(I["intercept"] + sum(c * x[k] for k, c in zip(I["cols"], I["coef"])))
        for mnt in range(50, 90, 5):
            lam = mu2 * (90 + STOP2 - mnt) / 45
            rows.append({"S": r.S, "parte": 2, "min": mnt, "p_nao": math.exp(-lam), "nao": int(not any(x >= mnt for x in g["g2"]))})
    R = pd.DataFrame(rows)
    print(f"{len(E)} jogos da ESPN · {R[R.parte == 1].shape[0] // 7} cruzados com o modelo")
    # calibração: ajusta em 2025/26, testa em 2026/27 (jogos que a calibração não viu)
    cal = {}
    for parte in (1, 2):
        P = R[R.parte == parte]
        tr = P.S == "2526"
        pts = v2.pav(P.p_nao[tr].values, P.nao[tr].values)
        R.loc[P.index, "p_cal"] = v2.cal_apply(pts, P.p_nao.values)
        cal[str(parte)] = [(round(a, 4), round(b, 4)) for a, b in v2.pav(P.p_nao.values, P.nao.values)]  # produção: tudo
    print("\n== Antes da calibração (todas as épocas) ==")
    bands(R, "p_nao")
    print("\n== Calibrado em 2025/26, teste em 2026/27 ==")
    bands(R[R.S == "2627"], "p_cal")
    M["aominuto"] = {"stop1": STOP1, "stop2": STOP2, "cal": cal}
    json.dump(M, open(os.path.join(HERE, "app", "data", "modelos.json"), "w"), indent=1)
    print("calibração ao minuto exportada para app/data/modelos.json")


def bands(R, col):
    out = []
    for parte in (1, 2):
        P = R[R.parte == parte]
        for side, p, y in (("já não há golo", P[col], P.nao), ("ainda há golo", 1 - P[col], 1 - P.nao)):
            for lo, hi in ((0.65, 0.70), (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.01)):
                k = (p >= lo) & (p < hi)
                if k.sum() >= 30:
                    out.append([f"{parte}.ª parte" if parte == 1 else "até ao fim", side, f"{lo:.0%}–{min(hi, 1):.0%}", int(k.sum()),
                                round(100 * p[k].mean(), 1), round(100 * y[k].mean(), 1)])
    print(pd.DataFrame(out, columns=["período", "leitura", "faixa", "n", "previsto %", "real %"]).to_string(index=False))


if __name__ == "__main__":
    main()
