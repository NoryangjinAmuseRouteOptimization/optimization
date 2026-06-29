"""
test_solver_regression.py -- pin the submission-safety fixes so they can't regress.

Covers the two failures that actually cost us leaderboard points, plus the
server execution model:

  1. test_aabb_boundary  -- the AABB fast-path must NOT accept a candidate whose
     bounding box pokes a hair past the bay wall.  candidate_positions filters
     positions with a 1e-6 tolerance, so a boundary candidate can slip through;
     the fast-path must re-check bay containment EXACTLY (matching the server's
     bay.contains_block).  This synthetic case reproduces the P3 -1 bug: it FAILS
     on the pre-fix code (returns an out-of-bay placement) and PASSES on the fix.

  2. test_safety_net  -- solver._ensure_feasible must replace an infeasible
     solution with the always-feasible sequential schedule, so a buggy optimizing
     path can never produce a -1 submission.

  3. test_single_threaded_feasible  -- with multiprocessing DISABLED (the server
     scenario), solve() must return feasible solutions within the time limit.

Run:
    cd <repo root>
    python tests/test_solver_regression.py
"""

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "baseline"))   # utils
sys.path.insert(0, str(ROOT))                 # solver, placement

from utils import Bay, Block, check_feasibility   # noqa: E402
import placement                                  # noqa: E402
import solver                                     # noqa: E402


def _rect_block(verts):
    """Minimal block_data with a single rectangular layer / one orientation."""
    return {
        "release_time": 0, "due_date": 100, "processing_time": 10,
        "workload": 1, "bay_preferences": [100],
        "shape": [{"orientation": 0, "layers": [verts]}],
    }


def test_aabb_boundary() -> bool:
    """
    Bay width 20.  Block A occupies x in [0, 14.5].  Block B has width 5.0000005,
    so the only non-colliding integer x for B is 15 -- where B spans
    [15, 20.0000005], i.e. 0.0000005 PAST the bay wall.  candidate_positions emits
    x=15 (passes its 1e-6 filter), and the fast-path must reject it on exact
    containment.  Correct outcome: _earliest_coexist returns None (B cannot
    coexist) -- never an out-of-bay placement.
    """
    bay = Bay(width=20, height=5, id=0)
    A = _rect_block([[0.0, 0.0], [14.5, 0.0], [14.5, 5.0], [0.0, 5.0]])
    B = _rect_block([[0.0, 0.0], [5.0000005, 0.0], [5.0000005, 5.0], [0.0, 5.0]])
    blocks_data = [A, B]
    geom = placement.GeometryCache({"blocks": blocks_data})

    placed = [Block(block_id=0, block_data=A, x=0, y=0, orient_idx=0)]
    scheds = [(0, 10)]

    res = solver._earliest_coexist(bay, placed, scheds, blocks_data, geom,
                                   bid=1, release=0, proc=10,
                                   max_entries=16, max_pos=80, deadline=None)
    ok = True
    if res is not None:
        oi, x, y, _, _ = res
        nb = Block(block_id=1, block_data=B, x=x, y=y, orient_idx=oi)
        if not bay.contains_block(nb):
            ok = False
            print(f"  [FAIL] AABB boundary: returned out-of-bay placement "
                  f"(x={x}, world_max_x={nb.bounding_rect()[2]} > W={bay.width})")
    print(f"  test_aabb_boundary: {'PASS' if ok else 'FAIL'} "
          f"(returned {'None (correct)' if res is None else res})")
    return ok


def test_safety_net() -> bool:
    """_ensure_feasible must turn an infeasible solution into a feasible one."""
    inst = ROOT / "alg_tester" / "example" / "example_B2_b10.json"
    prob = json.load(open(inst))
    bad = {"operations": {}}                       # no ops -> all blocks unassigned
    assert not check_feasibility(prob, bad)["feasible"], "bad solution should be infeasible"
    fixed = solver._ensure_feasible(prob, bad)
    ok = check_feasibility(prob, fixed)["feasible"]
    print(f"  test_safety_net: {'PASS' if ok else 'FAIL'} "
          f"(infeasible input -> {'feasible' if ok else 'STILL INFEASIBLE'} output)")
    return ok


def test_single_threaded_feasible() -> bool:
    """Server scenario: multiprocessing disabled -> solve() feasible & in time."""
    import concurrent.futures as cf

    class _Blocked:
        def __init__(self, *a, **k):
            raise OSError("multiprocessing blocked (simulated server sandbox)")

    orig = cf.ProcessPoolExecutor
    cf.ProcessPoolExecutor = _Blocked
    ok = True
    try:
        for name in ["alg_tester/example/example_B2_b10.json",
                     "data/train/prob_1.json", "data/train/prob_21.json"]:
            prob = json.load(open(ROOT / name))
            L = 8.0
            t0 = time.time()
            sol = solver.solve(prob, L)
            el = time.time() - t0
            r = check_feasibility(prob, sol)
            within = el <= L + 0.5
            if not (r["feasible"] and within):
                ok = False
                print(f"  [FAIL] {name}: feasible={r['feasible']} t={el:.1f}s (limit {L})")
            else:
                print(f"  {pathlib.Path(name).stem:18s} feasible, t={el:.1f}s")
    finally:
        cf.ProcessPoolExecutor = orig
    print(f"  test_single_threaded_feasible: {'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    print("=== solver regression tests ===")
    results = [
        test_aabb_boundary(),
        test_safety_net(),
        test_single_threaded_feasible(),
    ]
    print(f"\nRESULT: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
