"""No fim de cada execução, marca a seguinte (o horário automático do GitHub não está a disparar neste repositório).

Próxima marca de 5 minutos: às :00 e :30 a análise completa; entre as 10 e as 22 h (UTC) o ao vivo; fora dessas horas,
só a completa. Se já houver outra execução à espera ou a correr, não marca nada (para não haver duas cadeias).
Usa a chave interna do GitHub Actions (GH_TOKEN), que pode lançar workflow_dispatch.
"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta, timezone

REPO = os.environ["GITHUB_REPOSITORY"]
ME = os.environ.get("GITHUB_RUN_ID", "")


def next_slot(now):
    t = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    t += timedelta(minutes=(5 - t.minute % 5) % 5)
    while True:
        if t.minute % 30 == 0:
            return t, "completo"
        if 10 <= t.hour <= 22:
            return t, "aovivo"
        t += timedelta(minutes=5)


def others_waiting():
    out = subprocess.run(["gh", "run", "list", "-R", REPO, "--workflow", "bigodds.yml", "-L", "15", "--json", "status,databaseId"],
                         capture_output=True, text=True, check=True).stdout
    return any(r["status"] in ("queued", "waiting", "pending", "requested", "in_progress") and str(r["databaseId"]) != ME
               for r in json.loads(out))


def _self_test():
    t, m = next_slot(datetime(2026, 10, 18, 20, 41, tzinfo=timezone.utc))
    assert (t.minute, m) == (45, "aovivo"), (t, m)
    t, m = next_slot(datetime(2026, 10, 18, 20, 57, tzinfo=timezone.utc))
    assert (t.hour, t.minute, m) == (21, 0, "completo")
    t, m = next_slot(datetime(2026, 10, 19, 2, 3, tzinfo=timezone.utc))  # de madrugada: só a completa
    assert (t.hour, t.minute, m) == (2, 30, "completo")


if __name__ == "__main__":
    if "--teste" in sys.argv:
        _self_test()
        print("ok")
        sys.exit()
    if others_waiting():
        print("já há outra execução marcada: não duplico a cadeia")
        sys.exit()
    when, mode = next_slot(datetime.now(timezone.utc))
    wait = max(0, (when - datetime.now(timezone.utc)).total_seconds())
    print(f"próxima: {mode} às {when:%H:%M} UTC (daqui a {wait / 60:.0f} min)")
    time.sleep(wait)
    if others_waiting():  # alguém lançou entretanto (à mão ou o horário de reserva)
        print("entretanto apareceu outra execução: não duplico a cadeia")
        sys.exit()
    subprocess.run(["gh", "workflow", "run", "bigodds.yml", "-R", REPO, "-f", f"modo={mode}"], check=True)
