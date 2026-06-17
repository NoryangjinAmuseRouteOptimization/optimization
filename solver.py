"""
solver.py -- guaranteed-feasible, time-safe baseline solver
===============================================================================

Motivation
----------
The provided baseline_greedy is NOT submission-viable on these instances: the
bench_solver harness shows it overruns the time limit by 3x+ and still returns
infeasible solutions (e.g. prob_21: 47s for a 15s limit, stage-3 infeasible).
On the server that scores -1 (timeout AND infeasible).  Before optimizing the
objective, the team needs a solver that is ALWAYS feasible and ALWAYS within the
time limit -- that alone turns likely -1 scores into a positive floor.

Guaranteed-feasibility construction
-----------------------------------
If, within a bay, no two blocks' time intervals overlap (the bay holds at most
one block at any instant), then:
  * Stage-4 spatial collisions are impossible (no co-present pair).
  * Stage-2/3 crane checks are trivial (bay empty at every entry and exit).
  * Stage-5 ordering is trivial (operations never conflict).
So a "one block at a time per bay" schedule is feasible for ANY in-bounds block
positions.  We place each block at the smallest valid position of an orientation
that fits the bay (the bay is empty when it enters, so any in-bounds position is
collision/crane free).

Scheduling to limit tardiness (parallel-machine list scheduling)
----------------------------------------------------------------
Each bay behaves as a single machine.  We process blocks in EDD order and assign
each to the bay that finishes it earliest, i.e. minimizes
    exit = max(release, bay_free_time) + processing,
breaking ties toward the more-preferred / less-loaded bay.  This greedily
balances the bays and keeps completion times (hence tardiness) low while
remaining trivially feasible.

This is an O(n * m) construction -- effectively instant -- so the time limit is
never at risk.  It is a floor to beat, not the final algorithm: allowing safe
coexistence (via placement.can_place) to cut tardiness is the next step (P2).
"""

from __future__ import annotations

import sys
import pathlib

# Make utils / placement importable whether called from repo root or elsewhere.
_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "baseline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from utils import Bay  # noqa: E402
import placement       # noqa: E402


def _build_operations(assignments: list[dict]) -> dict:
    """
    Build the {"operations": {time: [ops]}} dict from per-block assignments.
    EXIT ops sort before ENTRY ops at the same time; within a type, by block_id.
    (Self-contained copy so solver.py does not depend on baseline_greedy.)
    """
    buckets: dict[int, list[tuple]] = {}
    for a in assignments:
        te, tx = int(a["entry_time"]), int(a["exit_time"])
        buckets.setdefault(tx, []).append((0, "EXIT",  a["block_id"], a["bay_id"], None, None, None))
        buckets.setdefault(te, []).append((1, "ENTRY", a["block_id"], a["bay_id"], a["x"], a["y"], a["orient_idx"]))

    operations: dict[str, list[dict]] = {}
    for t in sorted(buckets):
        ops = sorted(buckets[t], key=lambda r: (r[0], r[2]))
        out = []
        for _, kind, bid, bay, x, y, oi in ops:
            op = {"type": kind, "block_id": bid, "bay_id": bay}
            if kind == "ENTRY":
                op["x"], op["y"], op["orient_idx"] = x, y, oi
            out.append(op)
        operations[str(t)] = out
    return operations


def _fitting_orientation(bay: Bay, geom: placement.GeometryCache, bid: int):
    """
    Return (orient_idx, x, y) for the smallest-area orientation of block bid that
    fits empty `bay`, placed at its smallest valid integer position.  None if no
    orientation fits this bay.
    """
    best = None
    for oi in range(geom.n_orient(bid)):
        g = geom.geom(bid, oi)
        b = placement.position_bounds(bay, g)
        if b is None:
            continue
        px_lo, _, py_lo, _ = b
        area = g.width * g.height
        if best is None or area < best[0]:
            best = (area, oi, max(0, px_lo), max(0, py_lo))
    if best is None:
        return None
    _, oi, x, y = best
    return oi, x, y


def solve(prob_info: dict, timelimit: float = 60.0) -> dict:
    """
    Guaranteed-feasible, time-safe solver (see module docstring).

    Returns a solution dict in the competition format.  Always feasible for
    well-formed instances and runs in O(n*m), so the time limit is never used up.
    """
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob_info["bays"])]
    blocks = prob_info["blocks"]
    n_bays = len(bays)
    geom = placement.GeometryCache(prob_info)

    # Bay weights for a light load-balancing tie-break: u_j = avg_area / area_j.
    areas = [b.width * b.height for b in bays]
    avg_area = sum(areas) / n_bays
    u = [avg_area / a for a in areas]

    # Precompute, per block, the bays it fits and a placement for each.
    fit: dict[int, dict[int, tuple]] = {}
    for bid in range(len(blocks)):
        per_bay = {}
        for j, bay in enumerate(bays):
            res = _fitting_orientation(bay, geom, bid)
            if res is not None:
                per_bay[j] = res
        fit[bid] = per_bay  # {bay_id: (orient_idx, x, y)}

    # EDD order (ties: shortest processing first).
    order = sorted(range(len(blocks)),
                   key=lambda i: (blocks[i]["due_date"], blocks[i]["processing_time"]))

    bay_free = [0] * n_bays          # earliest time each bay is empty again
    bay_wload = [0.0] * n_bays       # weighted load, for tie-break
    assignments: list[dict] = []

    for bid in order:
        blk = blocks[bid]
        r, p = blk["release_time"], blk["processing_time"]
        prefs = blk["bay_preferences"]
        s_max = max(prefs)
        candidates = fit[bid]
        # Choose the bay minimizing (exit_time, pref_penalty, resulting load).
        best = None
        for j, (oi, x, y) in candidates.items():
            entry = max(r, bay_free[j])
            exit_t = entry + p
            key = (exit_t, s_max - prefs[j], bay_wload[j] + u[j] * blk["workload"])
            if best is None or key < best[0]:
                best = (key, j, oi, x, y, entry, exit_t)
        # Fallback (degenerate instance): force bay 0 orientation 0 at (0,0).
        if best is None:
            j = 0
            entry = max(r, bay_free[j]); exit_t = entry + p
            best = ((exit_t, 0, 0), j, 0, 0, 0, entry, exit_t)

        _, j, oi, x, y, entry, exit_t = best
        bay_free[j] = exit_t
        bay_wload[j] += u[j] * blk["workload"]
        assignments.append({
            "block_id": bid, "bay_id": j, "x": int(x), "y": int(y),
            "orient_idx": oi, "entry_time": int(entry), "exit_time": int(exit_t),
        })

    return {"operations": _build_operations(assignments)}


# Submission entry point shim (mirrors myalgorithm.algorithm signature).
def algorithm(prob_info: dict, timelimit: float = 60.0) -> dict:
    return solve(prob_info, timelimit)
