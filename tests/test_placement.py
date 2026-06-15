"""
test_placement.py -- validate placement.py against the evaluator (utils).

Strategy
--------
1. Run the baseline greedy on an instance to obtain a solution that
   utils.check_feasibility certifies as FEASIBLE.
2. Decompose that solution into per-block assignments
   (bay, x, y, orient, entry, exit).
3. For every block, reconstruct the state of its bay (all other blocks in the
   same bay with their schedules) and assert that placement.can_place() also
   accepts the placement.  A real feasible solution must never be rejected by
   can_place -- this catches false negatives in the present-at-entry/exit and
   collision logic.
4. Report candidate-generation stats vs the baseline generator.

Run:
    cd <repo root>
    python tests/test_placement.py [instance.json] [--timelimit S]
"""

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "baseline"))   # utils, baseline_greedy
sys.path.insert(0, str(ROOT))                 # placement

from utils import Bay, Block, check_feasibility            # noqa: E402
import baseline_greedy                                      # noqa: E402
import placement                                            # noqa: E402


def decompose(solution: dict) -> dict[int, dict]:
    """Rebuild per-block assignment dicts from an operations solution."""
    assign: dict[int, dict] = {}
    for t_str, ops in solution["operations"].items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            rec = assign.setdefault(bid, {})
            if op["type"] == "ENTRY":
                rec.update(bay_id=op["bay_id"], x=op["x"], y=op["y"],
                           orient_idx=op["orient_idx"], entry=t)
            else:  # EXIT
                rec.update(exit=t)
    return assign


def validate(prob_info: dict, timelimit: float) -> bool:
    name = prob_info.get("name", "?")
    print(f"\n=== {name}  bays={len(prob_info['bays'])} blocks={len(prob_info['blocks'])} ===")

    sol = baseline_greedy.greedyalgorithm(prob_info, timelimit=timelimit)
    res = check_feasibility(prob_info, sol)
    if not res["feasible"]:
        print(f"  [skip] baseline solution is infeasible (stage={res['stage']}); "
              f"cannot use as ground truth.")
        return True  # not a placement.py failure

    assign = decompose(sol)
    bays = [Bay.from_dict(d, i) for i, d in enumerate(prob_info["bays"])]
    blocks_data = prob_info["blocks"]
    geom = placement.GeometryCache(prob_info)

    # Group blocks by bay for state reconstruction.
    by_bay: dict[int, list[int]] = {}
    for bid, a in assign.items():
        by_bay.setdefault(a["bay_id"], []).append(bid)

    false_neg = 0
    fit_fail = 0
    cand_total = 0
    cand_hit = 0

    for bid, a in assign.items():
        bay = bays[a["bay_id"]]
        # Other blocks in same bay with their schedules.
        others = [c for c in by_bay[a["bay_id"]] if c != bid]
        placed = [Block(block_id=c, block_data=blocks_data[c],
                        x=assign[c]["x"], y=assign[c]["y"],
                        orient_idx=assign[c]["orient_idx"]) for c in others]
        scheds = [(assign[c]["entry"], assign[c]["exit"]) for c in others]

        new_block = Block(block_id=bid, block_data=blocks_data[bid],
                          x=a["x"], y=a["y"], orient_idx=a["orient_idx"])

        # (a) the placed orientation must be reported as fitting.
        g = geom.geom(bid, a["orient_idx"])
        if not placement.fits_in_bay(bay, g):
            fit_fail += 1
            print(f"  [FAIL] block {bid}: fits_in_bay=False for a placed block")

        # (b) can_place must accept this known-feasible placement.
        ok = placement.can_place(bay, placed, scheds, new_block,
                                 a["entry"], a["exit"])
        if not ok:
            false_neg += 1
            print(f"  [FAIL] block {bid}: can_place rejected a feasible placement "
                  f"(bay={a['bay_id']} pos=({a['x']},{a['y']}) oi={a['orient_idx']} "
                  f"t=[{a['entry']},{a['exit']}))")

        # (c) candidate generator should be able to reproduce the actual (x,y)
        #     for the placed orientation (informational, not a hard failure).
        relevant = [pb for pb, (s, e) in zip(placed, scheds)
                    if placement._time_overlaps(a["entry"], a["exit"], s, e)]
        cands = placement.candidate_positions(bay, relevant, g)
        cand_total += len(cands)
        if (a["x"], a["y"]) in cands:
            cand_hit += 1

    n = len(assign)
    print(f"  blocks={n}  false_negatives={false_neg}  fit_failures={fit_fail}")
    print(f"  candidate avg/block={cand_total / max(1, n):.1f}  "
          f"placed-pos-in-candidates={cand_hit}/{n}")

    ok = (false_neg == 0 and fit_fail == 0)
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("instance", nargs="?",
                        default=str(ROOT / "alg_tester" / "example" / "example_B2_b10.json"),
                        help="instance JSON (default: alg_tester example, 10 blocks)")
    parser.add_argument("--timelimit", type=float, default=30.0)
    args = parser.parse_args()

    with open(args.instance) as f:
        prob_info = json.load(f)

    ok = validate(prob_info, args.timelimit)
    sys.exit(0 if ok else 1)
