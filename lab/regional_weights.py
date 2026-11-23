"""Weather reference-point weights from Taipower regional load shares (ADR-0012, TICKET-303).

Each region's share is its load summed over the period's valid samples, divided by
the four-region total. The east has no reference point, so its share is spread over
the three points in proportion, which is the same as renormalizing the three shares.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from shiro_mlops.data.hourly_actual_load import complete_region_loads
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    REGIONAL_SUPPLY_DEMAND_REGIONS,
    TaipowerRegionalSupplyDemandSnapshot,
)

from lab.timestamps import normalize_taiwan_timestamp

# 北中南三區各自對應的氣象代表點（GitHub #95）；東部沒有代表點。
REGION_REFERENCE_POINTS: Mapping[str, str] = {
    "北部": "Taipei",
    "中部": "Taichung",
    "南部": "Kaohsiung",
}


@dataclass(frozen=True)
class RegionalLoadShares:
    """Four-region load shares over the source-time period ``[start, end)``."""

    start: pd.Timestamp
    end: pd.Timestamp
    sample_count: int
    shares: dict[str, float]

    def reference_point_weights(
        self,
        region_points: Mapping[str, str] = REGION_REFERENCE_POINTS,
        *,
        decimals: int | None = None,
    ) -> dict[str, float]:
        """Weights per reference point, summing to 1; unmapped regions spread in proportion.

        With ``decimals``, each weight is rounded and the rounding residual goes to the
        largest weight, so the TOML values still sum to exactly 1 at that precision.
        """
        mapped_total = sum(self.shares[region] for region in region_points)
        weights = {
            point: self.shares[region] / mapped_total for region, point in region_points.items()
        }
        if decimals is None:
            return weights
        rounded = {point: round(weight, decimals) for point, weight in weights.items()}
        largest = max(rounded, key=rounded.__getitem__)
        rounded[largest] = round(rounded[largest] + 1.0 - sum(rounded.values()), decimals)
        return rounded


def regional_load_shares(
    snapshots: Iterable[TaipowerRegionalSupplyDemandSnapshot],
    *,
    start: datetime | pd.Timestamp | str,
    end: datetime | pd.Timestamp | str,
) -> RegionalLoadShares:
    """Load share of each region over valid samples whose source_time is in ``[start, end)``.

    Valid samples follow the hourly actual load derivation: all four regions present,
    and a source_time captured in several observation slots counts once.
    """
    period_start = normalize_taiwan_timestamp(start)
    period_end = normalize_taiwan_timestamp(end)
    samples = [
        region_loads
        for source_time, region_loads in complete_region_loads(snapshots).items()
        if period_start <= pd.Timestamp(source_time) < period_end
    ]
    if not samples:
        raise ValueError(
            f"no complete four-region samples with source_time in "
            f"[{period_start.isoformat()}, {period_end.isoformat()})"
        )
    region_totals = {
        region: sum(sample[region] for sample in samples)
        for region in REGIONAL_SUPPLY_DEMAND_REGIONS
    }
    grand_total = sum(region_totals.values())
    return RegionalLoadShares(
        start=period_start,
        end=period_end,
        sample_count=len(samples),
        shares={region: total / grand_total for region, total in region_totals.items()},
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m lab.regional_weights",
        description=(
            "Compute weather reference-point weights from stored regional supply-demand "
            "snapshots over a source-time period [start, end)."
        ),
    )
    parser.add_argument("--start", required=True, help="Period start, Asia/Taipei ISO format.")
    parser.add_argument("--end", required=True, help="Period end (exclusive), Asia/Taipei ISO.")
    parser.add_argument(
        "--decimals", type=int, default=3, help="Round weights to this many decimals (default 3)."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    start = normalize_taiwan_timestamp(args.start)
    end = normalize_taiwan_timestamp(args.end)
    snapshots = TimeSeriesRepository().regional_supply_demand_store.fetch_by_source_time(
        start.to_pydatetime(), end.to_pydatetime()
    )
    shares = regional_load_shares(snapshots, start=start, end=end)
    weights = shares.reference_point_weights(decimals=args.decimals)
    print(f"period: [{shares.start.isoformat()}, {shares.end.isoformat()})")
    print(f"complete samples: {shares.sample_count}")
    for region, share in shares.shares.items():
        print(f"{region} share: {share:.4f}")
    for point, weight in weights.items():
        print(f"{point} weight: {weight}")
    values = " ".join(str(weight) for weight in weights.values())
    print(f"snapshot arguments: --reference-points {' '.join(weights)} --weights {values}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
