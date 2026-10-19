"""No fim de cada execução, marca a seguinte (o horário automático do GitHub não está a disparar neste repositório).

Próxima marca de 5 minutos: às :00 e :30 a análise completa; entre as 10 e as 22 h (UTC) o ao vivo; fora dessas horas,
só a completa. Só a execução mais recente continua a cadeia: se houver uma criada depois desta ainda por acabar, esta
não marca nada (assim nunca há duas cadeias e, ao contrário de antes, duas execuções nunca se travam uma à outra).
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


def newer_running(runs, me):
    """Há uma execução criada depois desta e ainda por acabar? Então é ela que continua a cadeia."""
    mine = next((r["createdAt"] for r in runs if str(r["databaseId"]) == me), "")
    return any(str(r["databaseId"]) != me and r["status"] != "completed" and r["createdAt"] > mine for r in runs)


def others_waiting():
    out = subprocess.run(["gh", "run", "list", "-R", REPO, "--workflow", "bigodds.yml", "-L", "15", "--json", "status,databaseId,createdAt"],
                         capture_output=True, text=True, check=True).stdout
    return newer_running(json.loads(out), ME)


def _self_test():
    t, m = next_slot(datetime(2026, 10, 18, 20, 41, tzinfo=timezone.utc))
    assert (t.minute, m) == (45, "aovivo"), (t, m)
    t, m = next_slot(datetime(2026, 10, 18, 20, 57, tzinfo=timezone.utc))
    assert (t.hour, t.minute, m) == (21, 0, "completo")
    t, m = next_slot(datetime(2026, 10, 19, 2, 3, tzinfo=timezone.utc))  # de madrugada: só a completa
    assert (t.hour, t.minute, m) == (2, 30, "completo")
    # 19/10: a reserva das 15:32 e a cadeia travaram-se uma à outra; agora só a mais recente decide
    runs = [{"databaseId": 2, "status": "in_progress", "createdAt": "2026-10-19T15:35:02Z"},
            {"databaseId": 1, "status": "in_progress", "createdAt": "2026-10-19T15:32:15Z"}]
    assert newer_running(runs, "1") and not newer_running(runs, "2")
    assert not newer_running([{"databaseId": 3, "status": "completed", "createdAt": "2026-10-19T16:00:00Z"}] + runs, "2")


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
