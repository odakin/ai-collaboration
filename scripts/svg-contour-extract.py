#!/usr/bin/env python3
"""Recover published contour / curve data from the vector paths of a paper figure (SVG from pdftocairo), self-calibrated (NumPy only).

Why: when a paper compares a model to a published 2D constraint whose chains are not public, the
only source is the figure.  Vector PDFs keep the contour as paths; this tool extracts them by
colour, applies the SVG transforms (pdftocairo puts `transform="matrix(...)"` on stroked paths and
nests fills in `<g>` groups: forgetting either shifts everything by a few percent), and calibrates
the SVG->data affine map from a reference path whose data bounding box is known (typically a contour
of the same figure that *is* public, or the axes frame with tick values).  A second known path is used
as a check; report residuals, and never claim a "touch" below the line width (~0.001 in n_s).

Workflow:
  pdftocairo -svg -f 3 -l 3 paper.pdf page3.svg
  svg-contour-extract.py page3.svg --list                       # colours, point counts, bboxes
  svg-contour-extract.py page3.svg --stroke "rgb(0.39" --calib-index 0 --calib-bbox 0.9604 0.9757 0 0.0411 \
        --extract "rgb(94.66" --out planck95.csv --contains 0.9569 0.0354
  (calibration: x_svg = a x + b, y_svg = c y + d from the bbox of the reference path; y is flipped in SVG)

Selftest: python3 svg-contour-extract.py --selftest

Sibling (raster route): `claude-config/scripts/read-plot-axes.py` reads a figure that is
an image rather than vector paths -- it calibrates from the axis tick marks instead of a
known reference bbox, and returns lines/markers/bands in data units.  Use this file when
the PDF keeps the curve as a path and some contour's data bbox is already known; use that
one when all you have is pixels and the axes.  (Two blind reviewers wrote the raster tool
from scratch before the two knew about each other -- hence this pointer.)
"""
from __future__ import annotations

import argparse
import re
import sys

import numpy as np

_NUM = r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_TAG = re.compile(r"<(/?)(g|path)\b([^>]*?)(/?)>", re.S)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def parse_matrix(s):
    """SVG transform attribute -> 3x3 matrix (supports matrix(), translate(), scale(); composed left to right)."""
    M = np.eye(3)
    for name, body in re.findall(r"(matrix|translate|scale)\s*\(([^)]*)\)", s or ""):
        v = [float(t) for t in re.findall(_NUM, body)]
        if name == "matrix" and len(v) == 6:
            a, b, c, d, e, f = v
            T = np.array([[a, c, e], [b, d, f], [0, 0, 1]])
        elif name == "translate":
            T = np.array([[1, 0, v[0]], [0, 1, v[1] if len(v) > 1 else 0.0], [0, 0, 1]])
        elif name == "scale":
            sx = v[0]; sy = v[1] if len(v) > 1 else sx
            T = np.diag([sx, sy, 1.0])
        else:
            continue
        M = M @ T
    return M


def parse_d(d):
    """Path data -> list of points (absolute; curve end points; relative commands supported for m/l/c/z)."""
    toks = re.findall(r"([MLCZHVmlczhv])|(" + _NUM + ")", d)
    pts = []
    cmd = None
    buf = []
    cur = np.zeros(2)
    start = None
    for c, num in toks:
        if c:
            cmd = c
            buf = []
            if cmd in "Zz" and start is not None:
                cur = start.copy()
            continue
        buf.append(float(num))
        need = {"M": 2, "L": 2, "C": 6, "H": 1, "V": 1}[cmd.upper()]
        if len(buf) < need:
            continue
        if cmd in "ML":
            cur = np.array(buf[-2:])
        elif cmd in "ml":
            cur = cur + np.array(buf[-2:])
        elif cmd == "C":
            cur = np.array(buf[4:6])
        elif cmd == "c":
            cur = cur + np.array(buf[4:6])
        elif cmd == "H":
            cur = np.array([buf[0], cur[1]])
        elif cmd == "h":
            cur = cur + np.array([buf[0], 0.0])
        elif cmd == "V":
            cur = np.array([cur[0], buf[0]])
        elif cmd == "v":
            cur = cur + np.array([0.0, buf[0]])
        if cmd in "Mm":
            start = cur.copy()
            cmd = "L" if cmd == "M" else "l"   # subsequent pairs are implicit lineto
        pts.append(cur.copy())
        buf = []
    return np.array(pts) if pts else np.zeros((0, 2))


def extract_paths(svg_text, min_points=3):
    """All <path> elements with composed transforms applied. Returns list of dicts (stroke, fill, pts, n)."""
    stack = [np.eye(3)]
    out = []
    for m in _TAG.finditer(svg_text):
        closing, tag, attrs, selfclose = m.groups()
        A = dict(_ATTR.findall(attrs))
        if tag == "g":
            if closing:
                if len(stack) > 1:
                    stack.pop()
            else:
                stack.append(stack[-1] @ parse_matrix(A.get("transform")))
                if selfclose:
                    stack.pop()
            continue
        if closing or "d" not in A:
            continue
        pts = parse_d(A["d"])
        if len(pts) < min_points:
            continue
        T = stack[-1] @ parse_matrix(A.get("transform"))
        hom = np.column_stack([pts, np.ones(len(pts))]) @ T.T
        out.append({"stroke": A.get("stroke", "none"), "fill": A.get("fill", "none"), "pts": hom[:, :2], "n": len(pts)})
    return out


class Calibration:
    """Affine map between SVG coordinates and data coordinates from a reference path's bounding box."""

    def __init__(self, ref_pts, xmin, xmax, ymin, ymax):
        X, Y = ref_pts[:, 0], ref_pts[:, 1]
        self.a = (X.max() - X.min()) / (xmax - xmin)
        self.b = X.min() - self.a * xmin
        self.c = (Y.min() - Y.max()) / (ymax - ymin)     # SVG y grows downward
        self.d = Y.max() - self.c * ymin

    def to_data(self, pts):
        return np.column_stack([(pts[:, 0] - self.b) / self.a, (pts[:, 1] - self.d) / self.c])

    def residual(self, pts, xmin, xmax, ymin, ymax):
        q = self.to_data(pts)
        return max(abs(q[:, 0].min() - xmin), abs(q[:, 0].max() - xmax), abs(q[:, 1].min() - ymin), abs(q[:, 1].max() - ymax))


def contains(poly, x, y):
    """Even-odd point-in-polygon test."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xint = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xint > x:
                inside = not inside
    return inside


def gap_at_fixed_y(poly, x, y, tol):
    """Signed gap in x to the polygon boundary at the same y (positive: boundary lies at larger x); nan if no crossing."""
    sel = np.abs(poly[:, 1] - y) < tol
    if not sel.any():
        return float("nan")
    return float((poly[sel, 0] - x).min())


def select(paths, stroke=None, fill=None):
    return [p for p in paths if (stroke is None or stroke in p["stroke"]) and (fill is None or fill in p["fill"])]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("svg", nargs="?")
    ap.add_argument("--list", action="store_true", help="list paths (index, stroke, fill, n, bbox in SVG units)")
    ap.add_argument("--min-points", type=int, default=3)
    ap.add_argument("--stroke", help="substring of the stroke colour selecting the calibration/check candidates")
    ap.add_argument("--fill", help="substring of the fill colour selecting candidates")
    ap.add_argument("--calib-index", type=int, default=0, help="index within the selected candidates of the reference path")
    ap.add_argument("--calib-bbox", nargs=4, type=float, metavar=("XMIN", "XMAX", "YMIN", "YMAX"))
    ap.add_argument("--check-index", type=int, default=None)
    ap.add_argument("--check-bbox", nargs=4, type=float)
    ap.add_argument("--extract", help="substring of stroke or fill colour of the paths to convert to data coordinates")
    ap.add_argument("--out", help="CSV output (x,y per point; paths separated by a blank line)")
    ap.add_argument("--contains", nargs=2, type=float, action="append", default=[], metavar=("X", "Y"))
    ap.add_argument("--gap-tol", type=float, default=None, help="y tolerance for the fixed-y gap report (default 1% of bbox height)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.svg:
        ap.error("svg file or --selftest required")
    paths = extract_paths(open(args.svg).read(), args.min_points)
    if args.list or not args.calib_bbox:
        for i, p in enumerate(paths):
            P = p["pts"]
            print(f"{i}: stroke={p['stroke']} fill={p['fill']} n={p['n']} x[{P[:,0].min():.1f},{P[:,0].max():.1f}] y[{P[:,1].min():.1f},{P[:,1].max():.1f}]")
        if not args.calib_bbox:
            return 0
    cands = select(paths, args.stroke, args.fill)
    if not cands:
        print("no candidate paths for the given colours", file=sys.stderr)
        return 2
    cal = Calibration(cands[args.calib_index]["pts"], *args.calib_bbox)
    print(f"# calibration from candidate {args.calib_index} ({cands[args.calib_index]['n']} pts): x=(X-{cal.b:.4f})/{cal.a:.4f}, y=(Y-{cal.d:.4f})/{cal.c:.4f}")
    if args.check_index is not None and args.check_bbox:
        r = cal.residual(cands[args.check_index]["pts"], *args.check_bbox)
        print(f"# check path {args.check_index}: max bbox residual {r:.3g} (data units)")
    targets = [p for p in paths if args.extract and (args.extract in p["stroke"] or args.extract in p["fill"])]
    rows = []
    for i, p in enumerate(targets):
        q = cal.to_data(p["pts"])
        print(f"# extracted {i}: stroke={p['stroke']} fill={p['fill']} n={p['n']} x[{q[:,0].min():.5f},{q[:,0].max():.5f}] y[{q[:,1].min():.5f},{q[:,1].max():.5f}]")
        tol = args.gap_tol or 0.01 * (q[:, 1].max() - q[:, 1].min())
        for x, y in args.contains:
            print(f"#   point ({x}, {y}): inside={contains(q, x, y)} gap_x_at_fixed_y={gap_at_fixed_y(q, x, y, tol):+.5f}")
        rows.append(q)
    if args.out:
        with open(args.out, "w") as f:
            for q in rows:
                for x, y in q:
                    f.write(f"{x:.8g},{y:.8g}\n")
                f.write("\n")
        print(f"# wrote {args.out}")
    return 0


def selftest():
    # synthetic figure: axes map data (x in [0,1], y in [0,2]) -> SVG via x_svg = 100 + 300 x, y_svg = 400 - 150 y,
    # drawn as (i) a filled reference square inside a translated+scaled <g>, (ii) a stroked triangle with a
    # matrix transform on the element, (iii) a decoy path with too few points.
    def to_svg(x, y):
        return 100 + 300 * x, 400 - 150 * y
    ref = [(0.2, 0.5), (0.8, 0.5), (0.8, 1.5), (0.2, 1.5)]
    tri = [(0.3, 0.2), (0.9, 0.2), (0.6, 1.8), (0.3, 0.2)]
    # group transform matrix(2,0,0,2,-50,-100): local = (svg + (50,100))/2
    g_pts = [((to_svg(*p)[0] + 50) / 2, (to_svg(*p)[1] + 100) / 2) for p in ref]
    d_ref = "M " + " L ".join(f"{x} {y}" for x, y in g_pts) + " Z"
    # element transform matrix(0.5,0,0,-0.5,10,300): svg = (0.5 X + 10, -0.5 Y + 300) -> X = 2(svg-10), Y = 2(300-svg)
    e_pts = [(2 * (to_svg(*p)[0] - 10), 2 * (300 - to_svg(*p)[1])) for p in tri]
    d_tri = "M " + " C ".join(f"{x} {y} {x} {y} {x} {y}" for x, y in e_pts)  # curves whose end points are the vertices
    d_tri = "M " + f"{e_pts[0][0]} {e_pts[0][1]} " + " ".join(f"C {x} {y} {x} {y} {x} {y}" for x, y in e_pts[1:])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"><g clip-path="url(#c)"><g transform="matrix(2,0,0,2,-50,-100)">
<path fill="rgb(60%, 78%, 87%)" stroke="none" d="{d_ref}"/></g></g>
<path fill="none" stroke="rgb(86.66%, 51.7%, 32.1%)" transform="matrix(0.5, 0, 0, -0.5, 10, 300)" d="{d_tri}"/>
<path stroke="rgb(0%, 0%, 0%)" d="M 1 1 L 2 2"/></svg>"""
    paths = extract_paths(svg, min_points=3)
    assert len(paths) == 2, [p["n"] for p in paths]
    fills = select(paths, fill="rgb(60")
    assert len(fills) == 1 and fills[0]["n"] == 4
    cal = Calibration(fills[0]["pts"], 0.2, 0.8, 0.5, 1.5)
    assert abs(cal.a - 300) < 1e-9 and abs(cal.c + 150) < 1e-9, (cal.a, cal.c)
    strokes = select(paths, stroke="rgb(86.66")
    q = cal.to_data(strokes[0]["pts"])
    assert np.allclose(q, np.array(tri), atol=1e-9), q
    assert cal.residual(strokes[0]["pts"], 0.3, 0.9, 0.2, 1.8) < 1e-9
    assert contains(q, 0.6, 0.5) and not contains(q, 0.1, 0.5)
    assert abs(gap_at_fixed_y(q, 0.1, 0.2, 1e-6) - 0.2) < 1e-9
    # relative commands and H/V
    r = parse_d("m 1 1 l 2 0 v 3 h -2 z")
    assert np.allclose(r, [[1, 1], [3, 1], [3, 4], [1, 4]]), r
    print("selftest OK: nested <g> + element matrix transforms, bbox calibration, curve end points, point-in-polygon, fixed-y gap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
