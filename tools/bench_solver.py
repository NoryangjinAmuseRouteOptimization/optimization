"""
bench_solver.py -- P3 critical-path harness: end-to-end solver evaluation
===============================================================================

Runs a solver (default: the real submission entry point myalgorithm.algorithm)
on every training instance, checks feasibility with the EXACT evaluator
(utils.check_feasibility), and reports the real competition objective and its
components -- the metric that actually decides the leaderboard, not packing
density.

Why this exists
---------------
P1's placement module is validated but produces no submittable solution by
itself.  Nothing in the repo measured the actual objective across all 40
instances, so no improvement could be scored.  This harness establishes the
baseline and is the regression tool the whole team needs.

What it reports per instance
----------------------------
  feasible | stage | objective | obj1(tardiness) | obj2(imbalance) | obj3(pref)
  | assigned/total blocks | elapsed

and aggregates: feasibility rate, total/mean objective over feasible instances,
and a count of failures (which would each score -1 on the server).

Server scoring note
-------------------
On the server an infeasible / timed-out / crashed run scores -1.  So the
feasibility rate is the first thing to protect; objective only matters among
feasible runs.

Run:
    python tools/bench_solver.py [--timelimit S] [--jobs N]
                                 [--instances 'data/train/*.json']
                                 [--solver baseline] [--out results.json]
"""

import argparse
import glob
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "baseline"))   # utils, baseline_greedy, myalgorithm
sys.path.insert(0, str(ROOT))                 # placement (for future solvers)


def _solve_one(args: tuple) -> dict:
    """
    Worker: load instance, run the solver, evaluate.  Runs in a child process so
    a crash/hang in one instance cannot take down the whole sweep, and so the 4
    server cores can be used.  Solver stdout is suppressed to keep output clean.
    """
    path, solver_name, timelimit = args
    # Re-establish import paths in the child process.
    sys.path.insert(0, str(ROOT / "baseline"))
    sys.path.insert(0, str(ROOT))
    from utils import check_feasibility

    name = pathlib.Path(path).stem
    with open(path) as f:
        prob = json.load(f)
    n_blocks = len(prob["blocks"])

    if solver_name == "baseline":
        import myalgorithm
        solver = myalgorithm.algorithm
    elif solver_name == "sequential":
        import solver as _s
        solver = _s.solve_sequential
    elif solver_name == "greedy":
        import solver as _s
        solver = _s.solve_greedy
    elif solver_name == "multistart":
        import solver as _s
        solver = _s.solve
    else:
        raise ValueError(f"unknown solver '{solver_name}'")

    rec = {"name": name, "n_blocks": n_blocks}
    t0 = time.time()
    try:
        with open(os.devnull, "w") as dn, redirect_stdout(dn):
            sol = solver(prob, timelimit)
        rec["elapsed"] = time.time() - t0
        res = check_feasibility(prob, sol)
        rec.update(
            feasible=res["feasible"],
            stage=res["stage"],
            objective=res["objective"],
            obj1=res["obj1"], obj2=res["obj2"], obj3=res["obj3"],
        )
        # assigned = number of ENTRY ops
        rec["assigned"] = sum(
            1 for ops in sol.get("operations", {}).values()
            for op in ops if op.get("type") == "ENTRY"
        )
    except Exception as e:  # crash -> server would score -1
        rec["elapsed"] = time.time() - t0
        rec.update(feasible=False, stage=-1, objective=None,
                   obj1=None, obj2=None, obj3=None, assigned=0,
                   error=f"{type(e).__name__}: {e}")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default=str(ROOT / "data" / "train" / "*.json"))
    ap.add_argument("--solver", default="baseline")
    ap.add_argument("--timelimit", type=float, default=30.0,
                    help="wall-clock seconds per instance (server uses minutes-30min)")
    ap.add_argument("--jobs", type=int, default=4,
                    help="parallel instances (server allows up to 4 cores)")
    ap.add_argument("--out", default=None, help="optional JSON results dump")
    args = ap.parse_args()

    files = sorted(glob.glob(args.instances),
                   key=lambda p: int(p.split("_")[-1].split(".")[0]))
    if not files:
        raise SystemExit(f"no instances matched {args.instances}")

    print(f"solver={args.solver}  timelimit={args.timelimit}s  jobs={args.jobs}  "
          f"instances={len(files)}")
    print(f"{'instance':10s} {'blk':>4s} {'feas':>5s} {'stg':>3s} "
          f"{'objective':>12s} {'obj1':>8s} {'obj2':>7s} {'obj3':>7s} "
          f"{'asgn':>7s} {'sec':>6s}")
    print("-" * 86)

    tasks = [(f, args.solver, args.timelimit) for f in files]
    results: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_solve_one, t): t[0] for t in tasks}
        for fut in as_completed(futs):
            r = fut.result()
            results[r["name"]] = r

    # Print in instance order.
    n_feas = 0
    tot_obj = tot_o1 = tot_o2 = tot_o3 = 0.0
    fails = []
    for f in files:
        r = results[pathlib.Path(f).stem]
        feas = r["feasible"]
        if feas:
            n_feas += 1
            tot_obj += r["objective"]; tot_o1 += r["obj1"]
            tot_o2 += r["obj2"]; tot_o3 += r["obj3"]
            objs = (f"{r['objective']:12.0f} {r['obj1']:8.1f} "
                    f"{r['obj2']:7.1f} {r['obj3']:7.1f}")
        else:
            fails.append(r["name"])
            objs = f"{'-':>12s} {'-':>8s} {'-':>7s} {'-':>7s}"
        print(f"{r['name']:10s} {r['n_blocks']:4d} {str(feas):>5s} "
              f"{r['stage']:3d} {objs} "
              f"{r['assigned']:3d}/{r['n_blocks']:<3d} {r['elapsed']:6.1f}")

    n = len(files)
    print("-" * 86)
    print(f"feasible: {n_feas}/{n} ({n_feas/n*100:.0f}%)   "
          f"failures (server -1): {len(fails)} {fails if fails else ''}")
    if n_feas:
        print(f"over feasible -> total obj={tot_obj:.0f}  mean={tot_obj/n_feas:.0f}  "
              f"| sum obj1={tot_o1:.0f} obj2={tot_o2:.0f} obj3={tot_o3:.0f}")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"meta": vars(args), "results": results}, f, indent=2)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
