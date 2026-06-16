"""
placement.py -- P1 deliverable: spatial placement & geometry module
===============================================================================

Owner : P1 (Spatial / Geometry)
Scope : everything about *where* and *with which orientation* a block sits, and
        whether a given placement is crane- and collision-feasible.

This module is the spatial core that P2's scheduler/search loop calls.  The
agreed contract with P2 is:

    "Given the current bay state and a time window [entry, exit_t),
     enumerate feasible (x, y, orient) placements, and answer can_place(...)."

Design principles
-----------------
1. CONSISTENCY WITH THE EVALUATOR (non-negotiable).
   The competition server judges feasibility with utils.check_feasibility, which
   uses utils.check_entry / check_exit / check_collisions.  So the *final*
   yes/no decision in can_place() delegates to those exact functions.  We never
   re-implement the collision geometry -- we only add a faster pre-screening
   layer on top so the search visits fewer Shapely calls.

2. SPEED VIA A GEOMETry CACHE.
   Per (block, orientation) local layers and bounding boxes are precomputed once
   in GeometryCache.  Candidate enumeration works purely on integer bounding-box
   arithmetic (no Shapely) and only the surviving candidates pay for the precise
   crane/collision check.

3. RICHER CANDIDATE SET THAN THE BASELINE.
   baseline_greedy._candidate_positions only anchors a new block's LEFT/BOTTOM
   edge against placed blocks' RIGHT/TOP edges.  We additionally anchor the
   new block's RIGHT/TOP edge against placed blocks' LEFT/BOTTOM edges, so the
   packer can also fill gaps to the left of and below existing blocks.  This is
   a corner-point ("bottom-left-fill") generator; a full No-Fit-Polygon (NFP)
   generator is the planned next step (see TODO at the bottom).

Coordinate model (mirrors utils / problem statement)
----------------------------------------------------
* The reference point of a block is the first vertex of its first layer, which
  the instance generator guarantees to be (0, 0) in local coordinates.
* Placing a block at (x, y) translates every layer by (x, y).  Therefore the
  world-space bounding box is simply the local bounding box shifted by (x, y).
* x, y are integers (the evaluator rounds them before checking).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from utils import (
    Bay,
    Block,
    check_entry,
    check_exit,
    check_collisions,
    _resolve_layers,
    _bounding_box,
)


# =============================================================================
# Geometry cache
# =============================================================================

@dataclass(frozen=True)
class OrientGeom:
    """
    Precomputed local geometry of one (block, orientation).

    Attributes
    ----------
    bbox       : (min_x, min_y, max_x, max_y) of the full footprint in LOCAL
                 coordinates (reference point = (0, 0)).  World bbox at position
                 (x, y) is (min_x + x, min_y + y, max_x + x, max_y + y).
    width      : max_x - min_x  (footprint width, float).
    height     : max_y - min_y  (footprint height, float).
    base_verts : layer-0 polygon vertices in LOCAL coordinates (reference point
                 at (0, 0)).  Used as the orbiting polygon vertices b_j for NFP
                 contact-point generation.  Layer 0 is always collision-checked,
                 so contacts generated on it are the binding ones; the precise
                 can_place still validates every layer.
    """
    bbox:       tuple[float, float, float, float]
    width:      float
    height:     float
    base_verts: tuple[tuple[float, float], ...]


class GeometryCache:
    """
    Per-instance cache of block/orientation local geometry.

    Build once from prob_info and reuse for the whole solve.  Keeps candidate
    enumeration free of repeated layer resolution and bbox computation.
    """

    def __init__(self, prob_info: dict):
        self._blocks: list[dict] = prob_info["blocks"]
        self._cache: dict[tuple[int, int], OrientGeom] = {}

    def n_orient(self, block_id: int) -> int:
        """Number of orientations available for a block."""
        return len(self._blocks[block_id]["shape"])

    def geom(self, block_id: int, orient_idx: int) -> OrientGeom:
        """Return cached local geometry for (block_id, orient_idx)."""
        key = (block_id, orient_idx)
        g = self._cache.get(key)
        if g is None:
            raw = self._blocks[block_id]["shape"][orient_idx]["layers"]
            layers = _resolve_layers(raw)
            if layers:
                verts = [v for layer in layers for v in layer]
                bbox = _bounding_box(verts)
                base_verts = tuple((float(x), float(y)) for x, y in layers[0])
            else:
                bbox = (0.0, 0.0, 1.0, 1.0)
                base_verts = ()
            g = OrientGeom(bbox=bbox,
                           width=bbox[2] - bbox[0],
                           height=bbox[3] - bbox[1],
                           base_verts=base_verts)
            self._cache[key] = g
        return g


# =============================================================================
# Integer placement bounds
# =============================================================================

def position_bounds(bay: Bay, g: OrientGeom) -> tuple[int, int, int, int] | None:
    """
    Integer reference-point bounds (px_lo, px_hi, py_lo, py_hi) such that the
    block's world bounding box stays inside the bay:

        x + min_x >= 0   =>  x >= ceil(-min_x)
        x + max_x <= W   =>  x <= floor(W - max_x)
        (same for y)

    Returns None when no valid integer position exists for this orientation in
    this bay (the orientation simply does not fit).
    """
    lx0, ly0, lx1, ly1 = g.bbox
    px_lo = math.ceil(-lx0)
    px_hi = math.floor(bay.width - lx1)
    py_lo = math.ceil(-ly0)
    py_hi = math.floor(bay.height - ly1)
    if px_lo > px_hi or py_lo > py_hi:
        return None
    return px_lo, px_hi, py_lo, py_hi


def fits_in_bay(bay: Bay, g: OrientGeom) -> bool:
    """True iff at least one integer position of this orientation fits in bay."""
    return position_bounds(bay, g) is not None


# =============================================================================
# Candidate position generation (corner-point / bottom-left-fill)
# =============================================================================

def candidate_positions(bay: Bay,
                        placed_blocks: list[Block],
                        g: OrientGeom,
                        max_candidates: int | None = None) -> list[tuple[int, int]]:
    """
    Enumerate integer (x, y) reference-point candidates for a block of geometry g
    in `bay`, given the blocks already placed (and time-relevant) there.

    Anchor lines (improvement over baseline)
    ----------------------------------------
    x anchors:
      * bay left wall            : x = ceil(-min_x)
      * right of a placed block  : x = ceil(b.right - min_x)   (new LEFT touches b.RIGHT)
      * left of a placed block   : x = ceil(b.left  - max_x)   (new RIGHT touches b.LEFT)
    y anchors:
      * bay bottom wall          : y = ceil(-min_y)
      * top of a placed block    : y = ceil(b.top    - min_y)  (new BOTTOM touches b.TOP)
      * bottom of a placed block : y = ceil(b.bottom - max_y)  (new TOP touches b.BOTTOM)

    The Cartesian product of x and y anchors is filtered to those whose world
    bbox stays inside the bay, deduplicated, and sorted bottom-left first
    (y, then x) so the caller naturally prefers tight, low placements.

    Note: passing this AABB test does NOT guarantee crane/collision feasibility
    -- it only guarantees the block fits in the bay.  Use can_place() on each
    candidate for the precise decision.

    Parameters
    ----------
    placed_blocks  : Block objects already occupying the bay during the relevant
                     time window (the caller decides which blocks are relevant).
    max_candidates : optional cap; when set, only the first N (bottom-left order)
                     candidates are returned to bound search cost on big bays.
    """
    lx0, ly0, lx1, ly1 = g.bbox

    xs: set[int] = {max(0, math.ceil(-lx0))}
    ys: set[int] = {max(0, math.ceil(-ly0))}

    for b in placed_blocks:
        bb = b.bounding_rect()  # (min_x, min_y, max_x, max_y) world
        # new LEFT edge touches b RIGHT edge / new BOTTOM touches b TOP edge
        xs.add(math.ceil(bb[2] - lx0))
        ys.add(math.ceil(bb[3] - ly0))
        # new RIGHT edge touches b LEFT edge / new TOP touches b BOTTOM edge
        xs.add(math.ceil(bb[0] - lx1))
        ys.add(math.ceil(bb[1] - ly1))

    # Keep only in-bounds anchor coordinates.
    xs = {x for x in xs if x + lx0 >= -1e-6 and x + lx1 <= bay.width + 1e-6}
    ys = {y for y in ys if y + ly0 >= -1e-6 and y + ly1 <= bay.height + 1e-6}

    candidates: list[tuple[int, int]] = []
    for y in sorted(ys):
        for x in sorted(xs):
            candidates.append((int(x), int(y)))
            if max_candidates is not None and len(candidates) >= max_candidates:
                return candidates
    return candidates


# =============================================================================
# NFP-based candidate generation (contact points)
# =============================================================================

def nfp_candidate_positions(bay: Bay,
                            placed_blocks: list[Block],
                            g: OrientGeom,
                            max_candidates: int | None = None) -> list[tuple[int, int]]:
    """
    Generate integer reference-point candidates from No-Fit-Polygon contact
    points: positions where the block's layer-0 polygon *touches* an obstacle
    (a placed block's layer-0 polygon or a bay corner) without overlapping.

    Method (vertex-vertex contact, the classic NFP candidate set)
    -------------------------------------------------------------
    For a fixed obstacle vertex a_i and an orbiting block vertex b_j (local,
    reference at origin), placing the block so that b_j coincides with a_i means
    the reference point goes to a_i - b_j.  The set { a_i - b_j } over all
    obstacle and block vertices is a superset of the NFP boundary vertices and,
    for non-convex polygons too, captures every vertex-vertex tight contact.
    Bay corners are included as obstacle vertices so the block can also nestle
    into the bay's corners and walls.

    Each fractional contact is snapped to its four surrounding integer points
    (floor/ceil x floor/ceil) and kept only if the block's bounding box still
    fits in the bay.  The bottom-left wall anchor is always included as a
    fallback.  Results are deduplicated and sorted bottom-left first.

    Passing this returns only AABB-valid positions; can_place() still makes the
    precise crane/collision decision.  Compared with candidate_positions (bbox
    corners) this yields contact points that let non-convex blocks interlock.
    """
    base = g.base_verts
    lx0, ly0, lx1, ly1 = g.bbox
    W, H = bay.width, bay.height
    eps = 1e-6

    if not base:
        return candidate_positions(bay, placed_blocks, g, max_candidates)

    # Obstacle vertices: placed blocks' layer-0 world vertices + bay corners.
    obst: list[tuple[float, float]] = [(0.0, 0.0), (W, 0.0), (0.0, H), (W, H)]
    for b in placed_blocks:
        layers = b.layers_at_pos()
        if layers:
            obst.extend((v[0], v[1]) for v in layers[0])

    pts: set[tuple[int, int]] = {(max(0, math.ceil(-lx0)), max(0, math.ceil(-ly0)))}
    for ax, ay in obst:
        for bx, by in base:
            rx, ry = ax - bx, ay - by
            for xi in (math.floor(rx), math.ceil(rx)):
                if xi + lx0 < -eps or xi + lx1 > W + eps:
                    continue
                for yi in (math.floor(ry), math.ceil(ry)):
                    if yi + ly0 < -eps or yi + ly1 > H + eps:
                        continue
                    pts.add((int(xi), int(yi)))

    ordered = sorted(pts, key=lambda p: (p[1], p[0]))
    if max_candidates is not None:
        ordered = ordered[:max_candidates]
    return ordered


# =============================================================================
# Feasibility predicate (delegates to the evaluator's exact geometry)
# =============================================================================

def _time_overlaps(a1: int, e1: int, a2: int, e2: int) -> bool:
    """Half-open interval overlap: [a1, e1) & [a2, e2) != empty."""
    return a1 < e2 and a2 < e1


def can_place(bay: Bay,
              placed_blocks: list[Block],
              schedules: list[tuple[int, int]],
              new_block: Block,
              entry: int,
              exit_t: int) -> bool:
    """
    Decide whether `new_block` can occupy `bay` during [entry, exit_t) given the
    blocks already placed there with their (entry, exit) schedules.

    This mirrors the spatial portion of utils.check_feasibility exactly:

      Stage 2 (crane entry) : present_at_entry = { b : b.a < entry < b.e }
                              check_entry(bay, present_at_entry, new_block) empty.
      Stage 3 (crane exit)  : present_at_exit  = [new_block] + { b : b.a < exit_t < b.e }
                              check_exit(bay, present_at_exit, new_block) empty.
      Stage 4 (collision)   : for every b whose interval overlaps [entry, exit_t),
                              check_collisions(bay, [new_block, b]) empty.
                              (also covers bay-boundary via check_entry stage above)

    Stage 5 (same-time operation ordering) is NOT decided here -- it is a
    scheduling concern owned by P2/P3.  can_place answers the pure spatial +
    crane-path question for a fixed time window.

    `placed_blocks` and `schedules` are parallel lists (same index = same block).

    Returns True iff the placement is spatially and crane-path feasible.
    """
    # -- Stage 2: crane can lower the block in -------------------------------
    present_at_entry = [
        b for b, (a, e) in zip(placed_blocks, schedules)
        if a < entry < e
    ]
    if check_entry(bay, present_at_entry, new_block, fast=True):
        return False

    # -- Stage 3: crane can lift the block out -------------------------------
    present_at_exit = [new_block] + [
        b for b, (a, e) in zip(placed_blocks, schedules)
        if a < exit_t < e
    ]
    if check_exit(bay, present_at_exit, new_block, fast=True):
        return False

    # -- Stage 4: no same-layer collision with any co-present block ----------
    for b, (a, e) in zip(placed_blocks, schedules):
        if not _time_overlaps(entry, exit_t, a, e):
            continue
        if check_collisions(bay, [new_block, b]):
            return False

    return True


def feasible_placements(bay: Bay,
                        placed_blocks: list[Block],
                        schedules: list[tuple[int, int]],
                        block_id: int,
                        block_data: dict,
                        geom: GeometryCache,
                        entry: int,
                        exit_t: int,
                        orientations: list[int] | None = None,
                        max_candidates_per_orient: int | None = None):
    """
    Generator of crane/collision-feasible placements for a block in a fixed time
    window [entry, exit_t).  Yields (orient_idx, x, y) tuples in bottom-left,
    orientation order.

    The caller (P2 scheduler) typically wants either the first feasible
    placement (tight packing) or the best-scoring one; this generator lets it
    decide without P1 owning the objective.

    Only blocks whose time interval overlaps [entry, exit_t) actually constrain
    the placement, but for crane checks we pass the full lists and let can_place
    filter by the precise present-at-entry / present-at-exit rule.
    """
    if orientations is None:
        orientations = list(range(geom.n_orient(block_id)))

    for oi in orientations:
        g = geom.geom(block_id, oi)
        if not fits_in_bay(bay, g):
            continue
        # Restrict candidate anchors to blocks that share the time window;
        # blocks outside the window cannot collide and need not seed anchors.
        relevant = [
            b for b, (a, e) in zip(placed_blocks, schedules)
            if _time_overlaps(entry, exit_t, a, e)
        ]
        for (x, y) in candidate_positions(bay, relevant, g,
                                          max_candidates=max_candidates_per_orient):
            new_block = Block(block_id=block_id, block_data=block_data,
                              x=x, y=y, orient_idx=oi)
            if not bay.contains_block(new_block):
                continue
            if can_place(bay, placed_blocks, schedules, new_block, entry, exit_t):
                yield (oi, x, y)


# =============================================================================
# TODO (P1 roadmap)
# =============================================================================
# [ ] No-Fit-Polygon (NFP) candidate generation for tighter packing of
#     non-convex layers (Minkowski-difference via shapely), replacing/augmenting
#     the bounding-box corner-point generator above.
# [ ] Skyline / bottom-left-fill contour structure to cut candidate count on
#     large bays without losing good positions.
# [ ] Orientation pre-ranking (e.g. by footprint area / aspect) so the search
#     tries the most space-efficient orientation first.
