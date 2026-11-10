from datetime import date

from app import db, stats


def test_streak():
    assert stats.streak([3, 3, 3], 3) == 3
    assert stats.streak([3, 0, 4, 3], 3) == 3
    assert stats.streak([3, 0, 3, 3], 3) == 2
    assert stats.streak([3, 0, 0, 4], 3) == 1
    assert stats.streak([3, 3, 1], 3) == 2
    assert stats.streak([3, 0, 1], 3) == 1
    assert stats.streak([0], 3) == 0


def test_longest_run():
    assert stats.longest_run([3, 3, 0, 3, 3, 3, 3, 0], 3) == 4


def test_week_totals():
    days = [date(2026, 11, 2), date(2026, 11, 8), date(2026, 11, 9)]
    assert stats.week_totals(days, date(2026, 11, 9)) == [2, 1]
    assert stats.week_totals([], date(2026, 11, 9)) == [0]
    assert stats.week_totals([date(2026, 12, 1)], date(2026, 11, 9)) == [0]  # entries all after today


def test_savings_and_achievements():
    assert stats.savings(10, 25, 6) == 190
    assert [n for n, ok in stats.achievements(1, 1, 0) if ok] == ["First cook"]


def test_connect_creates_schema_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for _ in range(2):
        con = db.connect()
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
        con.close()
    assert "refreshed_at" in cols
    assert {"users", "sessions", "entries", "photos", "weights", "shares"} <= names


def test_net_calories():
    assert stats.net_calories(2000, 600, 100) == (600, 1400)
    assert stats.net_calories(2000, 800, 75) == (600, 1400)
    assert stats.net_calories(500, 900, 100) == (900, -400)
    assert stats.net_calories(1000, 0, 100) == (0, 1000)
    assert stats.net_calories(1000, 800, 0) == (0, 1000)
