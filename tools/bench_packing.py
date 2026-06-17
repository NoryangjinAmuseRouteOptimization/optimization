"""
bench_packing.py -- P1 benchmark: candidate-generator packing density & speed
===============================================================================

Goal
----
Measure how well (and how fast) the current placement.candidate_positions
generator packs blocks, compared to the baseline generator, BEFORE deciding
whether the heavier No-Fit-Polygon (NFP) generator is worth building.

Isolating pure 2D packing from scheduling
-----------------------------------------
If every block is given the SAME time window [0, 1), the crane checks in
can_place become trivial:
  * present_at_entry = { b : b.a < 0 < b.e } = {}   -> check_entry only tests
    bay containment (no crane obstruction possible).
  * present_at_exit  = { b : b.a < 1 < b.e } = {}   -> check_exit trivially passes.
So can_place reduces to "inside bay AND no same-layer collision with any other
placed block" -- exactly a 2D irregular packing feasibility test.  This isolates
P1's spatial packing quality from P2's scheduling.

Experiment (First-Fit-Decreasing into the largest bay)
------------------------------------------------------
* Pick the largest bay of the instance.
* Sort blocks by descending footprint area (best/ smallest-area orientation).
* Greedily place each block at the first feasible (bottom-left) candidate,
  trying orientations smallest-area first.
* Metrics: blocks packed, area utilization, wall time, candidates examined.

The ONLY thing swapped between the two runs is the candidate function; the
feasibility predicate (placement.can_place) is identical, so the comparison is
fair.

Run:
    python tools/bench_packing.py [--instances data/train/*.json]
                                  [--cap N] [--budget S] [--max-cand M]
"""

import argparse
import glob
import json
import math
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "baseline"))
sys.path.insert(0, str(ROOT))

from utils import Bay, Block, _resolve_layers, _poly_from_verts  # noqa: E402
import baseline_greedy                             # noqa: E402
import placement                                   # noqa: E402


# Base-footprint (layer-0) area per (block, orient), cached.  Layer-0 polygons
# are ALWAYS collision-checked (k=0, j=0), so any two placed blocks have
# disjoint layer-0 interiors -- hence sum(layer0_area)/bay_area <= 100%.  Using
# the projected union of all layers would double-count area where blocks
# interlock at different heights (legal, since collisions are per-layer), giving
# misleading >100% utilization.
_FOOT: dict[tuple[int, int], float] = {}


def footprint_area(blocks_data: list[dict], bid: int, oi: int) -> float:
    key = (bid, oi)
    a = _FOOT.get(key)
    if a is None:
        layers = _resolve_layers(blocks_data[bid]["shape"][oi]["layers"])
        p = _poly_from_verts(layers[0]) if layers else None
        a = p.area if p is not None else 0.0
        _FOOT[key] = a
    return a


def _orient_by_area(geom: placement.GeometryCache, bid: int) -> list[int]:
    """Orientation indices for a block, smallest footprint area first."""
    oris = list(range(geom.n_orient(bid)))
    return sorted(oris, key=lambda oi: (lambda g: g.width * g.height)(geom.geom(bid, oi)))


def _baseline_candidates(bay: Bay, placed: list[Block], g: placement.OrientGeom,
                         max_cand):
    """Adapter so baseline_greedy._candidate_positions matches our signature."""
    blk_bb = g.bbox
    cands = baseline_greedy._candidate_positions(bay.width, bay.height, placed, blk_bb)
    if max_cand is not None:
        cands = cands[:max_cand]
    return cands


def _placement_candidates(bay: Bay, placed: list[Block], g: placement.OrientGeom,
                          max_cand):
    return placement.candidate_positions(bay, placed, g, max_candidates=max_cand)


def _nfp_candidates(bay: Bay, placed: list[Block], g: placement.OrientGeom,
                    max_cand):
    return placement.nfp_candidate_positions(bay, placed, g, max_candidates=max_cand)


def _skyline_candidates(bay: Bay, placed: list[Block], g: placement.OrientGeom,
                        max_cand):
    return placement.skyline_candidate_positions(bay, placed, g, max_candidates=max_cand)


_GENERATORS = {
    "baseline":  _baseline_candidates,
    "placement": _placement_candidates,
    "nfp":       _nfp_candidates,
    "skyline":   _skyline_candidates,
}


def pack_bay(bay: Bay, block_ids: list[int], blocks_data: list[dict],
             geom: placement.GeometryCache, gen_name: str,
             budget: float, max_cand, strategy: str = "first") -> dict:
    """
    First-Fit-Decreasing packing of block_ids into a single bay, all sharing the
    time window [0, 1).  Returns metrics dict.

    strategy = "first"  -> take the first feasible candidate (generator order).
    strategy = "best"   -> among ALL feasible candidates (over every orientation)
                           pick the one with least skyline waste (best-fit).  The
                           skyline is used only as a scoring oracle; candidates
                           still come polygon-precise from the chosen generator.
    """
    gen = _GENERATORS[gen_name]

    placed: list[Block] = []
    scheds: list[tuple[int, int]] = []
    placed_area = 0.0
    cand_examined = 0
    n_placed = 0
    t0 = time.time()

    for bid in block_ids:
        if time.time() - t0 > budget:
            break
        sky = placement.Skyline.from_blocks(bay, placed) if strategy == "best" else None
        best = None          # (waste, oi, x, y) for best strategy
        done = False
        for oi in _orient_by_area(geom, bid):
            g = geom.geom(bid, oi)
            if not placement.fits_in_bay(bay, g):
                continue
            lx0, ly0, lx1, ly1 = g.bbox
            for (x, y) in gen(bay, placed, g, max_cand):
                cand_examined += 1
                nb = Block(block_id=bid, block_data=blocks_data[bid],
                           x=x, y=y, orient_idx=oi)
                if not bay.contains_block(nb):
                    continue
                if not placement.can_place(bay, placed, scheds, nb, 0, 1):
                    continue
                if strategy == "first":
                    placed.append(nb); scheds.append((0, 1))
                    placed_area += footprint_area(blocks_data, bid, oi)
                    n_placed += 1
                    done = True
                    break
                else:
                    w = sky.waste(x + lx0, x + lx1, y + ly0)
                    if best is None or w < best[0]:
                        best = (w, oi, x, y)
            if done:
                break
        if strategy == "best" and best is not None:
            _, oi, x, y = best
            placed.append(Block(block_id=bid, block_data=blocks_data[bid],
                                x=x, y=y, orient_idx=oi))
            scheds.append((0, 1))
            placed_area += footprint_area(blocks_data, bid, oi)
            n_placed += 1

    elapsed = time.time() - t0
    bay_area = bay.width * bay.height
    return {
        "placed": n_placed,
        "util": placed_area / bay_area if bay_area else 0.0,
        "cand": cand_examined,
        "time": elapsed,
    }


def run_instance(prob_info: dict, gens: list[str], budget: float,
                 cap: int | None, max_cand, strategy: str = "first"):
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob_info["bays"])]
    geom = placement.GeometryCache(prob_info)
    blocks_data = prob_info["blocks"]

    # Largest bay, blocks by descending best-orientation area.
    big = max(bays, key=lambda b: b.width * b.height)

    def best_area(bid):
        return min((lambda g: g.width * g.height)(geom.geom(bid, oi))
                   for oi in range(geom.n_orient(bid)))

    order = sorted(range(len(blocks_data)), key=best_area, reverse=True)
    if cap:
        order = order[:cap]

    out = {g: pack_bay(big, order, blocks_data, geom, g, budget, max_cand, strategy)
           for g in gens}
    out["bay"] = f"{big.width}x{big.height}"
    out["n_try"] = len(order)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default=str(ROOT / "data" / "train" / "*.json"))
    ap.add_argument("--gens", default="baseline,nfp",
                    help="comma list of generators to compare "
                         f"(available: {','.join(_GENERATORS)})")
    ap.add_argument("--cap", type=int, default=80,
                    help="max blocks to attempt per instance (0 = all)")
    ap.add_argument("--budget", type=float, default=8.0,
                    help="per-generator time budget per instance (s)")
    ap.add_argument("--max-cand", type=int, default=400,
                    help="cap on candidates per orientation (0 = unlimited)")
    ap.add_argument("--strategy", choices=["first", "best"], default="first",
                    help="first = first feasible candidate; "
                         "best = least-skyline-waste feasible candidate (best-fit)")
    args = ap.parse_args()

    gens = [g.strip() for g in args.gens.split(",") if g.strip()]
    for g in gens:
        if g not in _GENERATORS:
            raise SystemExit(f"unknown generator '{g}'; available: {list(_GENERATORS)}")

    files = sorted(glob.glob(args.instances),
                   key=lambda p: int(p.split("_")[-1].split(".")[0]))
    cap = args.cap or None
    max_cand = args.max_cand or None

    header = f"{'instance':10s} {'bay':9s} {'try':>4s} |"
    for g in gens:
        header += f" {g[:9]:>9s} {'util':>6s} {'s':>5s} |"
    print(header)
    print("-" * len(header))

    agg = {g: {"plc": 0, "util": 0.0, "t": 0.0} for g in gens}
    n = 0
    for f in files:
        prob = json.load(open(f))
        r = run_instance(prob, gens, args.budget, cap, max_cand, args.strategy)
        row = f"{prob['name']:10s} {r['bay']:9s} {r['n_try']:4d} |"
        for g in gens:
            m = r[g]
            row += f" {m['placed']:9d} {m['util']*100:5.1f}% {m['time']:4.1f}s |"
            agg[g]["plc"] += m["placed"]; agg[g]["util"] += m["util"]; agg[g]["t"] += m["time"]
        print(row)
        n += 1

    n = max(1, n)
    print("-" * len(header))
    tot = f"{'TOTAL/AVG':10s} {'':9s} {'':>4s} |"
    for g in gens:
        a = agg[g]
        tot += f" {a['plc']:9d} {a['util']/n*100:5.1f}% {a['t']:4.1f}s |"
    print(tot)


if __name__ == "__main__":
    main()
