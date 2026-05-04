"""
Layout-aware path planner.

Scans static prims under /World/Layout for their world-space AABBs, builds a
2D occupancy grid inflated by the agent radius, and runs A* to route a vehicle
between waypoints around obstacles. Independent of omni.anim.navigation, which
only sees navmesh-baked geometry.
"""

import heapq
import math


class LayoutPlanner:
    def __init__(self, stage, bounds_min, bounds_max,
                 agent_radius=0.9, cell_size=0.25,
                 layout_root="/World/Layout",
                 floor_height_threshold=0.1):
        # agent_radius=0.9: forklift body is ~1.1 m wide × 2.4 m long with
        # ~1.2 m forks out front. Half-width of the swept rectangle plus a
        # small clearance margin lands around 0.9 m — smaller values let the
        # planner cut corners through pallets and rack uprights.
        self.stage = stage
        self.cell = cell_size
        self.agent_radius = agent_radius
        self.x0 = bounds_min[0] - 1.0
        self.y0 = bounds_min[1] - 1.0
        self.x1 = bounds_max[0] + 1.0
        self.y1 = bounds_max[1] + 1.0
        self.cols = max(1, int(math.ceil((self.x1 - self.x0) / cell_size)))
        self.rows = max(1, int(math.ceil((self.y1 - self.y0) / cell_size)))

        self.blocked = [bytearray(self.cols) for _ in range(self.rows)]
        self._aabbs = self._collect_aabbs(layout_root, floor_height_threshold)
        self._mark_blocked(self._aabbs)
        print(f"[INFO] LayoutPlanner: {len(self._aabbs)} obstacles, "
              f"grid {self.cols}x{self.rows} @ {cell_size}m")

    def _collect_aabbs(self, layout_root, floor_height_threshold):
        from pxr import Usd, UsdGeom
        aabbs = []
        root = self.stage.GetPrimAtPath(layout_root)
        if not root or not root.IsValid():
            return aabbs
        bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(),
                                       [UsdGeom.Tokens.default_])
        for prim in Usd.PrimRange(root):
            if not prim.IsValid() or prim == root:
                continue
            if not UsdGeom.Imageable(prim):
                continue
            try:
                rng = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
            except Exception:
                continue
            if rng.IsEmpty():
                continue
            mn, mx = rng.GetMin(), rng.GetMax()
            # Skip floor-painted markings (stripes, arrows, signs).
            if mx[2] < floor_height_threshold:
                continue
            aabbs.append((mn[0], mn[1], mx[0], mx[1]))
        return aabbs

    def _mark_blocked(self, aabbs):
        r = self.agent_radius
        for (x_lo, y_lo, x_hi, y_hi) in aabbs:
            i_lo, j_lo = self._world_to_grid(x_lo - r, y_lo - r)
            i_hi, j_hi = self._world_to_grid(x_hi + r, y_hi + r)
            for j in range(max(0, j_lo), min(self.rows, j_hi + 1)):
                row = self.blocked[j]
                for i in range(max(0, i_lo), min(self.cols, i_hi + 1)):
                    row[i] = 1

    def _world_to_grid(self, x, y):
        return (int((x - self.x0) / self.cell),
                int((y - self.y0) / self.cell))

    def _grid_to_world(self, i, j):
        return (self.x0 + (i + 0.5) * self.cell,
                self.y0 + (j + 0.5) * self.cell)

    def _in_bounds(self, i, j):
        return 0 <= i < self.cols and 0 <= j < self.rows

    def _free(self, i, j):
        return self._in_bounds(i, j) and not self.blocked[j][i]

    def _nearest_free(self, i, j, max_radius=8):
        """If the requested cell is blocked (start/end inside an obstacle's
        inflation buffer), spiral outward to the nearest open cell."""
        if self._free(i, j):
            return (i, j)
        for r in range(1, max_radius + 1):
            for di in range(-r, r + 1):
                for dj in (-r, r):
                    if self._free(i + di, j + dj):
                        return (i + di, j + dj)
                for dj in range(-r + 1, r):
                    for di in (-r, r):
                        if self._free(i + di, j + dj):
                            return (i + di, j + dj)
        return None

    def _line_clear(self, i1, j1, i2, j2):
        """Bresenham-style line-of-sight check on the grid."""
        di = abs(i2 - i1)
        dj = abs(j2 - j1)
        si = 1 if i2 > i1 else -1
        sj = 1 if j2 > j1 else -1
        err = di - dj
        i, j = i1, j1
        while True:
            if not self._free(i, j):
                return False
            if i == i2 and j == j2:
                return True
            e2 = 2 * err
            if e2 > -dj:
                err -= dj
                i += si
            if e2 < di:
                err += di
                j += sj

    def plan(self, x1, y1, x2, y2):
        """Return a list of intermediate (x, y) waypoints excluding endpoints,
        or None if no path exists."""
        s = self._nearest_free(*self._world_to_grid(x1, y1))
        g = self._nearest_free(*self._world_to_grid(x2, y2))
        if s is None or g is None:
            return None
        if s == g:
            return []

        came_from = {}
        gscore = {s: 0.0}
        open_heap = [(self._h(s, g), 0.0, s)]
        SQRT2 = math.sqrt(2)

        while open_heap:
            _, gs, cur = heapq.heappop(open_heap)
            if cur == g:
                return self._reconstruct(came_from, cur)
            if gs > gscore.get(cur, float("inf")):
                continue
            ci, cj = cur
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ni, nj = ci + di, cj + dj
                if not self._free(ni, nj):
                    continue
                # Disallow corner-cutting through diagonal obstacles.
                if di and dj and (not self._free(ci + di, cj) or
                                  not self._free(ci, cj + dj)):
                    continue
                step = SQRT2 if di and dj else 1.0
                tentative = gs + step
                nbr = (ni, nj)
                if tentative < gscore.get(nbr, float("inf")):
                    gscore[nbr] = tentative
                    came_from[nbr] = cur
                    heapq.heappush(open_heap, (tentative + self._h(nbr, g),
                                               tentative, nbr))
        return None

    def _h(self, a, b):
        di = abs(a[0] - b[0])
        dj = abs(a[1] - b[1])
        return (di + dj) + (math.sqrt(2) - 2) * min(di, dj)

    def _reconstruct(self, came_from, end):
        path = [end]
        while path[-1] in came_from:
            path.append(came_from[path[-1]])
        path.reverse()
        # String-pulling: drop intermediate cells whenever line-of-sight allows.
        smoothed = [path[0]]
        i = 0
        while i < len(path) - 1:
            j = len(path) - 1
            while j > i + 1 and not self._line_clear(*path[i], *path[j]):
                j -= 1
            smoothed.append(path[j])
            i = j
        # Drop endpoints (caller already has them) and convert to world space.
        return [self._grid_to_world(i, j) for (i, j) in smoothed[1:-1]]
