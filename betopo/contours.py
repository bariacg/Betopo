# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
import math
from collections import defaultdict

def distance_squared(p1, p2):
    return (p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2

def distance(p1, p2):
    return math.sqrt(distance_squared(p1, p2))

def cut_mesh(vertices, triangles, plane_origin, plane_normal, tolerance=1e-6):
    """
    Computes the intersection of a triangulated mesh with a plane.
    
    Args:
        vertices: Sequence of 3-float sequences representing vertex world coordinates.
        triangles: Sequence of 3-int sequences representing vertex indices.
        plane_origin: 3-float sequence for a point on the plane.
        plane_normal: 3-float sequence for the plane's normal vector.
        tolerance: Positive float for distance tolerance to the plane.
        
    Returns:
        dict with 'loops' and 'open_chains', each a list of ordered lists of (x,y,z) tuples.
    """
    if tolerance <= 0:
        raise ValueError("Tolerance must be positive")
    
    nx, ny, nz = plane_normal
    normal_length = math.sqrt(nx*nx + ny*ny + nz*nz)
    if normal_length == 0:
        raise ValueError("Plane normal must be nonzero")
    
    nnx, nny, nnz = nx / normal_length, ny / normal_length, nz / normal_length
    ox, oy, oz = plane_origin

    dists = []
    for idx, v in enumerate(vertices):
        if len(v) != 3:
            raise ValueError(f"Vertex at index {idx} must have 3 coordinates")
        dists.append((v[0]-ox)*nnx + (v[1]-oy)*nny + (v[2]-oz)*nnz)

    segments = []
    
    for t_idx, tri in enumerate(triangles):
        if len(tri) != 3:
            raise ValueError(f"Triangle at index {t_idx} must have 3 indices")
        
        for v_idx in tri:
            if v_idx < 0 or v_idx >= len(vertices):
                raise ValueError(f"Invalid vertex index {v_idx} in triangle {t_idx}")
        
        d0, d1, d2 = dists[tri[0]], dists[tri[1]], dists[tri[2]]
        
        # Skip completely coplanar triangles to avoid spurious interior diagonals
        if abs(d0) <= tolerance and abs(d1) <= tolerance and abs(d2) <= tolerance:
            continue
            
        # Skip triangles strictly on one side of the plane
        if (d0 > tolerance and d1 > tolerance and d2 > tolerance) or \
           (d0 < -tolerance and d1 < -tolerance and d2 < -tolerance):
            continue

        pts = []
        for i, j in [(0,1), (1,2), (2,0)]:
            vi, vj = tri[i], tri[j]
            di, dj = dists[vi], dists[vj]
            
            if (di > tolerance and dj < -tolerance) or (di < -tolerance and dj > tolerance):
                t = di / (di - dj)
                p1, p2 = vertices[vi], vertices[vj]
                pt = (
                    p1[0] + t * (p2[0] - p1[0]),
                    p1[1] + t * (p2[1] - p1[1]),
                    p1[2] + t * (p2[2] - p1[2])
                )
                pts.append(pt)
            elif abs(di) <= tolerance:
                v = vertices[vi]
                pts.append((float(v[0]), float(v[1]), float(v[2])))
                
        # Filter for unique intersection points
        unique = []
        for p in pts:
            if not any(distance_squared(p, up) <= tolerance * tolerance for up in unique):
                unique.append(p)
                
        if len(unique) == 2:
            segments.append((unique[0], unique[1]))

    # Spatial hash for robust endpoint matching
    cell_size = max(tolerance * 2.0, 1e-12)
    
    def get_cell(p):
        return (int(math.floor(p[0]/cell_size)), 
                int(math.floor(p[1]/cell_size)), 
                int(math.floor(p[2]/cell_size)))
    
    points_list = []
    grid = defaultdict(list)
    
    def add_point(p):
        cx, cy, cz = get_cell(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for pid in grid[(cx+dx, cy+dy, cz+dz)]:
                        if distance_squared(p, points_list[pid]) <= tolerance * tolerance:
                            return pid
        pid = len(points_list)
        points_list.append(p)
        grid[(cx, cy, cz)].append(pid)
        return pid

    edges = set()
    for pA, pB in segments:
        idA = add_point(pA)
        idB = add_point(pB)
        if idA != idB: # Ignore degenerate segments
            edges.add((min(idA, idB), max(idA, idB)))

    adj = defaultdict(set)
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
        
    unvisited_edges = set(edges)
    open_chains = []
    loops = []
    
    # Vertices with degree != 2 are chain endpoints or non-manifold junctions
    terminals = [v for v, neighbors in adj.items() if len(neighbors) != 2]
    
    # Extract unambiguous open chains starting from terminals
    # Sorting terminals for deterministic output
    for t in sorted(terminals):
        while True:
            # Deterministic edge traversal: sort adjacent vertices
            incident = sorted([v for v in adj[t] if (min(t, v), max(t, v)) in unvisited_edges])
            if not incident:
                break
            nxt = incident[0]
            unvisited_edges.remove((min(t, nxt), max(t, nxt)))
            
            chain = [t, nxt]
            curr = nxt
            while len(adj[curr]) == 2:
                next_incident = sorted([v for v in adj[curr] if (min(curr, v), max(curr, v)) in unvisited_edges])
                if not next_incident:
                    break
                nxt_curr = next_incident[0]
                unvisited_edges.remove((min(curr, nxt_curr), max(curr, nxt_curr)))
                curr = nxt_curr
                chain.append(curr)
                
            if len(chain) >= 2:
                open_chains.append([points_list[pid] for pid in chain])

    # Remaining edges form isolated closed loops of degree-2 vertices
    # Sort remaining edges to ensure deterministic loops
    while unvisited_edges:
        e = sorted(unvisited_edges)[0]
        unvisited_edges.remove(e)
        u, v = e
        loop = [u, v]
        curr = v
        while curr != u:
            incident = sorted([nxt for nxt in adj[curr] if (min(curr, nxt), max(curr, nxt)) in unvisited_edges])
            if not incident:
                break
            nxt = incident[0]
            unvisited_edges.remove((min(curr, nxt), max(curr, nxt)))
            curr = nxt
            if curr != u:
                loop.append(curr)
                
        if len(set(loop)) >= 3:
            loops.append([points_list[pid] for pid in loop])
            
    return {"loops": loops, "open_chains": open_chains}


def resample_ring(points, count):
    """
    Resamples a closed ring of points to an equal arc-length sequence.
    
    Args:
        points: Ordered sequence of (x,y,z) tuples forming a closed ring.
        count: Desired number of points in the output.
        
    Returns:
        List of `count` (x,y,z) points, preserving the first point.
    """
    if not isinstance(count,int) or count < 3:
        raise ValueError("Count must be at least 3")
    if len(points) < 3:
        raise ValueError("Ring must have at least 3 points")
        
    unique_pts = []
    for p in points:
        if not unique_pts or distance_squared(p, unique_pts[-1]) > 1e-12:
            unique_pts.append(p)
    if unique_pts and distance_squared(unique_pts[0], unique_pts[-1]) <= 1e-12:
        unique_pts.pop()
    if len(unique_pts) < 3:
        raise ValueError("Ring must have at least 3 unique points")
        
    ring = [tuple(p) for p in unique_pts] + [tuple(unique_pts[0])]
    lengths = [0.0]
    for i in range(len(ring)-1):
        lengths.append(lengths[-1] + distance(ring[i], ring[i+1]))
        
    total_len = lengths[-1]
    if total_len <= 0:
        raise ValueError("Ring perimeter must be positive")
        
    sampled = [ring[0]]
    for i in range(1, count):
        target_d = i * total_len / count
        for j in range(len(lengths)-1):
            if target_d <= lengths[j+1] or j == len(lengths) - 2:
                seg_len = lengths[j+1] - lengths[j]
                if seg_len <= 1e-12:
                    pt = ring[j]
                else:
                    t = max(0.0, min(1.0, (target_d - lengths[j]) / seg_len))
                    p1, p2 = ring[j], ring[j+1]
                    pt = (
                        p1[0] + t * (p2[0] - p1[0]),
                        p1[1] + t * (p2[1] - p1[1]),
                        p1[2] + t * (p2[2] - p1[2])
                    )
                sampled.append(pt)
                break
                
    return sampled


def align_ring(reference, candidate):
    """
    Reorders `candidate` ring by cyclic shift and optional reversal to best match `reference`.
    
    Args:
        reference: Sequence of (x,y,z) tuples.
        candidate: Sequence of (x,y,z) tuples.
        
    Returns:
        A new list containing the optimally reordered candidate.
    """
    if len(reference) != len(candidate):
        raise ValueError("Reference and candidate must have equal counts")
    if len(reference) < 3:
        raise ValueError("Count must be at least 3")
        
    n = len(reference)
    best_ssd = float('inf')
    best_cand = None
    
    cand_list = [tuple(p) for p in candidate]
    cand_rev = cand_list[::-1]
    
    for s in range(n):
        shifted = cand_list[s:] + cand_list[:s]
        ssd = sum(distance_squared(reference[i], shifted[i]) for i in range(n))
        if ssd < best_ssd:
            best_ssd = ssd
            best_cand = shifted
            
        shifted_rev = cand_rev[s:] + cand_rev[:s]
        ssd_rev = sum(distance_squared(reference[i], shifted_rev[i]) for i in range(n))
        if ssd_rev < best_ssd:
            best_ssd = ssd_rev
            best_cand = shifted_rev
            
    return best_cand
