#!/usr/bin/env python3
"""HPD credible level of points / a model trajectory in a 2D posterior from public MCMC chains (NumPy + SciPy only).

Why: "n_s within 2 sigma and r below the 95% limit" (a 1D box test) overstates the allowed
region when a model sits at the edge; the honest question is which highest-posterior-density
(HPD) contour of the *joint* 2D marginal a model point reaches.  This tool computes, for each
point (or for every point of a trajectory), the posterior mass of the region whose density
exceeds the density at that point, using a binned Gaussian KDE with boundary reflection
(a construction similar to GetDist's, without the dependency; the bandwidth is Scott's rule, so
levels differ from GetDist's by a few 0.1% -- measured on a public 66k-sample chain: 95.4% vs
95.95%, 99.57% vs 99.74%, 99.995% vs 99.98% -- which is exactly why tails must not be quoted to
0.01%).  It reports the 2-dof Delta chi^2 equivalent, a Gaussian-approximation cross-check, and
a smoothing-sensitivity sweep so that tail levels (99.9x%) are quoted only to their robustness.

Inputs:  a GetDist / Cobaya-style chain root (<root>.txt with columns weight, -loglike, params;
         <root>.paramnames; optional <root>.ranges for hard bounds), or a CSV via --csv x,y[,w].
Points:  --point X Y (repeatable) and/or --trajectory FILE (CSV: label,x,y or x,y).

Examples:
  hpd-credible-level.py chains/SPA_BK/CLASS --params n_s r --point 0.9611 0.0273
  hpd-credible-level.py chains/SPA_BK/CLASS --params n_s r --trajectory traj.csv --smooth-sweep

Selftest: python3 hpd-credible-level.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import sys
import tempfile

import numpy as np

try:  # scipy is optional for the core; used for chi2 conversion and interpolation
    from scipy.signal import fftconvolve
    from scipy.stats import chi2 as _chi2
except Exception:  # pragma: no cover - degraded mode
    fftconvolve = None
    _chi2 = None


# ----------------------------------------------------------------------------- chain I/O
def read_paramnames(path):
    names = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            names.append(line.split()[0].rstrip("*"))
    return names


def read_ranges(path):
    ranges = {}
    if not os.path.exists(path):
        return ranges
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3:
                continue
            lo = None if parts[1] in ("N", "None") else float(parts[1])
            hi = None if parts[2] in ("N", "None") else float(parts[2])
            ranges[parts[0].rstrip("*")] = (lo, hi)
    return ranges


def load_chain(root, params, ignore_rows=0.0):
    """Return x, y, w for the two named parameters from a GetDist-format chain root."""
    files = sorted(glob.glob(root + "_*.txt")) or ([root + ".txt"] if os.path.exists(root + ".txt") else [])
    if not files:
        raise FileNotFoundError(f"no chain files for root {root}")
    names = read_paramnames(root + ".paramnames")
    idx = [names.index(p) for p in params]
    blocks = []
    for fn in files:
        data = np.loadtxt(fn)
        if data.ndim == 1:
            data = data[None, :]
        n0 = int(len(data) * ignore_rows)
        blocks.append(data[n0:])
    data = np.vstack(blocks)
    w = data[:, 0]
    cols = data[:, 2:]
    x, y = cols[:, idx[0]], cols[:, idx[1]]
    ranges = read_ranges(root + ".ranges")
    bounds = [ranges.get(params[0], (None, None)), ranges.get(params[1], (None, None))]
    return x, y, w, bounds


def load_csv(path):
    rows = np.loadtxt(path, delimiter=",", ndmin=2)
    x, y = rows[:, 0], rows[:, 1]
    w = rows[:, 2] if rows.shape[1] > 2 else np.ones(len(x))
    return x, y, w


# ----------------------------------------------------------------------------- KDE density
class Density2D:
    """Binned Gaussian KDE with mirror reflection at hard bounds (bounds inside the data support)."""

    def __init__(self, x, y, w=None, bounds=((None, None), (None, None)), grid=400, smooth=1.0, pad=3.0):
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        w = np.ones_like(x) if w is None else np.asarray(w, float)
        n_eff = w.sum() ** 2 / (w ** 2).sum()
        sx = math.sqrt(np.cov(x, aweights=w))
        sy = math.sqrt(np.cov(y, aweights=w))
        # Scott's rule in 2D: h = sigma * n_eff^(-1/6)
        hx = smooth * sx * n_eff ** (-1.0 / 6.0)
        hy = smooth * sy * n_eff ** (-1.0 / 6.0)
        self.bandwidth = (hx, hy)
        (xlo, xhi), (ylo, yhi) = bounds
        # reflect samples across active bounds (bound within pad*h of the data range)
        xs, ys, ws = [x], [y], [w]
        for lo, hi, arr, other, h in ((xlo, xhi, x, y, hx), (ylo, yhi, y, x, hy)):
            for b in (lo, hi):
                if b is None:
                    continue
                if arr.min() - b > pad * h and b - arr.max() > pad * h:
                    continue  # bound far from data: no reflection needed
                m = np.abs(arr - b) < 6 * h
                refl = 2 * b - arr[m]
                if arr is x:
                    xs.append(refl); ys.append(y[m]); ws.append(w[m])
                else:
                    xs.append(x[m]); ys.append(refl); ws.append(w[m])
        X = np.concatenate(xs); Y = np.concatenate(ys); W = np.concatenate(ws)
        # grid over the physical region (clipped to bounds), extended by pad*h for the convolution
        gx0 = x.min() - pad * hx if xlo is None else max(xlo, x.min() - pad * hx)
        gx1 = x.max() + pad * hx if xhi is None else min(xhi, x.max() + pad * hx)
        gy0 = y.min() - pad * hy if ylo is None else max(ylo, y.min() - pad * hy)
        gy1 = y.max() + pad * hy if yhi is None else min(yhi, y.max() + pad * hy)
        self.xedges = np.linspace(gx0, gx1, grid + 1)
        self.yedges = np.linspace(gy0, gy1, grid + 1)
        self.dx = self.xedges[1] - self.xedges[0]
        self.dy = self.yedges[1] - self.yedges[0]
        ext = int(math.ceil(4 * max(hx / self.dx, hy / self.dy))) + 1
        xe = np.concatenate([self.xedges[0] - self.dx * np.arange(ext, 0, -1), self.xedges,
                             self.xedges[-1] + self.dx * np.arange(1, ext + 1)])
        ye = np.concatenate([self.yedges[0] - self.dy * np.arange(ext, 0, -1), self.yedges,
                             self.yedges[-1] + self.dy * np.arange(1, ext + 1)])
        H, _, _ = np.histogram2d(X, Y, bins=[xe, ye], weights=W)
        kx = np.arange(-ext, ext + 1) * self.dx
        ky = np.arange(-ext, ext + 1) * self.dy
        kernel = np.exp(-0.5 * (kx[:, None] / hx) ** 2 - 0.5 * (ky[None, :] / hy) ** 2)
        if fftconvolve is not None:
            P = fftconvolve(H, kernel, mode="same")
        else:  # pragma: no cover
            P = _conv_direct(H, kernel)
        P = P[ext:-ext, ext:-ext]
        P = np.clip(P, 0, None)
        self.P = P / (P.sum() * self.dx * self.dy)  # P[ix, iy]
        self.xc = 0.5 * (self.xedges[1:] + self.xedges[:-1])
        self.yc = 0.5 * (self.yedges[1:] + self.yedges[:-1])
        flat = np.sort(self.P.ravel())[::-1]
        self._levels = flat
        self._cum = np.cumsum(flat) * self.dx * self.dy

    def density(self, x, y):
        """Bilinear interpolation of the density at (x, y); zero outside the grid."""
        if x < self.xedges[0] or x > self.xedges[-1] or y < self.yedges[0] or y > self.yedges[-1]:
            return 0.0
        # inside the grid box: clamp to the cell-centre range so that points within half a cell of a
        # hard bound (e.g. r = 0) use the edge cell instead of being reported as zero density
        ix = min(max((x - self.xc[0]) / self.dx, 0.0), len(self.xc) - 1.0)
        iy = min(max((y - self.yc[0]) / self.dy, 0.0), len(self.yc) - 1.0)
        i0, j0 = int(math.floor(ix)), int(math.floor(iy))
        i1, j1 = min(i0 + 1, len(self.xc) - 1), min(j0 + 1, len(self.yc) - 1)
        fx, fy = ix - i0, iy - j0
        P = self.P
        return float((1 - fx) * (1 - fy) * P[i0, j0] + fx * (1 - fy) * P[i1, j0]
                     + (1 - fx) * fy * P[i0, j1] + fx * fy * P[i1, j1])

    def credible_level(self, x, y):
        """Posterior mass of the region with density above the density at (x, y) (smallest HPD contour containing it)."""
        p = self.density(x, y)
        if p <= 0:
            return 1.0
        k = int(np.searchsorted(-self._levels, -p))
        return float(self._cum[min(k, len(self._cum) - 1)])


def _conv_direct(H, K):  # pragma: no cover - fallback without scipy
    out = np.zeros_like(H)
    kx, ky = K.shape
    ox, oy = kx // 2, ky // 2
    for i in range(kx):
        for j in range(ky):
            out += K[i, j] * np.roll(np.roll(H, i - ox, axis=0), j - oy, axis=1)
    return out


class GaussianApprox:
    def __init__(self, x, y, w=None):
        w = np.ones_like(x) if w is None else w
        self.mu = np.array([np.average(x, weights=w), np.average(y, weights=w)])
        self.cov = np.cov(np.vstack([x, y]), aweights=w)
        self.icov = np.linalg.inv(self.cov)

    def credible_level(self, x, y):
        d = np.array([x, y]) - self.mu
        m2 = float(d @ self.icov @ d)
        return 1.0 - math.exp(-0.5 * m2)


def delta_chi2_2dof(cl):
    """Delta chi^2 with 2 degrees of freedom that encloses probability cl."""
    cl = min(max(cl, 0.0), 1 - 1e-16)
    return -2.0 * math.log(1.0 - cl)


# ----------------------------------------------------------------------------- CLI
def read_trajectory(path):
    pts = []
    with open(path) as f:
        for row in csv.reader(f):
            if not row or row[0].strip().startswith("#"):
                continue
            try:
                vals = [float(v) for v in row[-2:]]
            except ValueError:
                continue  # header
            label = row[0] if len(row) > 2 else f"{vals[0]:.5g},{vals[1]:.5g}"
            pts.append((label, vals[0], vals[1]))
    return pts


def analyse(x, y, w, bounds, points, smooth_factors, grid):
    out = []
    dens = {s: Density2D(x, y, w, bounds, grid=grid, smooth=s) for s in smooth_factors}
    gauss = GaussianApprox(x, y, w)
    for label, px, py in points:
        row = {"label": label, "x": px, "y": py, "gauss": gauss.credible_level(px, py)}
        for s in smooth_factors:
            row[f"kde_{s}"] = dens[s].credible_level(px, py)
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", nargs="?", help="chain root (GetDist format) or CSV with --csv")
    ap.add_argument("--csv", action="store_true", help="root is a CSV: x,y[,weight]")
    ap.add_argument("--params", nargs=2, default=None, help="two parameter names (chain mode)")
    ap.add_argument("--bounds", nargs=4, type=float, default=None,
                    help="hard bounds xlo xhi ylo yhi (use nan for none; overrides <root>.ranges)")
    ap.add_argument("--point", nargs=2, type=float, action="append", default=[], metavar=("X", "Y"))
    ap.add_argument("--trajectory", help="CSV of trajectory points: [label,]x,y")
    ap.add_argument("--smooth", type=float, default=1.0, help="bandwidth factor relative to Scott's rule")
    ap.add_argument("--smooth-sweep", action="store_true", help="also report smooth x0.7 and x1.5")
    ap.add_argument("--grid", type=int, default=400)
    ap.add_argument("--ignore-rows", type=float, default=0.0, help="fraction of each chain file to drop as burn-in")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.root:
        ap.error("chain root or --selftest required")
    if args.csv:
        x, y, w = load_csv(args.root)
        bounds = [(None, None), (None, None)]
    else:
        if not args.params:
            ap.error("--params needed in chain mode")
        x, y, w, bounds = load_chain(args.root, args.params, args.ignore_rows)
    if args.bounds:
        b = [None if math.isnan(v) else v for v in args.bounds]
        bounds = [(b[0], b[1]), (b[2], b[3])]
    points = [(f"{px:.5g},{py:.5g}", px, py) for px, py in args.point]
    if args.trajectory:
        points += read_trajectory(args.trajectory)
    if not points:
        ap.error("give --point and/or --trajectory")
    factors = [args.smooth] + ([0.7 * args.smooth, 1.5 * args.smooth] if args.smooth_sweep else [])
    rows = analyse(x, y, w, bounds, points, factors, args.grid)
    n_eff = w.sum() ** 2 / (w ** 2).sum()
    print(f"# samples={len(x)} n_eff={n_eff:.0f} bounds={bounds} smooth={factors}")
    hdr = "label,x,y," + ",".join(f"CL_kde_x{s:g}" for s in factors) + ",CL_gauss,dchi2_2dof(kde)"
    print(hdr)
    best = None
    for r in rows:
        cls = [r[f"kde_{s}"] for s in factors]
        print(f"{r['label']},{r['x']:.6g},{r['y']:.6g}," + ",".join(f"{100*c:.3f}%" for c in cls)
              + f",{100*r['gauss']:.3f}%,{delta_chi2_2dof(cls[0]):.2f}")
        if best is None or cls[0] < best[0]:
            best = (cls[0], r)
    if len(rows) > 1:
        c, r = best
        print(f"# minimum along trajectory: {r['label']} CL={100*c:.3f}% (dchi2_2dof={delta_chi2_2dof(c):.2f});"
              " quote tails as dchi2 or '>= 99.x%', not to 0.01%")
    return 0


# ----------------------------------------------------------------------------- selftest
def selftest():
    rng = np.random.default_rng(1)
    n = 200_000
    cov = np.array([[1.0, 0.6], [0.6, 2.0]])
    L = np.linalg.cholesky(cov)
    z = rng.standard_normal((n, 2)) @ L.T
    x, y = z[:, 0] + 0.5, z[:, 1] - 1.0
    dens = Density2D(x, y, grid=300)
    gauss = GaussianApprox(x, y)
    icov = np.linalg.inv(cov)
    # points at Mahalanobis distance d along the major axis: exact CL = 1 - exp(-d^2/2)
    evals, evecs = np.linalg.eigh(cov)
    v = evecs[:, -1] * math.sqrt(evals[-1])
    for d in (1.0, 2.0, 3.0):
        px, py = 0.5 + d * v[0], -1.0 + d * v[1]
        exact = 1 - math.exp(-0.5 * d * d)
        cl = dens.credible_level(px, py)
        assert abs(cl - exact) < 0.015, (d, cl, exact)
        assert abs(gauss.credible_level(px, py) - exact) < 0.01
        m2 = np.array([px - 0.5, py + 1.0]) @ icov @ np.array([px - 0.5, py + 1.0])
        assert abs(m2 - d * d) < 1e-9
    assert abs(delta_chi2_2dof(0.95) - 5.99) < 0.01
    # boundary reflection: half-normal in y (y >= 0). The mode is at y = 0; without reflection
    # the KDE would leak mass to y < 0 and depress the density at the edge.
    x2 = rng.standard_normal(n)
    y2 = np.abs(rng.standard_normal(n))
    d_ref = Density2D(x2, y2, bounds=((None, None), (0.0, None)), grid=300)
    d_noref = Density2D(x2, y2, grid=300)
    cl_edge_ref = d_ref.credible_level(0.0, 0.0)
    cl_edge_noref = d_noref.credible_level(0.0, 0.0)
    assert cl_edge_ref < 0.03, cl_edge_ref            # edge is the mode -> tiny credible level
    assert cl_edge_noref > cl_edge_ref                # without reflection the edge looks less probable
    # exact HPD level of (0, 1) for x ~ N(0,1), y ~ half-normal: density ratio e^{-1/2} -> mass with
    # density above it is the set x^2 + y^2 < 1 (y>=0) => 1 - e^{-1/2} = 0.3935
    cl = d_ref.credible_level(0.0, 1.0)
    assert abs(cl - 0.3935) < 0.02, cl
    # CLI round trip on GetDist-format files
    with tempfile.TemporaryDirectory() as td:
        root = os.path.join(td, "chain")
        w = np.ones(n)
        np.savetxt(root + "_1.txt", np.column_stack([w, np.zeros(n), x2, y2, np.zeros(n)]))
        with open(root + ".paramnames", "w") as f:
            f.write("a\ta\nb\tb\nc*\tc\n")
        with open(root + ".ranges", "w") as f:
            f.write("a N N\nb 0 N\n")
        traj = os.path.join(td, "traj.csv")
        with open(traj, "w") as f:
            f.write("label,x,y\nedge,0,0\nfar,0,2.5\n")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main([root, "--params", "a", "b", "--trajectory", traj, "--smooth-sweep", "--grid", "300"])
        assert rc == 0
        text = buf.getvalue()
        assert "minimum along trajectory: edge" in text, text
        assert "far," in text
    print("selftest OK: Gaussian HPD levels within 1.5% at d=1,2,3; reflection at hard bound; CLI round trip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
