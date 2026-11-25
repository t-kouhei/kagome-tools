# -*- coding: utf-8 -*-
"""格子の図：素辺を矢印で描き、指定した量で色分けする。"""
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

for fp in ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
           "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/meiryo.ttc",
           "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"]:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break


def plot_lattice(m, values, path, label="", incomplete=()):
    """values: {素辺: 数値}。行きと帰りの素辺は少しずらして並べる。格子の端の素辺は点線。"""
    segs, cols, styles, halo_segs = [], [], [], []
    for e in m.edges:
        a = m.position(e[:3])
        b = m.position(m.target(e))
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        ox, oy = -dy / n * 0.07, dx / n * 0.07            # 進行方向の左側へずらし、行きと帰りを分ける
        p0 = (a[0] + 0.15 * dx + ox, a[1] + 0.15 * dy + oy)
        p1 = (a[0] + 0.85 * dx + ox, a[1] + 0.85 * dy + oy)
        if not m.is_inner(e):                              # 余白は薄い灰色で形だけ描く
            halo_segs.append((p0, p1))
            continue
        segs.append((p0, p1))
        cols.append(values.get(e, float("nan")))
        styles.append("dotted" if e in incomplete else "solid")
    fig, ax = plt.subplots(figsize=(8, 6.5))
    vmin = min(c for c in cols if c == c)
    vmax = max(c for c in cols if c == c)
    lc = LineCollection(segs, array=cols, cmap="viridis", linewidths=3, linestyles=styles)
    lc.set_clim(vmin, vmax)
    ax.add_collection(lc)
    if halo_segs:
        ax.add_collection(LineCollection(halo_segs, colors="#cccccc", linewidths=2, linestyles="dotted"))
    for (p0, p1), c in zip(segs, cols):
        ax.annotate("", xy=p1, xytext=(p0[0] * 0.3 + p1[0] * 0.7, p0[1] * 0.3 + p1[1] * 0.7),
                    arrowprops=dict(arrowstyle="-|>", color="#333", lw=0.6, mutation_scale=7))
    for node in m.nodes:
        x, y = m.position(node)
        ax.plot(x, y, "o", ms=9, color="white", mec="#555", zorder=3)
        ax.text(x, y, node[0], ha="center", va="center", fontsize=6, zorder=4)
    fig.colorbar(lc, ax=ax, shrink=0.8, label=label)
    ax.set_aspect("equal"); ax.axis("off"); ax.autoscale()
    extra = "。灰色は余白" if m.halo else ""
    ax.set_title(f"カゴメ格子 N={m.n}：{label}（点線は格子の端で計算しきれない素辺{extra}）", fontsize=10)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
