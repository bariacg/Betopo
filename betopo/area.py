# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Surface patch planner bounded by four curved guides using Coons interpolation."""
import math
from mathutils import Vector

from .core import patch, sample_path

__all__ = ['grid_plan']


def _path_length(points):
    """Calculate total arc length of a 3D path."""
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += (b - a).length
    return total


def _validate_guide(guide, index):
    """Validate a single guide dictionary and return (points, existing, length)."""
    if not isinstance(guide, dict) or 'points' not in guide:
        raise ValueError(f"Guide {index} must be a dictionary with a 'points' list")
    raw_points = guide['points']
    if len(raw_points) < 2:
        raise ValueError(f"Guide {index} must contain at least two points")

    points = [Vector(p) for p in raw_points]
    for pt in points:
        if not all(math.isfinite(coord) for coord in pt):
            raise ValueError(f"Guide {index} contains non-finite coordinates")

    if (points[-1] - points[0]).length <= 1e-7:
        raise ValueError(f"Guide {index} endpoints must not be identical")

    length = _path_length(points)
    if length <= 1e-7:
        raise ValueError(f"Guide {index} has zero or near-zero length")

    existing = guide.get('existing')
    if existing is not None:
        if len(existing) != len(points):
            raise ValueError(
                f"Guide {index} existing BMVert count ({len(existing)}) "
                f"does not match points count ({len(points)})"
            )
        existing = list(existing)
        if any(not v.is_valid for v in existing):
            raise ValueError('The attached boundary changed; draw Area again')

    return points, existing, length


def _reconcile_corners(guides_data):
    """Validate cyclic connectivity within scale-relative tolerance and reconcile corner positions."""
    # guides_data in cyclic order: 0: bottom (p00->p10), 1: right (p10->p11),
    #                             2: top (p11->p01),    3: left (p01->p00)
    corner_pairs = [
        (3, -1, 0, 0),   # Corner 0: left end -> bottom start (p00)
        (0, -1, 1, 0),   # Corner 1: bottom end -> right start (p10)
        (1, -1, 2, 0),   # Corner 2: right end -> top start (p11)
        (2, -1, 3, 0),   # Corner 3: top end -> left start (p01)
    ]

    corners = []
    for c_idx, (g_prev, p_prev_idx, g_curr, p_curr_idx) in enumerate(corner_pairs):
        pts_prev, ex_prev, len_prev = guides_data[g_prev]
        pts_curr, ex_curr, len_curr = guides_data[g_curr]
        p_prev = pts_prev[p_prev_idx]
        p_curr = pts_curr[p_curr_idx]
        if ex_prev and ex_curr and ex_prev[p_prev_idx] != ex_curr[p_curr_idx]:
            raise ValueError('Attached Area sides must share the same corner vertex')

        gap = (p_curr - p_prev).length
        local_scale = max(min(len_prev, len_curr), 1e-5)
        tol = max(1e-4, 0.05 * local_scale)

        if gap > tol:
            raise ValueError(
                f"Guide corner {c_idx} is disconnected: gap ({gap:.5f}) "
                f"exceeds tolerance ({tol:.5f})"
            )

        # Attached vertices must never be moved; reconcile unattached to attached
        if ex_curr:
            reconciled = p_curr.copy()
        elif ex_prev:
            reconciled = p_prev.copy()
        else:
            reconciled = (p_curr + p_prev) * 0.5

        corners.append(reconciled)

    return corners


def _segments_intersect_2d(p1, p2, p3, p4):
    """Check whether open 2D line segments (p1, p2) and (p3, p4) strictly intersect."""
    d1 = p2 - p1
    d2 = p4 - p3
    det = d1.x * d2.y - d1.y * d2.x
    if abs(det) < 1e-12:
        return False, 0.0, 0.0

    dp = p3 - p1
    t = (dp.x * d2.y - dp.y * d2.x) / det
    u = (dp.x * d1.y - dp.y * d1.x) / det
    eps = 1e-5
    if eps < t < 1.0 - eps and eps < u < 1.0 - eps:
        return True, t, u
    return False, t, u


def _validate_patch(points, faces, boundary_indices, source, patch_scale):
    """Validate quad convexity, positive area, and boundary non-self-intersection."""
    for face in faces:
        coords = [points[i] for i in face]
        center = sum(coords, Vector()) / len(coords)
        normal = sum(
            ((a - center).cross(b - center) for a, b in zip(coords, coords[1:] + coords[:1])),
            Vector()
        )
        if normal.length < 1e-10:
            raise ValueError("Patch contains a zero-area face")

        turns = [
            (coords[k] - coords[k - 1]).cross(coords[(k + 1) % 4] - coords[k]).dot(normal)
            for k in range(4)
        ]
        if min(turns) < -1e-10 * normal.length_squared:
            raise ValueError("Patch contains a folded quad; reduce size or change Grid Span")

    # Dominant tangent plane for boundary intersection testing
    centroid = sum(points, Vector()) / len(points)
    dom_normal = None
    if source is not None:
        try:
            dom_normal = source.nearest(centroid)[1]
        except Exception:
            dom_normal = None

    if dom_normal is None or dom_normal.length < 1e-6:
        ring = [points[i] for i in boundary_indices]
        dom_normal = sum(
            ((a - centroid).cross(b - centroid) for a, b in zip(ring, ring[1:] + ring[:1])),
            Vector()
        )

    if dom_normal.length < 1e-8:
        raise ValueError("Patch boundary has degenerate zero area")

    dom_normal = dom_normal.normalized()
    test_vec = Vector((0, 0, 1)) if abs(dom_normal.z) < 0.9 else Vector((1, 0, 0))
    u_axis = dom_normal.cross(test_vec).normalized()
    v_axis = dom_normal.cross(u_axis).normalized()

    b_pts_2d = [
        Vector((points[i].dot(u_axis), points[i].dot(v_axis)))
        for i in boundary_indices
    ]

    num_b = len(boundary_indices)
    for k1 in range(num_b):
        a1_2d = b_pts_2d[k1]
        a2_2d = b_pts_2d[(k1 + 1) % num_b]
        for k2 in range(k1 + 2, num_b):
            if k1 == 0 and k2 == num_b - 1:
                continue
            b1_2d = b_pts_2d[k2]
            b2_2d = b_pts_2d[(k2 + 1) % num_b]

            intersects, t, u = _segments_intersect_2d(a1_2d, a2_2d, b1_2d, b2_2d)
            if intersects:
                p3d_1 = points[boundary_indices[k1]].lerp(points[boundary_indices[(k1 + 1) % num_b]], t)
                p3d_2 = points[boundary_indices[k2]].lerp(points[boundary_indices[(k2 + 1) % num_b]], u)
                if (p3d_1 - p3d_2).length < 0.25 * patch_scale:
                    raise ValueError("Boundary guides self-intersect: edge crossing detected")


def grid_plan(guides, quad_size, source=None, offset=0.0, subdivisions=(0, 0), max_segments=128):
    """Plan a retopology quad patch bounded by four curved guides using Coons interpolation."""
    if len(guides) != 4:
        raise ValueError("Area patch requires exactly four boundary guides")
    if not math.isfinite(quad_size) or quad_size <= 0 or not math.isfinite(offset):
        raise ValueError('Area needs a positive Quad Size and finite Surface Offset')

    guides_data = [_validate_guide(guide, i) for i, guide in enumerate(guides)]
    corners = _reconcile_corners(guides_data)

    (pts_bottom, ex_bottom, len_bottom), \
    (pts_right, ex_right, len_right), \
    (pts_top, ex_top, len_top), \
    (pts_left, ex_left, len_left) = guides_data

    # Parse subdivision hints
    if isinstance(subdivisions, (int, float)):
        sub_u, sub_v = int(subdivisions), int(subdivisions)
    else:
        sub_u, sub_v = int(subdivisions[0]), int(subdivisions[1])

    # Horizontal (U / column) subdivision determination
    if ex_bottom and ex_top:
        count_bottom = len(pts_bottom) - 1
        count_top = len(pts_top) - 1
        if count_bottom != count_top:
            raise ValueError(
                f"Opposite attached guides have incompatible counts: "
                f"bottom has {count_bottom} segments, top has {count_top} segments"
            )
        cols = count_bottom
    elif ex_bottom:
        cols = len(pts_bottom) - 1
    elif ex_top:
        cols = len(pts_top) - 1
    elif sub_u > 0:
        cols = sub_u
    else:
        if quad_size <= 0:
            raise ValueError("quad_size must be positive for automatic subdivision")
        cols = max(1, math.ceil(max(len_bottom, len_top) / quad_size))

    # Vertical (V / row) subdivision determination
    if ex_right and ex_left:
        count_right = len(pts_right) - 1
        count_left = len(pts_left) - 1
        if count_right != count_left:
            raise ValueError(
                f"Opposite attached guides have incompatible counts: "
                f"right has {count_right} segments, left has {count_left} segments"
            )
        rows = count_right
    elif ex_right:
        rows = len(pts_right) - 1
    elif ex_left:
        rows = len(pts_left) - 1
    elif sub_v > 0:
        rows = sub_v
    else:
        if quad_size <= 0:
            raise ValueError("quad_size must be positive for automatic subdivision")
        rows = max(1, math.ceil(max(len_right, len_left) / quad_size))

    # Validate subdivision bounds
    if cols < 1 or rows < 1:
        raise ValueError(f"Subdivision counts must be at least 1 (got {cols}x{rows})")
    if cols > max_segments:
        raise ValueError(f"Column subdivision count {cols} exceeds maximum of {max_segments}")
    if rows > max_segments:
        raise ValueError(f"Row subdivision count {rows} exceeds maximum of {max_segments}")
    if cols * rows > max_segments * max_segments:
        raise ValueError("Total grid quad count exceeds safe maximum")

    # Corner attachment status (attached corner vertices are left exact)
    corner_attached = [
        bool(ex_left or ex_bottom),   # Corner 0
        bool(ex_bottom or ex_right),  # Corner 1
        bool(ex_right or ex_top),     # Corner 2
        bool(ex_top or ex_left),      # Corner 3
    ]

    # Project unattached corners once
    projected_corners = []
    for c_idx, corner_pt in enumerate(corners):
        if not corner_attached[c_idx] and source is not None:
            projected_corners.append(source.project(corner_pt, offset))
        else:
            projected_corners.append(corner_pt.copy())

    # Sample four boundary curves in oriented cyclic order
    counts = [cols + 1, rows + 1, cols + 1, rows + 1]
    sampled_boundaries = []
    for g_idx in range(4):
        pts, ex, _ = guides_data[g_idx]
        count = counts[g_idx]
        if ex:
            # Attached boundary: keep exact points, never move or subdivide
            sampled = [p.copy() for p in pts]
        else:
            # Unattached boundary: resample between reconciled corners
            c_start = projected_corners[g_idx]
            c_end = projected_corners[(g_idx + 1) % 4]
            if len(pts) == 2:
                path = [c_start, c_end]
            else:
                path = [c_start] + [p.copy() for p in pts[1:-1]] + [c_end]
            sampled = sample_path(path, count)

            # Project intermediate newly generated points once
            if source is not None:
                for s_idx in range(1, count - 1):
                    sampled[s_idx] = source.project(sampled[s_idx], offset)

        sampled_boundaries.append(sampled)

    bottom_samples, right_samples, top_samples, left_samples = sampled_boundaries

    # Extract four corners for Coons bilinear term
    c00 = bottom_samples[0]
    c10 = bottom_samples[cols]
    c11 = top_samples[0]
    c01 = top_samples[cols]

    # Generate grid points and populate existing BMVert mapping
    grid = {}
    points = []
    existing = {}

    for j in range(rows + 1):
        for i in range(cols + 1):
            idx = len(points)
            grid[i, j] = idx

            is_bottom = (j == 0)
            is_right = (i == cols)
            is_top = (j == rows)
            is_left = (i == 0)

            if is_bottom and is_left:
                co = c00
                if ex_bottom:
                    existing[idx] = ex_bottom[0]
                elif ex_left:
                    existing[idx] = ex_left[rows]
            elif is_bottom and is_right:
                co = c10
                if ex_right:
                    existing[idx] = ex_right[0]
                elif ex_bottom:
                    existing[idx] = ex_bottom[cols]
            elif is_top and is_right:
                co = c11
                if ex_top:
                    existing[idx] = ex_top[0]
                elif ex_right:
                    existing[idx] = ex_right[rows]
            elif is_top and is_left:
                co = c01
                if ex_left:
                    existing[idx] = ex_left[0]
                elif ex_top:
                    existing[idx] = ex_top[cols]
            elif is_bottom:
                co = bottom_samples[i]
                if ex_bottom:
                    existing[idx] = ex_bottom[i]
            elif is_right:
                co = right_samples[j]
                if ex_right:
                    existing[idx] = ex_right[j]
            elif is_top:
                co = top_samples[cols - i]
                if ex_top:
                    existing[idx] = ex_top[cols - i]
            elif is_left:
                co = left_samples[rows - j]
                if ex_left:
                    existing[idx] = ex_left[rows - j]
            else:
                # Interior grid point: Coons interpolation + single projection
                s = i / cols
                t = j / rows
                b_pt = bottom_samples[i]
                t_pt = top_samples[cols - i]
                l_pt = left_samples[rows - j]
                r_pt = right_samples[j]

                bilinear = ((1.0 - s) * (1.0 - t) * c00 +
                            s * (1.0 - t) * c10 +
                            s * t * c11 +
                            (1.0 - s) * t * c01)
                coons_co = (1.0 - t) * b_pt + t * t_pt + (1.0 - s) * l_pt + s * r_pt - bilinear
                co = source.project(coons_co, offset) if source is not None else coons_co

            points.append(co)

    # Assemble quad faces
    faces = [
        (grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1])
        for j in range(rows)
        for i in range(cols)
    ]

    # Collect ordered boundary indices for validation
    boundary_indices = (
        [grid[i, 0] for i in range(cols)] +
        [grid[cols, j] for j in range(rows)] +
        [grid[cols - i, rows] for i in range(cols)] +
        [grid[0, rows - j] for j in range(rows)]
    )

    patch_scale = max(len_bottom, len_right, len_top, len_left)
    _validate_patch(points, faces, boundary_indices, source, patch_scale)

    # Orient boundary lists for metadata display
    guide_points = [
        [points[grid[i, 0]] for i in range(cols + 1)],
        [points[grid[cols, j]] for j in range(rows + 1)],
        [points[grid[cols - i, rows]] for i in range(cols + 1)],
        [points[grid[0, rows - j]] for j in range(rows + 1)],
    ]

    plan = patch(points, faces, existing=existing)
    plan['grid_columns'] = cols
    plan['grid_rows'] = rows
    plan['guide_points'] = guide_points

    return plan
