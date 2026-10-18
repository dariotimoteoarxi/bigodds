"""Meteorologia no dia do jogo (chuva, vento, temperatura) ajuda a prever golos, cantos e amarelos?

Estádio de cada equipa atual: ESPN (cidade do estádio num jogo em casa). Coordenadas e tempo histórico diário:
Open-Meteo (grátis, sem conta). Mesmo protocolo do especialista_contexto.py (treino 2021/22–2024/25, teste
2025/26–2026/27). Equipas que já não estão nas 6 ligas ficam de fora (sem estádio conhecido).
Uso: python3 especialista_meteo.py
"""
import difflib, json, math, os, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import date, timedelta
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "app"))
import especialista_v2 as v2  # noqa: E402
import live  # noqa: E402
from arbitros import norm  # noqa: E402
from especialista_contexto import evaluate  # noqa: E402

CACHE = os.path.join(HERE, "app", "data", "espn")
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/"


def get(url, path=None):
    if path and os.path.exists(path):
        return json.load(open(path))
    for tries in range(8):
        try:
            data = live._get(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)"}))
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or tries == 7:
                raise
            time.sleep(70)  # Open-Meteo limita pedidos por minuto: espera e tenta outra vez
    time.sleep(1.0 if "open-meteo" in url else 0.25)
    if path:
        json.dump(data, open(path, "w"))
    return data


def venues():
    """{(liga, nome ESPN): (cidade, país)} das equipas atuais, a partir de um jogo em casa de cada uma."""
    path = os.path.join(CACHE, "estadios.json")
    if os.path.exists(path):
        return {tuple(k.split("|")): tuple(v) for k, v in json.load(open(path)).items()}
    out = {}
    for div, lg in live.SLUG.items():
        teams = get(BASE.format(lg=lg) + "teams")["sports"][0]["leagues"][0]["teams"]
        for t in (x["team"] for x in teams):
            sched = get(BASE.format(lg=lg) + f"teams/{t['id']}/schedule").get("events", [])
            home = next((e for e in sched if any(c["homeAway"] == "home" and c["team"]["id"] == t["id"] for c in e["competitions"][0]["competitors"])), None)
            if not home:
                continue
            addr = get(BASE.format(lg=lg) + f"summary?event={home['id']}").get("gameInfo", {}).get("venue", {}).get("address", {})
            if addr.get("city"):
                out[(div, t["displayName"])] = (addr["city"], addr.get("country", ""))
    json.dump({"|".join(k): v for k, v in out.items()}, open(path, "w"), ensure_ascii=False)
    return out


def coords(city, country):
    r = get("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": city, "count": 5, "language": "en"}))
    res = r.get("results") or []
    hit = next((x for x in res if country and x.get("country", "").lower() == country.lower()), res[0] if res else None)
    return (hit["latitude"], hit["longitude"]) if hit else None


def weather(lat, lon, key):
    path = os.path.join(CACHE, f"meteo_{key}.json")
    end = (date.today() - timedelta(days=3)).isoformat()
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "start_date": "2021-07-01", "end_date": end, "timezone": "Europe/London",
                                "daily": "precipitation_sum,wind_speed_10m_max,temperature_2m_max"})
    d = get("https://archive-api.open-meteo.com/v1/archive?" + q, path)["daily"]
    return {t: (p, w, tm) for t, p, w, tm in zip(d["time"], d["precipitation_sum"], d["wind_speed_10m_max"], d["temperature_2m_max"])}


def main():
    D = v2.build()
    D = D[D.S != "2021"].reset_index(drop=True)
    fd = {(r.L, r.home) for r in D.itertuples()}
    W = {}
    for (div, name), (city, country) in venues().items():
        cands = {norm(t): t for L, t in fd if L == div}
        hit = difflib.get_close_matches(norm(name), list(cands), n=1, cutoff=0.6)
        c = coords(city, country)
        if hit and c:
            W[(div, cands[hit[0]])] = weather(*c, key=f"{div}_{norm(name).replace(' ', '_')}")
    print("equipas com tempo:", len(W), "de", len({t for t in fd if t[0] in live.SLUG}))
    rec = []
    for r in D.itertuples():
        w = W.get((r.L, r.home), {}).get(r.dt.strftime("%Y-%m-%d"))
        rec.append({"rain": math.log1p(w[0]), "wind": w[1] / 10, "temp": (w[2] - 18) / 10} if w and None not in w else {})
    D = pd.concat([D, pd.DataFrame(rec)], axis=1).dropna(subset=["rain"]).reset_index(drop=True)
    print(f"jogos com tempo: {len(D)} · dias de chuva forte (>5 mm): {int((D.rain > math.log1p(5)).sum())}")
    NEW = {"ht": ["rain", "wind"], "g2": ["rain", "wind"], "hg": ["rain", "wind"], "ag": ["rain", "wind"],
           "c": ["rain", "wind"], "y": ["rain", "temp"]}
    print(evaluate(D, NEW).to_string(index=False))


if __name__ == "__main__":
    main()
