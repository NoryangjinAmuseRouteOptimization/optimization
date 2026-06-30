"""Diagnostic: count how many training-instance solutions have coexisting blocks
with strict AABB interior overlap (i.e., Shapely was required for their
feasibility check, and Shapely version differences might matter)."""
import sys, json, glob, time
sys.path.insert(0, "/home/user/optimization")

from utils import Block, _bb_overlap
import solver

TIMELIMIT = 8.0

def aabb_coexist_overlap_pairs(prob_info, sol):
    """Return count of coexisting block pairs with AABB interior overlap."""
    bays_data = prob_info["bays"]
    blocks_data = prob_info["blocks"]

    asgns = {}
    for t_str, ops in sol.get("operations", {}).items():
        t = int(t_str)
        for op in ops:
            bid = op["block_id"]
            if op["type"] == "ENTRY":
                asgns[bid] = {"bay_id": op["bay_id"], "x": op["x"], "y": op["y"],
                               "orient_idx": op["orient_idx"], "entry_time": t}
            elif op["type"] == "EXIT" and bid in asgns:
                asgns[bid]["exit_time"] = t

    from collections import defaultdict
    bay_asgns = defaultdict(list)
    for bid, a in asgns.items():
        bay_asgns[a["bay_id"]].append((bid, a))

    overlap_count = 0
    for j, blist in bay_asgns.items():
        blocks_bb = {}
        for bid, a in blist:
            blk = Block(block_id=bid, block_data=blocks_data[bid],
                        x=int(round(a["x"])), y=int(round(a["y"])),
                        orient_idx=a["orient_idx"])
            blocks_bb[bid] = (blk.bounding_rect(), a)

        blist2 = list(blocks_bb.items())
        for p in range(len(blist2)):
            bidp, (bbp, ap) = blist2[p]
            for q in range(p+1, len(blist2)):
                bidq, (bbq, aq) = blist2[q]
                # Time overlap
                if ap["entry_time"] < aq.get("exit_time", 0) and aq["entry_time"] < ap.get("exit_time", 0):
                    if _bb_overlap(bbp, bbq):
                        overlap_count += 1
    return overlap_count

files = sorted(glob.glob("/home/user/optimization/data/train/prob_*.json"))
print(f"Testing {len(files)} instances with solver.solve({TIMELIMIT}s)")
print(f"{'Instance':20} {'Coexist-AABB-overlap':20} {'Feasible':10}")

total_overlap = 0
for fp in files:
    name = fp.split("/")[-1].replace(".json","")
    with open(fp) as f:
        prob = json.load(f)
    try:
        sol = solver.solve(prob, TIMELIMIT)
        from utils import check_feasibility
        res = check_feasibility(prob, sol)
        feasible = res["feasible"]
        n_overlap = aabb_coexist_overlap_pairs(prob, sol)
        total_overlap += n_overlap
        print(f"{name:20} {n_overlap:20} {str(feasible):10}")
    except Exception as e:
        print(f"{name:20} ERROR: {e}")
print(f"\nTotal coexist-AABB-overlap pairs across all instances: {total_overlap}")
