#!/usr/bin/env python3
"""Supplementary Figure S1 -- conceptual design, protocol, and measurement window.

Drawn at final print size (7.0 in = AAAI two-column text width) and included at
width=\\textwidth, so the scale factor is 1.0 and every label renders at its
nominal point size. No label is below 9 pt (AAAI figure-text floor). Total height
is held under 5 in so that the figure plus its caption stays inside LaTeX's
two-column top-float fraction and the float lands near its first reference.

(a) The scientific control: identical frozen base weights across the two tutoring
    policies; only the policy layer differs. The cold baseline calls no tutor.
(b) The continuous protocol and the two context scopes: the student carries one
    growing conversation across all 19 problems; the tutor sees only the current
    training problem's dialogue.
(c) The answer-phase evaluation window on one training problem, and where the
    turn-level measures attach.

Outputs: supp_fig1_design.pdf (editable text, Type 42) and .png.
Deterministic: identical inputs give identical output.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplconfig-supp")

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans", "sans-serif"],
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "svg.fonttype": "none",
    "font.size": 9.0,
    "axes.linewidth": 0.8,
})

# ---------------------------------------------------------------- palette
INK = "#1A1A1A"
GREY = "#6E6E6E"
RULE = "#BFBFBF"
BLUE = "#2C6FB0"        # ConvTutor family
ORANGE = "#C4661F"      # PedTutor family
NEUTRAL = "#7A7A7A"     # cold
FILL_W = "#FFFFFF"
FILL_L = "#EFF2F6"
FILL_TUT = "#E3EDF6"    # tutored / tutor turn
FILL_PROBE = "#F4F1EA"  # unassisted probe phase
FILL_STU = "#EAF0EA"    # student turn

W, H = 7.0, 4.52        # inches; included at width=\textwidth -> scale 1.0
XL, XR = 0.30, 6.70     # content margins
XC = (XL + XR) / 2

FS_PANEL = 9.5
FS_HEAD = 9.0
FS_BODY = 9.0

fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")


def box(x, y, w, h, fc=FILL_W, ec=INK, lw=0.9, r=0.045, z=2, ls="-"):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
        facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, zorder=z))


def txt(x, y, s, size=FS_BODY, color=INK, ha="center", va="center",
        weight="normal", z=5):
    ax.text(x, y, s, fontsize=size, color=color, ha=ha, va=va,
            fontweight=weight, zorder=z)


def arrow(x0, y0, x1, y1, color=INK, lw=0.9, z=4, ms=6):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>",
                                 mutation_scale=ms, color=color, linewidth=lw,
                                 shrinkA=0, shrinkB=0, zorder=z))


def bracket(x0, x1, y, color=INK, lw=1.0, tick=0.08, down=True):
    ax.plot([x0, x1], [y, y], color=color, lw=lw, zorder=3)
    dy = -tick if down else tick
    for xe in (x0, x1):
        ax.plot([xe, xe], [y, y + dy], color=color, lw=lw, zorder=3)


# =====================================================================
# Panel (a): identical weights, policy as the manipulation
# =====================================================================
txt(0.06, 4.42, "(a)", size=FS_PANEL, ha="left", weight="bold")
txt(0.34, 4.42, "Scientific control: policy is the only manipulation",
    size=FS_HEAD, ha="left", weight="bold")

box(XL, 4.06, XR - XL, 0.22, fc=FILL_L, ec=GREY, lw=0.8)
txt(XC, 4.17, "One frozen tutor base model, identical weights across policies",
    size=FS_BODY)

ay, ah = 3.14, 0.82
cols = [
    (XL, 1.60, "Cold", NEUTRAL, ["no tutor in any phase"]),
    (XL + 1.78, 2.25, "ConvTutor", BLUE,
     ["one helpful-tutor instruction;", "one model call per turn"]),
    (XL + 4.21, 2.19, "PedTutor", ORANGE,
     ["learner-state tracker, then", "one of three responders;",
      "two model calls per turn"]),
]
for x, w, name, col, lines in cols:
    box(x, ay, w, ah, fc=FILL_W, ec=col, lw=1.1)
    txt(x + w / 2, ay + ah - 0.17, name, size=FS_HEAD, color=col, weight="bold")
    for i, ln in enumerate(lines):
        txt(x + w / 2, ay + ah - 0.37 - 0.17 * i, ln, size=FS_BODY)
    if name != "Cold":      # the cold baseline calls no tutor model at all
        arrow(x + w / 2, 4.06, x + w / 2, ay + ah + 0.005, color=GREY, lw=0.8)

# =====================================================================
# Panel (b): continuous protocol and the two context scopes
# =====================================================================
txt(0.06, 2.94, "(b)", size=FS_PANEL, ha="left", weight="bold")
txt(0.34, 2.94, "Continuous protocol and context scoping",
    size=FS_HEAD, ha="left", weight="bold")

phases = [("Training", "6 items", "tutored", FILL_TUT),
          ("Immediate", "3 items", "unassisted", FILL_PROBE),
          ("Interference", "4 items", "unassisted", FILL_PROBE),
          ("Delayed", "3 items", "unassisted", FILL_PROBE),
          ("Transfer", "3 items", "unassisted", FILL_PROBE)]
gap = 0.11
pw = ((XR - XL) - 4 * gap) / 5
by, ph = 2.04, 0.56
for i, (nm, n, kind, fc) in enumerate(phases):
    x = XL + i * (pw + gap)
    box(x, by, pw, ph, fc=fc, ec=INK if i == 0 else RULE,
        lw=1.0 if i == 0 else 0.8)
    txt(x + pw / 2, by + 0.42, nm, size=FS_HEAD, weight="bold")
    txt(x + pw / 2, by + 0.26, n, size=FS_BODY, color=GREY)
    txt(x + pw / 2, by + 0.10, kind, size=FS_BODY, color=GREY)
    if i < 4:
        arrow(x + pw + 0.006, by + ph / 2, x + pw + gap - 0.006, by + ph / 2,
              color=GREY, lw=0.9, ms=5)

bracket(XL, XL + pw, 2.72, color=ORANGE, down=True)
txt(XL + pw + 0.16, 2.73,
    "Tutor context: the current training problem only, reset at each problem",
    size=FS_BODY, color=ORANGE, ha="left")

bracket(XL, XR, 1.90, color=INK, down=False)
txt(XC, 1.76,
    "Student context: one continuous conversation, carried across all 19 problems",
    size=FS_BODY)

# =====================================================================
# Panel (c): answer-phase window on one training problem
# =====================================================================
txt(0.06, 1.52, "(c)", size=FS_PANEL, ha="left", weight="bold")
txt(0.34, 1.52, "Answer-phase evaluation window (one training problem)",
    size=FS_HEAD, ha="left", weight="bold")

seq = [("S", "S1"), ("T", "T1"), ("S", "S2"), ("T", "T2"),
       ("S", "S3 = c"), ("T", "T3"), ("S", "S4")]
inwin = [True, True, True, True, True, False, False]
tg = 0.085
tw = ((XR - XL) - 6 * tg) / 7
cy, th = 0.68, 0.34
xs = []
for i, (kind, lab) in enumerate(seq):
    x = XL + i * (tw + tg)
    xs.append(x)
    ok = inwin[i]
    fc = (FILL_STU if kind == "S" else FILL_TUT) if ok else "#FBFBFB"
    box(x, cy, tw, th, fc=fc, ec=INK if ok else RULE, lw=0.9 if ok else 0.7,
        ls="-" if ok else (0, (2.2, 1.6)))
    txt(x + tw / 2, cy + th / 2, lab, size=FS_BODY,
        color=INK if ok else GREY, weight="bold" if i == 4 else "normal")

wend = xs[4] + tw
bracket(XL, wend, 1.17, color=INK, down=True)
txt((XL + wend) / 2, 1.29, "evaluation window", size=FS_BODY)
bracket(xs[5], XR, 1.17, color=GREY, down=True)
txt((xs[5] + XR) / 2, 1.29, "excluded", size=FS_BODY, color=GREY)

txt(XL, 0.52,
    "S, student turn;  T, visible tutor turn;  c, the student’s first committed answer.",
    size=FS_BODY, ha="left")
txt(XL, 0.34,
    "Leakage and both judged rubrics score T1 and T2;  independence scores S1 to S3;",
    size=FS_BODY, ha="left")
txt(XL, 0.16,
    "next-turn independence pairs each in-window tutor turn with the student turn that follows it.",
    size=FS_BODY, ha="left")

out = Path("/tmp/supp")
out.mkdir(parents=True, exist_ok=True)
fig.savefig(out / "supp_fig1_design.pdf", format="pdf")
fig.savefig(out / "supp_fig1_design.png", dpi=300)
print("wrote", out / "supp_fig1_design.pdf")
