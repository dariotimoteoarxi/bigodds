"""Recolha completa das nomeações de árbitros da Liga Portugal -> data/arbitros/P1.csv.

Uso: python3 recolher_arbitros_pt.py [época ...]   (ex.: 20262027; sem argumentos recolhe 2021/22–2026/27)
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
import arbitros  # noqa: E402

SEASONS = ["20212022", "20222023", "20232024", "20242025", "20252026", "20262027"]

if __name__ == "__main__":
    seasons = sys.argv[1:] or SEASONS
    rows = [r for r in arbitros.load() if r["season"] not in seasons]
    for s in seasons:
        for rnd in range(1, 35):
            try:
                rows += arbitros.to_rows(s, rnd, arbitros.fetch(s, rnd))
            except Exception as e:  # jornada inexistente ou falha de rede: segue
                print(f"{s} jornada {rnd}: {e}", file=sys.stderr)
    arbitros.save(rows)
    print(f"{len(rows)} jogos gravados em {arbitros.CSV}")
