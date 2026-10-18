import sqlite3
from datetime import datetime, timedelta, timezone
from logger import SCHEMA, closing, due

now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
h = timedelta(hours=1)
m = timedelta(minutes=1)

# sem jogos nas próximas 24 h não gasta créditos
assert not due(now, [now + 30 * h, now - h], None)
# primeira leitura de um jogo dentro da janela
assert due(now, [now + 20 * h], None)
# longe do jogo: de hora a hora
assert not due(now, [now + 10 * h], now - 30 * m)
assert due(now, [now + 10 * h], now - 60 * m)
# entre 3 h e 90 min: de 15 em 15 min
assert not due(now, [now + 2 * h], now - 10 * m)
assert due(now, [now + 2 * h], now - 15 * m)
# últimos 90 min: de 5 em 5 min (tolerância do cron)
assert due(now, [now + 60 * m], now - 5 * m + timedelta(seconds=20))
assert not due(now, [now + 60 * m], now - 3 * m)

# odd de fecho = última leitura antes do início, ignora leituras depois do apito
db = sqlite3.connect(":memory:")
db.executescript(SCHEMA)
ko = "2026-10-18T19:00:00+00:00"
db.execute("insert into events values('e1','soccer_epl','A','B',?)", (ko,))
for ts, price in [("2026-10-18T10:00:00+00:00", 2.10), ("2026-10-18T18:55:00+00:00", 1.95), ("2026-10-18T19:05:00+00:00", 1.50)]:
    db.execute("insert into snapshots values(?,?,?,?,?,?,?,?)", (ts, "e1", "betclic_fr", "h2h", "A", None, price, ts))
assert closing(db, "e1", "h2h", "betclic_fr") == [("A", None, 1.95, "2026-10-18T18:55:00+00:00")]
print("ok")
