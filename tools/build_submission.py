"""
build_submission.py -- assemble and validate the competition submission zip
===============================================================================

Produces dist/submission.zip with the layout the evaluation server expects:

    myalgorithm.py     (root)  -- entry point; calls solver.algorithm
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
MYALGORITHM_SRC = '''\
# OGC2026 submission entry point.
# The server calls algorithm(prob_info, timelimit); we delegate to solver.
def algorithm(prob_info, timelimit=60):
    import solver
    return solver.algorithm(prob_info, timelimit)
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
        entrypoint = z.read("myalgorithm.py").decode("utf-8")
    print(f"zip       : {zip_path}  ({size_mb:.3f} MB)")
    print(f"contents  : {names}")
    assert "myalgorithm.py" in names, "myalgorithm.py missing from zip root"
    assert all("/" not in n for n in names), "files must be at zip root"
    assert size_mb <= 15.0, f"zip exceeds 15 MB ({size_mb:.2f})"
    assert "solver.algorithm(prob_info, timelimit)" in entrypoint, \
        "submission entry point must delegate to solver.algorithm"

    # 2. Functional check in an ISOLATED dir (only the unzipped files on path),
    #    run as a child process so nothing from the repo leaks in.
    instance = instance.resolve()
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tdp)
        runner = (
            "import json,sys;"
            "import myalgorithm,utils;"
            f"p=json.load(open(r'{instance}'));"
            f"s=myalgorithm.algorithm(p,{timelimit});"
            "r=utils.check_feasibility(p,s);"
            "print('FEASIBLE' if r['feasible'] else 'INFEASIBLE stage='+str(r['stage']),"
            "'obj=%.0f'%r['objective'] if r['feasible'] else '');"
            "sys.exit(0 if r['feasible'] else 1)"
        )
        print(f"smoke test: {instance.name} (timelimit={timelimit}s, isolated)")
        timeout = timelimit + max(5.0, timelimit * 0.10)
        try:
            res = subprocess.run([sys.executable, "-c", runner], cwd=tdp,
                                 capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(
                f"submission FAILED isolated timeout ({timeout:.1f}s)"
            ) from exc
        out = (res.stdout + res.stderr).strip()
        print(f"result    : {out}")
        if res.returncode != 0:
            raise SystemExit("submission FAILED isolated feasibility check")
    print("OK: submission self-contained and feasible.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default=str(ROOT / "data" / "train" / "prob_21.json"))
    ap.add_argument("--timelimit", type=float, default=30.0)
    args = ap.parse_args()
    zip_path = build()
    validate(zip_path, pathlib.Path(args.instance), args.timelimit)


if __name__ == "__main__":
    main()
