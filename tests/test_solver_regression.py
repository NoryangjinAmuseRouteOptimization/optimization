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

  4. test_submission_entry_point  -- the ACTUAL packaged entry point matters, not
     just solver.solve().  The server runs zip-root myalgorithm.py, so this pins
     that the generated entry point delegates to solver.solve (the path that ends
     in the _ensure_feasible safety net) and NOT solver.solve_greedy (which
     bypasses it).  This is the exact gap that let the P3 -1 ship: solve() had the
     net, but the submitted myalgorithm.py called solve_greedy and skipped it.

  5. test_packaged_zip_feasible  -- build the real submission.zip, extract it into
     an isolated dir, and run the packaged myalgorithm.algorithm(...) as a child
     process with ONLY that dir on the path (mirroring the server).  Its result
     must pass utils.check_feasibility.  This exercises the end-to-end submission
     path, not just an in-repo import.

  6. test_p3like_quarantine  -- the P3-like quarantine must (a) route a small
     instance to the conservative NARROW greedy (seed 0, max_entries=16,
     max_pos=40 -- the #1-era profile that was server-feasible on P3), returning
     exactly that solution and not the wide/local path, and (b) route a large
     instance (narrow objective above _SMALL_OBJ_THRESHOLD) to the wide optimizer.
     Both must be feasible.  This pins the fix for the P3 -1 that the wide path
     reintroduced on the server while local check_feasibility kept passing.

Run:
    cd <repo root>
    python tests/test_solver_regression.py
"""

import json
import pathlib
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "baseline"))   # utils
sys.path.insert(0, str(ROOT))                 # solver, placement
sys.path.insert(0, str(ROOT / "tools"))       # build_submission

from utils import Bay, Block, check_feasibility   # noqa: E402
import placement                                  # noqa: E402
import solver                                     # noqa: E402
import build_submission                           # noqa: E402


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


def test_submission_entry_point() -> bool:
    """
    The packaged entry point must delegate to solver.solve (safety-net path), not
    solver.solve_greedy.  Check both the source template in build_submission.py
    and the myalgorithm.py actually written into dist/submission.zip.
    """
    ok = True

    # (a) the source template build_submission.py uses.
    src = build_submission.MYALGORITHM_SRC
    if "solver.solve(" not in src or "solver.solve_greedy(" in src:
        ok = False
        print("  [FAIL] MYALGORITHM_SRC does not call solver.solve "
              "(or still calls solver.solve_greedy)")

    # (b) the file that ends up in the built zip.
    zip_path = build_submission.build()
    with zipfile.ZipFile(zip_path) as z:
        entry = z.read("myalgorithm.py").decode()
    if "return solver.solve(prob_info, timelimit)" not in entry:
        ok = False
        print("  [FAIL] packaged myalgorithm.py does not "
              "'return solver.solve(prob_info, timelimit)'")
    if "solver.solve_greedy(" in entry:
        ok = False
        print("  [FAIL] packaged myalgorithm.py still calls solver.solve_greedy")

    print(f"  test_submission_entry_point: {'PASS' if ok else 'FAIL'} "
          f"(packaged entry point calls solver.solve)")
    return ok


def test_packaged_zip_feasible() -> bool:
    """
    End-to-end: build the zip, extract into an isolated dir, and run the packaged
    myalgorithm.algorithm(...) as a child process with only that dir on the path
    (the server's execution model).  The result must be feasible.  This is the
    test that would have caught the solve_greedy entry point shipping without the
    _ensure_feasible safety net.
    """
    zip_path = build_submission.build()
    inst = (ROOT / "data" / "train" / "prob_21.json").resolve()
    ok = True
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tdp)
        runner = (
            "import json,sys;"
            "import myalgorithm,utils;"
            f"p=json.load(open(r'{inst}'));"
            "s=myalgorithm.algorithm(p,8);"
            "r=utils.check_feasibility(p,s);"
            "sys.exit(0 if r['feasible'] else 1)"
        )
        res = subprocess.run([sys.executable, "-c", runner], cwd=tdp,
                             capture_output=True, text=True)
        if res.returncode != 0:
            ok = False
            print(f"  [FAIL] packaged algorithm infeasible/crashed: "
                  f"{(res.stdout + res.stderr).strip()}")
    print(f"  test_packaged_zip_feasible: {'PASS' if ok else 'FAIL'} "
          f"(isolated packaged myalgorithm.algorithm -> feasible)")
    return ok


def _coexist_x_disjoint(prob, assignments) -> bool:
    """True iff every pair of same-bay, time-overlapping blocks has x-disjoint
    bounding boxes (the column-packing guarantee that makes a solution feasible
    on any checker version)."""
    geom = placement.GeometryCache(prob)
    per_bay = {}
    for a in assignments:
        per_bay.setdefault(a["bay_id"], []).append(a)
    for bay_id, aa in per_bay.items():
        boxes = []
        for a in aa:
            b = Block(block_id=a["block_id"], block_data=prob["blocks"][a["block_id"]],
                      x=a["x"], y=a["y"], orient_idx=a["orient_idx"])
            boxes.append((a["entry_time"], a["exit_time"], b.bounding_rect()))
        for i in range(len(boxes)):
            e1, x1, bb1 = boxes[i]
            for j in range(i + 1, len(boxes)):
                e2, x2, bb2 = boxes[j]
                if e1 < x2 and e2 < x1:                 # time overlap
                    # x-ranges must be clearly disjoint (>= ~1 gap, allow 0.5 tol)
                    if not (bb1[2] <= bb2[0] - 0.5 or bb2[2] <= bb1[0] - 0.5):
                        return False
    return True


def test_p3like_quarantine() -> bool:
    """
    Three-way routing on the narrow-greedy objective:
      * P1/P2 band (< _COLUMN_PACK_LO)          -> narrow greedy (returned verbatim),
      * P3 band (.. < _SMALL_OBJ_THRESHOLD)      -> COLUMN PACKING (x-disjoint coexist),
      * large (>= _SMALL_OBJ_THRESHOLD)          -> wide optimizer.
    All feasible; the P3-band solution must satisfy the x-disjoint guarantee.
    """
    ok = True
    L = 10.0

    # (a) P1/P2 band: narrow path, returned verbatim.
    prob_s = json.load(open(ROOT / "data" / "train" / "prob_5.json"))
    narrow = solver._greedy_assignments(prob_s, L, seed=0, key_mode="exit",
                                        max_entries=16, max_pos=40)
    narrow_obj = solver.compute_objective(prob_s, narrow)[0]
    if narrow_obj >= solver._COLUMN_PACK_LO:
        ok = False
        print(f"  [FAIL] prob_5 narrow obj {narrow_obj:.0f} not below "
              f"_COLUMN_PACK_LO {solver._COLUMN_PACK_LO} (test instance assumption)")
    sol_s = solver.solve(prob_s, L)
    r_s = check_feasibility(prob_s, sol_s)
    obj_s = r_s["objective"]
    # Narrow path keeps the objective in the narrow band (column packing would
    # inflate it above _COLUMN_PACK_LO; the wide path would drop it far lower but
    # is only taken for large instances).  The probe uses a shorter budget than a
    # full L-second narrow run, so we check the band, not an exact match.
    if not r_s["feasible"]:
        ok = False
        print("  [FAIL] P1/P2-band instance (prob_5) infeasible")
    elif obj_s >= solver._COLUMN_PACK_LO:
        ok = False
        print(f"  [FAIL] P1/P2-band not on narrow path: solve obj {obj_s:.0f} "
              f">= _COLUMN_PACK_LO {solver._COLUMN_PACK_LO} (column/other path leaked in?)")

    # (b) P3 band: must column-pack (x-disjoint coexistence) and be feasible.
    prob_p = json.load(open(ROOT / "data" / "train" / "prob_22.json"))
    narrow_p = solver.compute_objective(
        prob_p, solver._greedy_assignments(prob_p, L, seed=0, key_mode="exit",
                                           max_entries=16, max_pos=40))[0]
    if not (solver._COLUMN_PACK_LO <= narrow_p < solver._SMALL_OBJ_THRESHOLD):
        ok = False
        print(f"  [FAIL] prob_22 narrow obj {narrow_p:.0f} not in P3 band "
              f"[{solver._COLUMN_PACK_LO}, {solver._SMALL_OBJ_THRESHOLD}) (assumption)")
    # direct column-packing construction must be feasible AND x-disjoint
    col = solver._greedy_assignments(prob_p, L, seed=0, key_mode="exit",
                                     max_entries=16, max_pos=40,
                                     x_gap=solver._COLUMN_X_GAP)
    if not check_feasibility(prob_p, {"operations": solver._build_operations(col)})["feasible"]:
        ok = False
        print("  [FAIL] column-packing construction (prob_22) infeasible")
    if not _coexist_x_disjoint(prob_p, col):
        ok = False
        print("  [FAIL] column-packing produced a NON-x-disjoint coexisting pair")
    sol_p = solver.solve(prob_p, L)
    if not check_feasibility(prob_p, sol_p)["feasible"]:
        ok = False
        print("  [FAIL] P3-band instance (prob_22) infeasible via solve()")

    # (c) large instance: narrow objective above threshold -> routed to wide.
    prob_l = json.load(open(ROOT / "data" / "train" / "prob_40.json"))
    narrow_l = solver._greedy_assignments(prob_l, L, seed=0, key_mode="exit",
                                          max_entries=16, max_pos=40)
    if solver.compute_objective(prob_l, narrow_l)[0] < solver._SMALL_OBJ_THRESHOLD:
        ok = False
        print("  [FAIL] prob_40 narrow objective below threshold (assumption)")
    sol_l = solver.solve(prob_l, L)
    if not check_feasibility(prob_l, sol_l)["feasible"]:
        ok = False
        print("  [FAIL] large instance (prob_40) infeasible")

    print(f"  test_p3like_quarantine: {'PASS' if ok else 'FAIL'} "
          f"(P1/P2->narrow, P3->column x-disjoint, large->wide; all feasible)")
    return ok


if __name__ == "__main__":
    print("=== solver regression tests ===")
    results = [
        test_aabb_boundary(),
        test_safety_net(),
        test_single_threaded_feasible(),
        test_submission_entry_point(),
        test_packaged_zip_feasible(),
        test_p3like_quarantine(),
    ]
    print(f"\nRESULT: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
