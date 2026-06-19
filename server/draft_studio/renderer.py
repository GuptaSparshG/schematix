"""STL → 2D engineering drawing.

Adapted from the standalone 3d-to-2d-diagram service. Renders Front/Side/Top
orthographic projections plus an isometric view from an `.stl` mesh and
composes them into a single PNG with title block.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from shapely.geometry import Polygon as SPoly
from shapely.ops import unary_union
from stl import mesh

from server.config import OUTPUT_DIR

STL_OUT_DIR = OUTPUT_DIR / "stl"


# ── geometry helpers ────────────────────────────────────────────────────

def _load_stl_bytes(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    tmp = Path(f"/tmp/{uuid.uuid4()}.stl")
    tmp.write_bytes(data)
    try:
        m = mesh.Mesh.from_file(str(tmp))
        return m.vectors, m.normals
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _bounds(verts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pts = verts.reshape(-1, 3)
    bmin = pts.min(axis=0)
    bmax = pts.max(axis=0)
    return bmin, bmax, bmax - bmin


def _iso_rotate(verts, normals, bmin, bmax, az=45, el=30):
    c = (bmin + bmax) / 2
    v = verts.reshape(-1, 3) - c
    az_r = np.radians(az)
    el_r = np.radians(el)
    Rz = np.array([[np.cos(az_r), -np.sin(az_r), 0],
                   [np.sin(az_r),  np.cos(az_r), 0],
                   [0,             0,             1]])
    Rx = np.array([[1, 0,            0           ],
                   [0, np.cos(el_r), -np.sin(el_r)],
                   [0, np.sin(el_r),  np.cos(el_r)]])
    R = Rx @ Rz
    verts_rot = ((R @ v.T).T).reshape(-1, 3, 3)
    normals_rot = (R @ normals.T).T
    return verts_rot, normals_rot


# ── per-view rendering ─────────────────────────────────────────────────

def _render_view(ax, verts_3d, normals_3d, proj_axes, depth_axis, cam_normal,
                 title, real_w, real_h, show_centerlines=True,
                 line_width=1.0, edge_color="#111111", crease_angle=30):
    dots = normals_3d @ cam_normal
    is_front = dots >= -0.05

    if not is_front.any():
        ax.text(0.5, 0.5, "No visible faces", ha="center", va="center", transform=ax.transAxes)
        return

    pts_all = verts_3d[:, :, proj_axes].reshape(-1, 2)
    mn = pts_all.min(axis=0)
    mx = pts_all.max(axis=0)
    rng = mx - mn
    rng[rng == 0] = 1

    # Pass 1: clean outer outline via polygon union
    all_tris_n = (verts_3d[:, :, proj_axes] - mn) / rng
    polys = []
    for tri in all_tris_n:
        try:
            p = SPoly(tri)
            if p.is_valid and not p.is_empty and p.area > 1e-9:
                polys.append(p)
        except Exception:
            pass
    outline = unary_union(polys) if polys else None

    # Pass 2: silhouette + crease edges
    edge_faces = defaultdict(list)
    prec = 4
    for i in range(len(verts_3d)):
        tri = verts_3d[i]
        for j in range(3):
            v0 = tuple(np.round(tri[j], prec))
            v1 = tuple(np.round(tri[(j + 1) % 3], prec))
            edge_faces[tuple(sorted([v0, v1]))].append(i)

    cos_crease = np.cos(np.radians(crease_angle))
    sil_segs = []
    for (v0t, v1t), fids in edge_faces.items():
        draw = False
        if len(fids) == 1:
            draw = True
        elif len(fids) == 2:
            f0, f1 = fids
            if is_front[f0] != is_front[f1]:
                draw = True
            elif is_front[f0]:
                n0, n1 = normals_3d[f0], normals_3d[f1]
                d = np.linalg.norm(n0) * np.linalg.norm(n1)
                cos_a = np.dot(n0, n1) / d if d > 1e-10 else 1.0
                draw = cos_a < cos_crease
        if draw:
            p0 = (np.array(v0t)[proj_axes] - mn) / rng
            p1 = (np.array(v1t)[proj_axes] - mn) / rng
            sil_segs.append([p0, p1])

    ax.set_facecolor("white")
    ax.set_xlim(-0.30, 1.30)
    ax.set_ylim(-0.30, 1.30)
    ax.set_aspect("equal")
    ax.tick_params(labelbottom=False, labelleft=False, bottom=False, left=False)
    for sp in ax.spines.values():
        sp.set_edgecolor("#ddd")
        sp.set_linewidth(0.4)

    if outline is not None and not outline.is_empty:
        geoms = list(outline.geoms) if outline.geom_type == "MultiPolygon" else [outline]
        for geom in geoms:
            if geom.is_empty:
                continue
            xy = np.array(geom.exterior.coords)
            ax.fill(xy[:, 0], xy[:, 1], color="white", zorder=3)
            ax.plot(xy[:, 0], xy[:, 1], color=edge_color,
                    lw=line_width * 1.5, solid_capstyle="round",
                    solid_joinstyle="round", zorder=5)
            for hole in geom.interiors:
                hxy = np.array(hole.coords)
                ax.fill(hxy[:, 0], hxy[:, 1], color="white", zorder=4)
                ax.plot(hxy[:, 0], hxy[:, 1], color=edge_color,
                        lw=line_width, solid_capstyle="round", zorder=5)

    if sil_segs:
        lc = LineCollection(sil_segs, colors=edge_color, linewidths=line_width, zorder=6)
        ax.add_collection(lc)

    if show_centerlines:
        cl = dict(color="#0057b7", lw=0.9, linestyle=(0, (8, 3, 2, 3)), alpha=0.9, zorder=7)
        ax.plot([-0.05, 1.05], [0.5, 0.5], **cl)
        ax.plot([0.5, 0.5], [-0.05, 1.05], **cl)

    DC = "#CC0000"
    ext = dict(color="#aaa", lw=0.6, linestyle="--")
    ax.plot([0, 0], [0, -0.17], **ext)
    ax.plot([1, 1], [0, -0.17], **ext)
    ax.annotate("", xy=(1, -0.17), xytext=(0, -0.17),
                arrowprops=dict(arrowstyle="<->", color=DC, lw=1.1, mutation_scale=9))
    ax.text(0.5, -0.23, f"{real_w:.1f} mm", ha="center", va="top",
            fontsize=7.5, color=DC, fontweight="bold",
            bbox=dict(fc="white", ec="none", pad=0.5), zorder=8)

    ax.plot([-0.17, 0], [0, 0], **ext)
    ax.plot([-0.17, 0], [1, 1], **ext)
    ax.annotate("", xy=(-0.17, 1), xytext=(-0.17, 0),
                arrowprops=dict(arrowstyle="<->", color=DC, lw=1.1, mutation_scale=9))
    ax.text(-0.23, 0.5, f"{real_h:.1f} mm", ha="right", va="center",
            fontsize=7.5, color=DC, fontweight="bold", rotation=90,
            bbox=dict(fc="white", ec="none", pad=0.5), zorder=8)

    ax.text(0.5, 1.22, title, ha="center", va="center",
            fontsize=9, fontweight="bold", color="#111")
    ax.plot([0.12, 0.88], [1.16, 1.16], color="#111", lw=1.2)


# ── pipeline ────────────────────────────────────────────────────────────

def generate_drawing(stl_bytes: bytes, name: str,
                     drawn_by: str = "Engineer",
                     dpi: int = 250,
                     line_width: float = 1.0) -> Path:
    STL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    verts, normals = _load_stl_bytes(stl_bytes)
    bmin, bmax, dims = _bounds(verts)
    verts_iso, normals_iso = _iso_rotate(verts, normals, bmin, bmax)
    today = datetime.date.today().strftime("%Y-%m-%d")

    fig = plt.figure(figsize=(18, 12), facecolor="white", dpi=dpi)

    def hl(x1, x2, y, lw=0.9):
        fig.add_artist(plt.Line2D([x1, x2], [y, y],
            transform=fig.transFigure, color="#111", lw=lw, zorder=10))

    def vl(x, y1, y2, lw=0.9):
        fig.add_artist(plt.Line2D([x, x], [y1, y2],
            transform=fig.transFigure, color="#111", lw=lw, zorder=10))

    for y in [0.01, 0.99]: hl(0.01, 0.99, y, lw=2.5)
    for x in [0.01, 0.99]: vl(x, 0.01, 0.99, lw=2.5)

    for y in [0.09, 0.065, 0.038, 0.012]: hl(0.01, 0.99, y)
    for x in [0.50, 0.64, 0.74, 0.86]:    vl(x, 0.01, 0.09)

    tb = [
        (0.02, 0.078, "PART NAME",   5.5, "#666", "left"),
        (0.02, 0.068, name[:42],     8.5, "#000", "left"),
        (0.51, 0.078, "SCALE",       5.5, "#666", "left"),
        (0.51, 0.068, "NTS",         8.0, "#000", "left"),
        (0.65, 0.078, "UNIT",        5.5, "#666", "left"),
        (0.65, 0.068, "mm",          8.0, "#000", "left"),
        (0.75, 0.078, "PROJECTION",  5.5, "#666", "left"),
        (0.75, 0.068, "3rd Angle",   7.5, "#000", "left"),
        (0.87, 0.078, "SHEET",       5.5, "#666", "left"),
        (0.87, 0.068, "1 / 1",       7.5, "#000", "left"),
        (0.02, 0.051, "MATERIAL",    5.5, "#666", "left"),
        (0.02, 0.041, "—",           7.0, "#000", "left"),
        (0.51, 0.051, "DRAWN BY",    5.5, "#666", "left"),
        (0.51, 0.041, drawn_by,      7.5, "#000", "left"),
        (0.65, 0.051, "DATE",        5.5, "#666", "left"),
        (0.65, 0.041, today,         7.5, "#000", "left"),
        (0.75, 0.051, "CHECKED",     5.5, "#666", "left"),
        (0.75, 0.041, "—",           7.0, "#000", "left"),
        (0.87, 0.051, "REV",         5.5, "#666", "left"),
        (0.87, 0.041, "A",           8.0, "#000", "left"),
        (0.02, 0.025,
         f"BOUNDING BOX:  X={dims[0]:.2f} mm   Y={dims[1]:.2f} mm   Z={dims[2]:.2f} mm",
         6.5, "#333", "left"),
        (0.87, 0.025, "AUTO-GENERATED", 5.5, "#aaa", "left"),
    ]
    for (x, y, t, fs, c, ha) in tb:
        fig.text(x, y, t, ha=ha, va="center", fontsize=fs,
                 color=c, transform=fig.transFigure)

    vl(0.50, 0.09, 0.99, lw=0.6)
    hl(0.01, 0.99, 0.50, lw=0.6)

    ax_f = fig.add_axes([0.04, 0.53, 0.42, 0.40])
    ax_s = fig.add_axes([0.54, 0.53, 0.42, 0.40])
    ax_t = fig.add_axes([0.04, 0.12, 0.42, 0.35])
    ax_i = fig.add_axes([0.54, 0.12, 0.42, 0.35])

    kw = dict(line_width=line_width)
    _render_view(ax_f, verts, normals, [0, 1], 2, np.array([0, 0, 1]),
                 "FRONT VIEW", dims[0], dims[1], **kw)
    _render_view(ax_s, verts, normals, [1, 2], 0, np.array([1, 0, 0]),
                 "SIDE VIEW", dims[1], dims[2], **kw)
    _render_view(ax_t, verts, normals, [0, 2], 1, np.array([0, 1, 0]),
                 "TOP VIEW", dims[0], dims[2], **kw)
    _render_view(ax_i, verts_iso, normals_iso, [0, 1], 2, np.array([0, 0, 1]),
                 "ISOMETRIC VIEW", dims[0], dims[1],
                 show_centerlines=False, **kw)

    out_path = STL_OUT_DIR / f"{uuid.uuid4().hex[:12]}_{name}.png"
    plt.savefig(str(out_path), dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path
