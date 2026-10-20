"""Personal pace model: learns how long *this* student really takes.

After a deadline, the student logs actual hours. For each assignment type we model
log(actual / estimate) and shrink it toward the student's overall ratio, which is
itself shrunk toward 0 (no correction). This is a small empirical-Bayes model:

    r_i          = log(actual_i / estimate_i)
    global_mean  = sum(r) / (n + K_GLOBAL)
    type_mean_t  = (sum_t(r) + K_TYPE * global_mean) / (n_t + K_TYPE)
    multiplier_t = exp(type_mean_t)

With no data every multiplier is 1.0; each logged task moves it a little. The
evaluation (eval/evaluate.py) measures how much this lowers the error in hour
estimates over a simulated semester.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

K_GLOBAL = 2.0
K_TYPE = 3.0
MAX_ABS_LOG = math.log(4.0)  # ignore wild outliers beyond 4x either way


@dataclass
class PaceModel:
    global_mult: float
    by_type: dict[str, float]
    counts: dict[str, int]
    n: int

    def multiplier(self, kind: str) -> float:
        return self.by_type.get(kind, self.global_mult)

    def describe(self) -> list[str]:
        notes = []
        for kind, m in sorted(self.by_type.items(), key=lambda kv: -abs(math.log(kv[1]))):
            if self.counts.get(kind, 0) < 2 or abs(m - 1) < 0.1:
                continue
            direction = "longer" if m > 1 else "less time"
            pct = round(abs(m - 1) * 100)
            notes.append(f"You usually take {pct}% {direction} than estimated on {kind} "
                         f"({self.counts[kind]} logged).")
        return notes[:3]


def fit(history: list[tuple[str, float, float]]) -> PaceModel:
    """history: (type, estimated_hours, actual_hours) for completed tasks."""
    logs: dict[str, list[float]] = defaultdict(list)
    for kind, est, actual in history:
        if est and actual and est > 0 and actual > 0:
            r = max(-MAX_ABS_LOG, min(MAX_ABS_LOG, math.log(actual / est)))
            logs[kind].append(r)
    all_r = [r for rs in logs.values() for r in rs]
    g = sum(all_r) / (len(all_r) + K_GLOBAL)
    by_type = {k: math.exp((sum(rs) + K_TYPE * g) / (len(rs) + K_TYPE)) for k, rs in logs.items()}
    return PaceModel(math.exp(g), by_type, {k: len(v) for k, v in logs.items()}, len(all_r))


def effective_hours(task: dict, model: PaceModel | None) -> float:
    """The hours the forecast should use: the student's own number wins, then the pace-adjusted estimate."""
    if task.get("user_hours") is not None:
        return float(task["user_hours"])
    base = float(task["base_hours"])
    return round(base * (model.multiplier(task["type"]) if model else 1.0), 2)
