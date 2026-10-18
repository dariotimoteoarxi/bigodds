"""Árbitros da Serie A (API pública do site legaseriea.it) -> data/arbitros/I1.csv.

Uso: python3 recolher_arbitros_it.py [2025/26 ...]   (sem argumentos: 2023/24–2026/27; antes disso a API não tem nomes)
~1 pedido por segundo e cache em data/arbitros/cache_it/ (jogos terminados ficam guardados para sempre).
"""
import json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import arbitros  # noqa: E402

API = "https://api-sdp.legaseriea.it/v1/serie-a/football"
COMP = "serie-a::Football_Competition::ec93b94f74294dc98ab5bcfd67fc0d88"
SEASONS = ["2023/24", "2024/25", "2025/26", "2026/27"]
CACHE = os.path.join(arbitros.DIR, "cache_it")


def get(path, keep):
    file = os.path.join(CACHE, re.sub(r"[^a-z0-9]+", "_", path.lower())[-150:] + ".json")
    if keep and os.path.exists(file):
        return json.load(open(file))
    req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0 (Bigodds pessoal)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    time.sleep(1)
    if keep:
        os.makedirs(CACHE, exist_ok=True)
        json.dump(data, open(file, "w"))
    return data


def items(data):
    """A API embrulha as listas de formas diferentes: devolve a primeira lista de dicts que encontrar."""
    if isinstance(data, list):
        return data
    for v in (data or {}).values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
        if isinstance(v, dict):
            found = items(v)
            if found:
                return found
    return []


def season_ids():
    out = {}
    for s in items(get(f"/competitions/{COMP}/seasons", keep=False)):
        m = re.search(r"(20\d\d)\D+(?:20)?(\d\d)$", str(s.get("seasonName") or ""))
        sid = s.get("seasonId") or s.get("id")
        if m and sid:
            out[f"{m.group(1)}/{m.group(2)[-2:]}"] = sid
    return out


def referee(facts):
    for r in (facts or {}).get("referees") or []:
        if isinstance(r, dict) and r.get("role") == "Referee":
            name = " ".join(x for x in (r.get("mediaFirstName"), r.get("mediaLastName")) if x)
            return name or r.get("shortName") or ""
    return ""


def season_rows(label, sid, upcoming_only=False):
    out = []
    today = time.strftime("%Y-%m-%d")
    for m in get(f"/seasons/{sid}/matches", keep=False)["matches"]:
        mid = m.get("matchId") or m.get("id")
        date = str(m.get("matchDateLocal") or m.get("matchDate") or "")[:10]
        home = (m.get("home") or {}).get("shortName") or (m.get("home") or {}).get("name") or ""
        away = (m.get("away") or {}).get("shortName") or (m.get("away") or {}).get("name") or ""
        finished = bool(date) and date < today  # jogos já disputados: o árbitro não muda, fica em cache
        if upcoming_only and finished:
            continue
        try:
            facts = get(f"/seasons/{sid}/match/{mid}/matchfacts", keep=finished)
            ref = referee(facts)
        except Exception as e:
            print(label, mid, e, file=sys.stderr)
            ref = ""
        out.append({"season": label, "round": m.get("roundName") or "", "date": date,
                    "home": home, "away": away, "referee": ref})
    return out


if __name__ == "__main__":
    wanted = sys.argv[1:] or SEASONS
    ids = season_ids()
    print("épocas encontradas:", {k: v[-8:] for k, v in ids.items()}, flush=True)
    rows = [r for r in arbitros.load("I1") if r["season"] not in wanted]
    for s in wanted:
        if s not in ids:
            print("época não encontrada:", s, file=sys.stderr)
            continue
        rows += season_rows(s, ids[s])
        arbitros.save(rows, "I1")
        print(s, "ok", sum(1 for r in rows if r["season"] == s and r["referee"]), "com árbitro", flush=True)
