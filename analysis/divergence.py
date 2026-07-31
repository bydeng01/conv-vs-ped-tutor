"""Three-evaluator divergence view (descriptive EXTENSION; decisions-log 2026-06-27).

Lines up the three post-hoc evaluators of the visible training tutor turns -- generic
**helpfulness** (analysis/judge.py, §9.4), **pedagogical quality** (analysis/judge_pedagogy.py,
the extension), and student **independence** (§9.3) -- and shows, per turn and per session,
where they AGREE and where they DIVERGE. The divergence is the substance of the J2 story:
the helpfulness signal can rate a turn high exactly where pedagogy and next-turn independence
rate it low.

This is DESCRIPTIVE / exploratory only. It is NOT a new inferential test and does not touch
the frozen §10 J1/J2 analysis or any frozen metric. It standardizes (z-scores) each signal
across the analyzed units so the three different scales are comparable, reports the per-unit
spread ("disagreement"), pairwise agreement (Pearson + Spearman rank), and the turns/sessions
where the evaluators most disagree.

Inputs are the tidy rows compute_metrics already builds:
  - per_turn:    helpfulness, pedagogy, next_turn_independence (True/False/None)
  - per_session: helpfulness_mean, pedagogy_mean, independence_ratio
A signal whose column is entirely empty (e.g. helpfulness when --judge-helpfulness was not
run) simply drops out; disagreement is computed over whatever signals are present (>=2).
"""
from __future__ import annotations

import math
from typing import Optional

# (signal key in the row, short label) for per-turn and per-session.
TURN_SIGNALS = (("helpfulness", "help"), ("pedagogy", "ped"),
                ("next_turn_independence", "indep"))
SESSION_SIGNALS = (("helpfulness_mean", "help"), ("pedagogy_mean", "ped"),
                   ("independence_ratio", "indep"))


def _as_float(v) -> Optional[float]:
    """Coerce a cell to float; True/False -> 1.0/0.0; None/'' -> None."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def zscores(xs: list[Optional[float]]) -> list[Optional[float]]:
    """Standardize the present values (mean 0, sample sd ddof=1); None passes through.
    With fewer than two present values, or zero spread, present values map to 0.0 (no
    information to standardize on)."""
    present = [x for x in xs if x is not None]
    if len(present) < 2:
        return [None if x is None else 0.0 for x in xs]
    mu = sum(present) / len(present)
    var = sum((x - mu) ** 2 for x in present) / (len(present) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return [None if x is None else 0.0 for x in xs]
    return [None if x is None else (x - mu) / sd for x in xs]


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _ranks(xs: list[float]) -> list[float]:
    """Average (fractional) ranks, ties shared -- for Spearman."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0          # 1-based average rank over the tie block
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def pairwise_agreement(rows: list[dict], signals) -> list[dict]:
    """Pearson + Spearman between each pair of signals, over the units where BOTH are
    present (paired complete cases)."""
    out = []
    keys = [k for k, _ in signals]
    labels = {k: lab for k, lab in signals}
    cols = {k: [_as_float(r.get(k)) for r in rows] for k in keys}
    for a_i in range(len(keys)):
        for b_i in range(a_i + 1, len(keys)):
            ka, kb = keys[a_i], keys[b_i]
            pairs = [(x, y) for x, y in zip(cols[ka], cols[kb])
                     if x is not None and y is not None]
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            out.append({
                "pair": f"{labels[ka]}~{labels[kb]}",
                "a": ka, "b": kb, "n": len(pairs),
                "pearson": _pearson(xs, ys), "spearman": _spearman(xs, ys),
            })
    return out


def annotate(rows: list[dict], signals, id_fields) -> list[dict]:
    """Return divergence rows: the raw signals, their z-scores, and a `disagreement`
    spread (max-min over the present z-scores; None with <2 present), plus which signal
    is highest / lowest. The z-scores are computed across ALL passed rows (the analyzed
    unit set), so they are comparable within this analysis run."""
    keys = [k for k, _ in signals]
    labels = {k: lab for k, lab in signals}
    zcols = {k: zscores([_as_float(r.get(k)) for r in rows]) for k in keys}

    out = []
    for i, r in enumerate(rows):
        zvals = {k: zcols[k][i] for k in keys}
        present = {k: z for k, z in zvals.items() if z is not None}
        if len(present) >= 2:
            hi = max(present, key=present.get)
            lo = min(present, key=present.get)
            disagreement = present[hi] - present[lo]
            pattern = f"{labels[hi]}>{labels[lo]}"
        else:
            hi = lo = disagreement = pattern = None
        rec = {f: r.get(f) for f in id_fields}
        rec.update({
            "raw": {k: _as_float(r.get(k)) for k in keys},
            "z": {labels[k]: zvals[k] for k in keys},
            "disagreement": disagreement,
            "highest": labels.get(hi) if hi else None,
            "lowest": labels.get(lo) if lo else None,
            "pattern": pattern,
        })
        out.append(rec)
    return out


def top_disagreements(div_rows: list[dict], k: int = 12) -> list[dict]:
    """The k units with the largest disagreement spread (descending)."""
    scored = [r for r in div_rows if r.get("disagreement") is not None]
    scored.sort(key=lambda r: r["disagreement"], reverse=True)
    return scored[:k]


def divergence_view(per_turn: list[dict], per_session: list[dict],
                    k: int = 12) -> dict:
    """Assemble the full descriptive divergence view for results/divergence_detail.json."""
    turn_div = annotate(per_turn, TURN_SIGNALS,
                        ("condition", "replicate_id", "problem_id", "turn_index"))
    session_div = annotate(per_session, SESSION_SIGNALS,
                           ("condition", "replicate_id", "run_id"))

    def _present(rows, signals):
        return {lab: sum(1 for r in rows if _as_float(r.get(key)) is not None)
                for key, lab in signals}

    return {
        "note": ("DESCRIPTIVE / exploratory extension (decisions-log 2026-06-27). Not a "
                 "§10 inferential test; does not change J1/J2. z-scores are standardized "
                 "within this analyzed unit set; disagreement = max-min over present "
                 "z-scores."),
        "signals_present_per_turn": _present(per_turn, TURN_SIGNALS),
        "signals_present_per_session": _present(per_session, SESSION_SIGNALS),
        "per_turn_agreement": pairwise_agreement(per_turn, TURN_SIGNALS),
        "per_session_agreement": pairwise_agreement(per_session, SESSION_SIGNALS),
        "per_turn": turn_div,
        "per_session": session_div,
        "top_turn_disagreements": top_disagreements(turn_div, k),
        "top_session_disagreements": top_disagreements(session_div, k),
    }
