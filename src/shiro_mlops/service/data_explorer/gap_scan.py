"""Find a dataset window's missing slots and gap members from its `GapPolicy`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from shiro_mlops.service.data_explorer.datasets.definition import Dataset, GapPolicy
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time
from shiro_mlops.service.data_explorer.values import row_time


@dataclass(frozen=True)
class GapScan:
    """The gaps of one dataset under a request's filters; only narrowing filters apply."""

    db: ExplorerDb
    dataset: Dataset
    filters: Mapping[str, Any] = field(default_factory=dict)

    @property
    def policy(self) -> GapPolicy:
        if self.dataset.gaps is None:
            raise ValueError(f"dataset {self.dataset.id} declares no gap policy")
        return self.dataset.gaps

    def due_missing_slots(self, window: TimeWindow, now: datetime) -> list[str]:
        """Missing slots of the window that have happened by `now` and are due, ascending."""
        elapsed_end = min(window.end, now)
        if elapsed_end < window.start:
            return []
        return self.missing_slots(
            TimeWindow(window.start, elapsed_end), due_by=now - self.policy.slot_lag
        )

    def missing_slots(self, window: TimeWindow, *, due_by: datetime | None = None) -> list[str]:
        """Each expected slot from the first at or after `window.start` that no row fills."""
        policy, cadence = self.policy, self.dataset.cadence
        present = self.present_members(window)
        last = window.end if due_by is None else min(window.end, due_by)
        first = pd.Timestamp(window.start).ceil(cadence)
        missing: list[str] = []
        for timestamp in pd.date_range(first, last, freq=cadence):
            slot = timestamp.to_pydatetime()
            label = format_taiwan_time(slot)
            if policy.members is None:
                if slot not in present:
                    missing.append(label)
                continue
            absent = self.absent_members(present.get(slot, set()))
            if policy.members.listed:
                missing.extend(f"{label}:{member}" for member in absent)
            elif absent:
                missing.append(label)
        return missing

    def present_members(self, window: TimeWindow) -> dict[datetime, set[str]]:
        """The slots rows fill inside the window, each with the gap members present in it."""
        policy, dataset = self.policy, self.dataset
        clauses, params = self.db.time_window(dataset.time_column, window)
        scope_clauses, scope_params = dataset.gap_clauses(self.db, self.filters)
        member = policy.members.column if policy.members is not None else None
        columns = dataset.time_column if member is None else f"{dataset.time_column}, {member}"
        rows = self.db.fetch(
            f"SELECT DISTINCT {columns} FROM {dataset.relation} "
            f"WHERE {' AND '.join([*clauses, *scope_clauses])}",
            {**params, **scope_params},
        )
        present: dict[datetime, set[str]] = {}
        for row in rows:
            moment = row_time(row, dataset.time_column)
            slot = (
                moment
                if policy.exact_instant
                else pd.Timestamp(moment).floor(dataset.cadence).to_pydatetime()
            )
            members = present.setdefault(slot, set())
            if member is not None:
                members.add(str(row[member]))
        return present

    def absent_members(self, found: set[str]) -> list[str]:
        """Expected members missing from one slot."""
        expected = self.dataset.expected_gap_members(self.filters)
        return [member for member in expected if member not in found]
