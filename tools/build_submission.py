"""
build_submission.py -- assemble and validate the competition submission zip
===============================================================================

Produces dist/submission.zip with the layout the evaluation server expects:

    myalgorithm.py     (root)  -- entry point; calls solver.solve (safety net)
    solver.py          (root)  -- our solver
    placement.py       (root)  -- spatial/geometry module
    utils.py           (root)  -- OFFICIAL, unmodified (server overwrites it)

Submission rules enforced (problem statement section 3.1):
  * myalgorithm.py is at the zip ROOT (not in a subfolder).
  * utils.py is the unmodified official file (byte-identical to baseline/utils.py).
  * total zip size <= 15 MB.

After building, the script UNZIPS into a throwaway dir and runs the packaged
algorithm there with ONLY that dir on the path -- proving the submission is
self-contained and that utils.check_feasibility certifies the result feasible.
This mirrors how the server runs it.

Run:
    python tools/build_submission.py [--instance data/train/prob_21.json]
                                     [--timelimit 30]
"""

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Generated entry point.  Kept tiny and dependency-light; the real work is in
# solver.py.  Lives only inside the zip, so it never shadows the repo's tooling.
#
# IMPORTANT: this delegates to solver.solve (NOT solver.solve_greedy).  solve()
# is the only path that ends in solver._ensure_feasible(), the safety net that
# re-checks the result with utils.check_feasibility and falls back to the
# always-feasible sequential schedule if anything is wrong.  Calling
# solve_greedy here would bypass that net and let an infeasible solution reach
# the server -- exactly the P3 -1 failure we are guarding against.
MYALGORITHM_SRC = '''\
# OGC2026 submission entry point.
# The server calls algorithm(prob_info, timelimit); we delegate to solver.solve,
# whose final _ensure_feasible() step guarantees a feasible result (it falls back
# to the sequential schedule if the optimizing path ever produces an infeasible
# solution).  Do NOT change this to solve_greedy: that bypasses the safety net.
def algorithm(prob_info, timelimit=60):
    import solver
    return solver.solve(prob_info, timelimit)
'''

# Files copied verbatim from the repo into the zip root.
PAYLOAD = {
    "solver.py":    ROOT / "solver.py",
    "placement.py": ROOT / "placement.py",
    "utils.py":     ROOT / "baseline" / "utils.py",   # OFFICIAL, unmodified
}


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> pathlib.Path:
    DIST.mkdir(exist_ok=True)
    build_dir = DIST / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir()

    (build_dir / "myalgorithm.py").write_text(MYALGORITHM_SRC)
    for name, src in PAYLOAD.items():
        shutil.copy2(src, build_dir / name)

    # Sanity: utils.py must be byte-identical to the official baseline copy.
    assert _sha(build_dir / "utils.py") == _sha(PAYLOAD["utils.py"]), \
        "utils.py was altered during copy"

    zip_path = DIST / "submission.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(build_dir.iterdir()):
            z.write(f, f.name)   # arcname = bare filename -> root of zip
    return zip_path


def validate(zip_path: pathlib.Path, instance: pathlib.Path, timelimit: float):
    # 1. Structural checks.
    size_mb = zip_path.stat().st_size / 1e6
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    print(f"zip       : {zip_path}  ({size_mb:.3f} MB)")
    print(f"contents  : {names}")
    assert "myalgorithm.py" in names, "myalgorithm.py missing from zip root"
    assert all("/" not in n for n in names), "files must be at zip root"
    assert size_mb <= 15.0, f"zip exceeds 15 MB ({size_mb:.2f})"

    # Report SHA256 of each packaged file.  Hashes are how we verify the right
    # build went out -- byte counts drift with every edit and are unsafe to pin
    # in docs, so we identify the build by content hash instead.
    with zipfile.ZipFile(zip_path) as z:
        for n in sorted(names):
            digest = hashlib.sha256(z.read(n)).hexdigest()
            print(f"sha256    : {n:16s} {digest}")

    # The packaged entry point MUST delegate to solver.solve (the safety-net
    # path), never solver.solve_greedy (which bypasses _ensure_feasible).
    with zipfile.ZipFile(zip_path) as z:
        entry_src = z.read("myalgorithm.py").decode()
    assert "solver.solve(" in entry_src, \
        "myalgorithm.py must call solver.solve (the _ensure_feasible safety net)"
    assert "solver.solve_greedy(" not in entry_src, \
        "myalgorithm.py must NOT call solver.solve_greedy -- it bypasses the safety net"

    # 2. Functional check in an ISOLATED dir (only the unzipped files on path),
    #    run as a child process so nothing from the repo leaks in.  We smoke-test
    #    BOTH routing paths so a regression in either fails the build:
    #      * a SMALL instance -> the P3-like quarantine / narrow-greedy path
    #        (the conservative solution that keeps P3 feasible on the server),
    #      * the given (large) instance -> the wide optimizer path.
    #    If the safe path ever produces a locally-infeasible result we must NOT
    #    ship it -- the build fails instead.
    small_inst = (ROOT / "data" / "train" / "prob_5.json").resolve()
    instances = [small_inst, instance.resolve()]
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tdp)
        for inst in instances:
            runner = (
                "import json,sys;"
                "import myalgorithm,utils;"
                f"p=json.load(open(r'{inst}'));"
                f"s=myalgorithm.algorithm(p,{timelimit});"
                "r=utils.check_feasibility(p,s);"
                "print('FEASIBLE' if r['feasible'] else 'INFEASIBLE stage='+str(r['stage']),"
                "'obj=%.0f'%r['objective'] if r['feasible'] else '');"
                "sys.exit(0 if r['feasible'] else 1)"
            )
            print(f"smoke test: {inst.name} (timelimit={timelimit}s, isolated)")
            res = subprocess.run([sys.executable, "-c", runner], cwd=tdp,
                                 capture_output=True, text=True)
            out = (res.stdout + res.stderr).strip()
            print(f"result    : {out}")
            if res.returncode != 0:
                raise SystemExit(f"submission FAILED isolated feasibility check on {inst.name}")
    print("OK: submission self-contained and feasible (both routing paths).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default=str(ROOT / "data" / "train" / "prob_21.json"))
    ap.add_argument("--timelimit", type=float, default=30.0)
    args = ap.parse_args()
    zip_path = build()
    validate(zip_path, pathlib.Path(args.instance), args.timelimit)


if __name__ == "__main__":
    main()
