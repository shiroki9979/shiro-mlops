"""Offline unit tests for lab.regional_weights (public seam: regional_load_shares, main CLI)."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from lab.regional_weights import main as weights_main
from lab.regional_weights import regional_load_shares
from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    REGIONAL_SUPPLY_DEMAND_REGIONS,
    TaipowerRegionalSupplyDemandSnapshot,
)
from sqlalchemy import create_engine

START = datetime(2026, 10, 1)
END = datetime(2026, 10, 2)


def _sample(
    source_time: datetime,
    region_loads_wan_kw: tuple[float, ...],
    *,
    regions: tuple[str, ...] = REGIONAL_SUPPLY_DEMAND_REGIONS,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    return [
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=source_time,
            region=region,
            source_time=source_time,
            generation_wan_kw=None,
            load_wan_kw=load,
            raw_payload={},
        )
        for region, load in zip(regions, region_loads_wan_kw, strict=True)
    ]


def test_shares_are_each_region_load_over_the_four_region_total_across_samples() -> None:
    snapshots = [
        *_sample(START, (1000.0, 600.0, 300.0, 100.0)),
        *_sample(START + timedelta(minutes=10), (1400.0, 1000.0, 500.0, 100.0)),
    ]

    shares = regional_load_shares(snapshots, start=START, end=END)

    assert shares.sample_count == 2
    assert shares.shares == pytest.approx({"北部": 0.48, "中部": 0.32, "南部": 0.16, "東部": 0.04})


def test_samples_missing_a_region_or_outside_the_period_are_excluded() -> None:
    snapshots = [
        *_sample(START, (500.0, 300.0, 150.0, 50.0)),
        *_sample(START + timedelta(minutes=10), (9.0, 9.0, 9.0), regions=("北部", "中部", "南部")),
        *_sample(END, (9.0, 9.0, 9.0, 9.0)),
        *_sample(START - timedelta(minutes=10), (9.0, 9.0, 9.0, 9.0)),
    ]

    shares = regional_load_shares(snapshots, start=START, end=END)

    assert shares.sample_count == 1
    assert shares.shares == pytest.approx({"北部": 0.5, "中部": 0.3, "南部": 0.15, "東部": 0.05})


def test_period_without_complete_samples_is_rejected() -> None:
    snapshots = _sample(START, (9.0, 9.0, 9.0), regions=("北部", "中部", "南部"))

    with pytest.raises(ValueError, match="no complete four-region samples"):
        regional_load_shares(snapshots, start=START, end=END)


def test_east_share_is_spread_over_the_three_points_in_proportion() -> None:
    shares = regional_load_shares(_sample(START, (500.0, 300.0, 150.0, 50.0)), start=START, end=END)

    weights = shares.reference_point_weights()

    assert list(weights) == ["Taipei", "Taichung", "Kaohsiung"]
    assert weights == pytest.approx(
        {"Taipei": 0.5 / 0.95, "Taichung": 0.3 / 0.95, "Kaohsiung": 0.15 / 0.95}
    )
    assert sum(weights.values()) == pytest.approx(1.0)


def test_rounded_weights_still_sum_to_exactly_one() -> None:
    # 1/3 各自四捨五入為 0.33，總和 0.99；差額歸給最大權重。
    shares = regional_load_shares(_sample(START, (100.0, 100.0, 100.0, 30.0)), start=START, end=END)

    weights = shares.reference_point_weights(decimals=2)

    assert weights == {"Taipei": 0.34, "Taichung": 0.33, "Kaohsiung": 0.33}
    assert round(sum(weights.values()), 10) == 1.0


def test_cli_reads_stored_snapshots_and_prints_snapshot_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'weights.db'}")
    ensure_timescale_hypertables(engine)
    repository = TimeSeriesRepository(engine=engine)
    repository.upsert_regional_supply_demand_snapshots(_sample(START, (500.0, 300.0, 150.0, 50.0)))
    monkeypatch.setattr("lab.regional_weights.TimeSeriesRepository", lambda: repository)

    exit_code = weights_main(
        ["--start", "2026-10-01T00:00:00", "--end", "2026-10-02T00:00:00", "--decimals", "3"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "complete samples: 1" in output
    assert "--reference-points Taipei Taichung Kaohsiung --weights 0.526 0.316 0.158" in output
