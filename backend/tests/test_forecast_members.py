"""Point-in-time index membership (backend/forecast/members.py): the Picks study ranks and fires only
among each day's own index members, so stocks that left still count and stocks that joined late do not."""

from datetime import date

import pandas as pd
import pytest

from backend.forecast import members, setups, study
from backend.tests.test_forecast_picks import _frames

pytestmark = pytest.mark.real_members


def test_each_day_takes_the_latest_list_on_or_before_it(monkeypatch):
    monkeypatch.setattr(members, "snapshots", lambda: (
        (date(2022, 3, 1), frozenset({"S0", "S1"})), (date(2022, 6, 1), frozenset({"S1", "S2"}))))
    days = pd.bdate_range("2022-01-03", "2022-07-01")
    m = members.mask(days, ["S0", "S1", "S2", "S3"])
    assert m.loc["2022-01-03"].to_dict() == {"S0": True, "S1": True, "S2": False, "S3": False}  # before the first: first
    assert m.loc["2022-05-31"].to_dict() == {"S0": True, "S1": True, "S2": False, "S3": False}
    assert m.loc["2022-06-01"].to_dict() == {"S0": False, "S1": True, "S2": True, "S3": False}


def test_the_committed_lists_hold_stocks_that_left():
    assert members.ever() >= {"HDFC", "DHFL", "JETAIRWAYS"}
    assert members.snapshots()[0][0] < date(2009, 1, 1)  # covers the study's first bars


def test_fires_and_ranks_are_only_among_members():
    t = setups.table(_frames(n=40))
    out = [f"S{i}" for i in range(20)]
    t["member"] = pd.DataFrame(True, index=t["close"].index, columns=t["close"].columns)
    t["member"][out] = False
    s = setups.BY_NAME["momentum_vol_60"]
    results, fires = study.run(t, [s])
    f = fires[s.name]
    days = f.index[f.notna().any(axis=1)]
    assert len(days) and f[out].isna().all().all()
    assert all(f.loc[d].notna().sum() == 2 for d in days)  # 20 members -> top tenth is 2, not 4 of 40
    assert study.every_month(t)[out].isna().all().all()


def test_build_moves_old_symbols_to_today_s(tmp_path):
    (tmp_path / "n200_20180315000000.csv").write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\n" + "".join(f"C{i},X,S{i},EQ,I{i}\n" for i in range(99))
        + "Old Co,X,OLDSYM,EQ,I\n")
    (tmp_path / "cnx100_20100102000000.csv").write_text(
        "\nConstituents list of CNX 100\n\nCompany Name,Industry,Symbol,Series,ISIN Code\n"
        + "".join(f"C{i},X,T{i},EQ,I{i}\n" for i in range(100)))
    (tmp_path / "cnx100_20190101000000.csv").write_text(  # after the first 200 list: dropped
        "Company Name,Industry,Symbol,Series,ISIN Code\n" + "".join(f"C{i},X,U{i},EQ,I{i}\n" for i in range(100)))
    changes = tmp_path / "symbolchange.csv"
    changes.write_text("NAME OF THE COMPANY,OLD SYMBOL,NEW SYMBOL,EFFECTIVE DATE\nOld,OLDSYM,MID,1-JAN-2019\nOld,MID,NEWSYM,1-JAN-2020\n")
    rows = members.build(tmp_path, changes)
    assert {d for d, _ in rows} == {date(2010, 1, 2), date(2018, 3, 15)}
    assert (date(2018, 3, 15), "NEWSYM") in rows and not any(s == "OLDSYM" for _, s in rows)
