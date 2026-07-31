#!/usr/bin/env python3
"""
Figure 2 -- evaluator dependence of the helpfulness signal.

Unit of analysis throughout panel (a): the replicate. Each base contributes ten
ConvTutor/PedTutor replicate pairs, and every gap shown is the mean of the ten
paired session-level differences, tested two-sided by exact Wilcoxon signed-rank
-- the same estimator and test behind Table 1a. "Detected" below means
p < 0.05 on that test.

(a) Cross-judge policy contrasts. For each of the three tutor bases, the
    ConvTutor - PedTutor gap is shown for judged helpfulness (left) and judged
    pedagogy (right), under Claude Opus 4.8 (filled square) and GPT-5.6 Sol
    (open circle), joined by a connector. A FADED marker marks a gap the signed-
    rank test does not detect (p >= 0.05), so the reader can separate a sign flip
    from a null:
      helpfulness -- on the GPT-5.5 base both judges detect a gap and the signs
        are opposite (Opus favours PedTutor, Sol favours ConvTutor): a genuine
        ordering reversal. On Sonnet the Opus gap is NOT detected, so the
        connector crosses zero from a null, not from a reversal. On Gemini both
        judges detect a gap and agree in sign.
      pedagogy -- PedTutor is favoured wherever a difference is detected (Sonnet
        and the GPT-5.5 base, both judges); on Gemini neither judge detects one,
        so both Gemini pedagogy markers are faded. Read as a manipulation check.

(b) Opus-only seven-policy ablation. Per policy, the judged-helpfulness (open)
    and judged-pedagogy (filled) means under Opus, joined by a connector:
    helpfulness is compressed across policies while pedagogy spreads out. Marker
    SHAPE carries the tutor family (circle = ConvTutor family, square = PedTutor
    family) so the grouping survives greyscale printing; colour repeats it. Sol
    did not rescore the ablation policies. The ablation reuses the confirmatory
    Sonnet ConvTutor/PedTutor replicates, so its `ConvTutor` and
    `PedTutor (full)` rows reproduce the Sonnet row of panel (a) exactly --
    validated below.

Inputs (read, never re-fitted):
    results/confirmatory{,_gpt,_gemini}/inference.json     Opus helpfulness gap + p
    results/judge_robustness/gpt-5.6-sol/<base>/judge_inference.json  Sol gaps + p
    results/ablation/per_replicate.csv                     panel (b) policy means

Computed here (the frozen pipeline reports no Opus pedagogy contrast):
    results/confirmatory{,_gpt,_gemini}/per_replicate.csv -> Opus pedagogy gap as
    the mean paired replicate difference plus its exact signed-rank p, by the
    same recipe analysis/figures/gen_sol_values.py uses for \\OpusPed*{}. Both
    the values and the p-values are pinned against CHECKPOINTS below, so this
    figure and Table 1a cannot drift apart silently.

Outputs (stem fig2_dissociation): editable-text PDF, editable SVG, PNG, TIFF.
With --sync-manuscript the PDF is copied to AI4EDU/Figures and byte-verified.
Backend: Python / matplotlib. Deterministic: identical inputs give identical
bytes for all four outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplconfig-fig2")

import numpy as np
import pandas as pd
import matplotlib as mpl
from scipy.stats import wilcoxon

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.legend_handler import HandlerTuple

mpl.rcParams.update({
    # font block copied verbatim from analysis/figures/fig3_forest.py so the two
    # figures typeset identically (Figure 3 embeds Helvetica)
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans", "sans-serif"],
    "svg.fonttype": "none",
    "svg.hashsalt": "fig2_dissociation",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.size": 8.5,
    "axes.linewidth": 0.7,
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "lines.solid_capstyle": "round",
})

BLUE = "#4477AA"      # ConvTutor family
ORANGE = "#EE7733"    # PedTutor family
OPUS = "#332288"      # primary judge
SOL = "#CC3311"       # robustness judge
C_TEXT = "#202020"    # label ink, as in fig3_forest.py
MINUS = "−"      # real minus, in the text font (NOT mathtext: mathtext would
                      # pull the glyph from DejaVu Sans and embed a second family)

STEM = "fig2_dissociation"
FIG_W_IN = 3.3125
FIG_H_IN = 3.55

ALPHA = 0.05
N_REPLICATES = 10
SCALE = (1.0, 5.0)                  # judged rubrics are 1-5
SOL_MODEL = "openai/gpt-5.6-sol"
FADE = 0.58                         # blend fraction toward white for undetected gaps

XLIM = {"help": (-0.47, 0.22), "ped": (-2.55, 0.35)}
XLIM_ABL = (2.0, 5.1)
XTICKS_ABL = (2, 3, 4, 5)

# key, results dir, long label (QA), row label (figure), row y
BASES = [("sonnet", "confirmatory", "Sonnet 4.6", "Sonnet", 2.0),
         ("gpt", "confirmatory_gpt", "GPT-5.5", "GPT-5.5", 1.0),
         ("gemini", "confirmatory_gemini", "Gemini 3.1", "Gemini", 0.0)]

ORDER = ["conv", "conv_no_final_answer", "conv_socratic",
         "ped", "ped_no_cascade", "ped_no_gate", "ped_no_tracker"]
FAMILY = {"conv": "conv", "conv_no_final_answer": "conv", "conv_socratic": "conv",
          "ped": "ped", "ped_no_gate": "ped", "ped_no_cascade": "ped",
          "ped_no_tracker": "ped"}
POLICY_LABEL = {"conv": "ConvTutor", "conv_no_final_answer": "No final answer",
                "conv_socratic": "Socratic", "ped": "PedTutor (full)",
                "ped_no_gate": "No gate", "ped_no_cascade": "No cascade",
                "ped_no_tracker": "No tracker"}
IS_HEADER = {"conv": True, "ped": True}
LABEL_X = -0.04          # right-aligned variant labels, axes fraction
HEADER_X = -0.415        # left-aligned family labels, hanging left as in Figure 3
FAMILY_COLOR = {"conv": BLUE, "ped": ORANGE}
FAMILY_MARKER = {"conv": "o", "ped": "s"}       # shape carries family (greyscale-safe)
FAMILY_MS = {"o": 6.2, "s": 5.6}                # visually matched areas

# Frozen checkpoints: (gap, two-sided p). Mirrors AI4EDU/values_sol.tex and
# Table 1a. A data or estimator change must fail here, not redraw silently.
CHECKPOINTS = {
    "sonnet": {"opus_help": (-0.093866, 0.16015625),
               "sol_help": (+0.115044, 0.00390625),
               "opus_ped": (-1.720646, 0.001953125),
               "sol_ped": (-1.240325, 0.001953125)},
    "gpt": {"opus_help": (-0.375897, 0.001953125),
            "sol_help": (+0.085595, 0.015625),
            "opus_ped": (-2.364190, 0.001953125),
            "sol_ped": (-2.017611, 0.001953125)},
    "gemini": {"opus_help": (+0.088380, 0.01953125),
               "sol_help": (+0.064566, 0.015625),
               "opus_ped": (-0.181271, 0.42578125),
               "sol_ped": (-0.016211, 1.0)},
}
ABL_CHECKPOINTS = {"help_range": 0.245315, "ped_range": 2.285474}

# Expected (sign, detected) per judge -- the claim the figure makes, asserted so
# the caption cannot outlive the data. sign: -1 favours PedTutor, +1 ConvTutor.
EXPECTED = {
    "help": {"sonnet": ((-1, False), (+1, True)),    # Opus null -> Sol favours Conv
             "gpt": ((-1, True), (+1, True)),        # the one detected reversal
             "gemini": ((+1, True), (+1, True))},    # judges agree
    "ped": {"sonnet": ((-1, True), (-1, True)),
            "gpt": ((-1, True), (-1, True)),
            "gemini": ((-1, False), (-1, False))},   # neither judge detects a gap
}


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class Fig2Data:
    pass


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _tint(hex_color: str, frac: float = FADE) -> str:
    """Blend a colour toward white; used to fade gaps the test does not detect."""
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    out = [round(c + (255 - c) * frac) for c in rgb]
    return "#%02X%02X%02X" % tuple(out)


def _signed_rank_p(a: np.ndarray, b: np.ndarray) -> float:
    """Exact two-sided Wilcoxon signed-rank p, as gen_sol_values.py computes it."""
    try:
        return float(wilcoxon(a, b, alternative="two-sided", zero_method="wilcox",
                              method="exact").pvalue)
    except TypeError:                                    # older scipy keyword
        return float(wilcoxon(a, b, alternative="two-sided", zero_method="wilcox",
                              mode="exact")[1])


def _clean_pair(df: pd.DataFrame, where: str) -> tuple[np.ndarray, np.ndarray,
                                                       np.ndarray, np.ndarray]:
    """conv/ped replicate vectors from a per_replicate frame, fully validated.

    Returns (conv_help, ped_help, conv_ped, ped_ped), each ordered by replicate_id.
    """
    need = {"condition", "replicate_id", "helpfulness_mean", "pedagogy_mean"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"{where}: per_replicate.csv missing {sorted(missing)}")
    out = []
    ids = {}
    for cond in ("conv", "ped"):
        sub = df[df.condition == cond].sort_values("replicate_id")
        if len(sub) != N_REPLICATES:
            raise ValueError(f"{where}/{cond}: expected {N_REPLICATES} replicates, "
                             f"got {len(sub)}")
        if sub.replicate_id.duplicated().any():
            raise ValueError(f"{where}/{cond}: duplicate replicate_id rows")
        vals = sub[["helpfulness_mean", "pedagogy_mean"]].to_numpy(float)
        if not np.isfinite(vals).all():
            raise ValueError(f"{where}/{cond}: non-finite or missing judged score")
        if vals.min() < SCALE[0] or vals.max() > SCALE[1]:
            raise ValueError(f"{where}/{cond}: judged score outside {SCALE}")
        ids[cond] = set(sub.replicate_id)
        out.append(vals)
    if ids["conv"] != ids["ped"]:
        raise ValueError(f"{where}: conv/ped replicate_id sets differ, cannot pair")
    (ch, cp), (ph, pp) = out[0].T, out[1].T
    return ch, ph, cp, pp


def _cell(value: float, p: float) -> dict:
    return {"value": float(value), "p": float(p), "sig": bool(p < ALPHA)}


def _connect(ax, x0, x1, y, color, lw, shrink, alpha=1.0, zorder=2) -> bool:
    """Dumbbell connector that stops `shrink` points short of each marker.

    A plain line ends at the data point, i.e. inside the marker, leaving a stub
    visible through the open (transparent-faced) markers. Shrinking in POINTS
    keeps the gap at the marker radius regardless of the data scale. When the two
    markers are closer than the shrink allowance they visibly touch, and no
    connector is drawn -- returns False so callers can report it.
    """
    px0 = ax.transData.transform((x0, y))[0]
    px1 = ax.transData.transform((x1, y))[0]
    span_pt = abs(px1 - px0) * 72.0 / ax.figure.dpi
    if span_pt <= 2 * shrink + 0.5:
        return False
    ax.annotate("", xy=(x1, y), xytext=(x0, y), xycoords="data", textcoords="data",
                annotation_clip=False, zorder=zorder,
                arrowprops=dict(arrowstyle="-", color=color, lw=lw, alpha=alpha,
                                shrinkA=shrink, shrinkB=shrink))
    return True


# --------------------------------------------------------------------------- #
def load_and_validate(repo_root: Path) -> Fig2Data:
    V = Fig2Data()
    sol_root = repo_root / "results/judge_robustness/gpt-5.6-sol"

    # ---- panel (a): cross-judge gaps (conv - ped), one row per tutor base ----
    V.bases = []
    for key, cdir, label, row_label, y in BASES:
        inf = json.loads((repo_root / "results" / cdir / "inference.json").read_text())
        ji = json.loads((sol_root / key / "judge_inference.json").read_text())

        # provenance: the two judges must have scored the SAME frozen transcripts
        if ji.get("base") != key:
            raise ValueError(f"{key}: judge_inference base is {ji.get('base')!r}")
        if ji.get("returned_model") != SOL_MODEL:
            raise ValueError(f"{key}: robustness judge is {ji.get('returned_model')!r}, "
                             f"expected {SOL_MODEL!r}")
        if ji.get("backend") != "live":
            raise ValueError(f"{key}: Sol backend is {ji.get('backend')!r}, not live")
        frozen = list(ji["original_transcript_freeze"].values())
        if len(frozen) != 1 or frozen[0] != inf["provenance"]["freeze_commit"]:
            raise ValueError(f"{key}: Sol scored freeze {frozen} but the Opus "
                             f"inference is on {inf['provenance']['freeze_commit']}")

        rep = pd.read_csv(repo_root / "results" / cdir / "per_replicate.csv")
        _, _, conv_ped, ped_ped = _clean_pair(rep, f"{cdir}")

        opus_h = inf["j1"]["P2_helpfulness"]
        sol_h = ji["session_helpfulness_contrast"]
        sol_p = ji["session_pedagogy_contrast_manipulation_check"]
        cells = {
            "opus_help": _cell(opus_h["mean_diff_conv_minus_ped"], opus_h["p_two_sided"]),
            "sol_help": _cell(sol_h["mean_diff_conv_minus_ped"], sol_h["p_two_sided"]),
            # the only quantity not present in a frozen artifact:
            "opus_ped": _cell(np.mean(conv_ped - ped_ped),
                              _signed_rank_p(conv_ped, ped_ped)),
            "sol_ped": _cell(sol_p["mean_diff_conv_minus_ped"], sol_p["p_two_sided"]),
        }
        for name, cell in cells.items():
            want_v, want_p = CHECKPOINTS[key][name]
            if abs(cell["value"] - want_v) > 1e-6 or abs(cell["p"] - want_p) > 1e-9:
                raise ValueError(
                    f"{key}.{name} is {cell['value']:+.6f} (p={cell['p']:.9g}), "
                    f"checkpoint says {want_v:+.6f} (p={want_p:.9g}) -- inputs or "
                    f"estimator changed; re-check Table 1a / values_sol.tex")
        V.bases.append(dict(key=key, label=label, row_label=row_label, y=y, **cells))

    # the figure's claim, asserted against the data
    for which, table in EXPECTED.items():
        for b in V.bases:
            got = tuple((int(np.sign(b[f"{j}_{which}"]["value"])), b[f"{j}_{which}"]["sig"])
                        for j in ("opus", "sol"))
            if got != table[b["key"]]:
                raise ValueError(f"{b['key']} {which}: (sign, detected) per judge is "
                                 f"{got}, expected {table[b['key']]}")
        for b in V.bases:                       # every value must be drawable
            lo, hi = XLIM[which]
            for j in ("opus", "sol"):
                v = b[f"{j}_{which}"]["value"]
                if not lo < v < hi:
                    raise ValueError(f"{b['key']} {j}_{which}={v:+.3f} falls outside "
                                     f"the {which} axis {XLIM[which]} and would clip")

    # ---- panel (b): Opus-only ablation policy means ----
    abl = pd.read_csv(repo_root / "results/ablation/per_replicate.csv")
    need = {"condition", "replicate_id", "helpfulness_mean", "pedagogy_mean"}
    missing = need - set(abl.columns)
    if missing:
        raise ValueError(f"ablation per_replicate.csv missing {sorted(missing)}")
    V.help_mean, V.ped_mean = {}, {}
    for c in ORDER:
        sub = abl[abl.condition == c]
        if len(sub) != N_REPLICATES:
            raise ValueError(f"ablation policy {c}: expected {N_REPLICATES} "
                             f"replicates, got {len(sub)}")
        if sub.replicate_id.duplicated().any():
            raise ValueError(f"ablation policy {c}: duplicate replicate_id rows")
        vals = sub[["helpfulness_mean", "pedagogy_mean"]].to_numpy(float)
        if not np.isfinite(vals).all():
            raise ValueError(f"ablation policy {c}: non-finite or missing judged score")
        if vals.min() < SCALE[0] or vals.max() > SCALE[1]:
            raise ValueError(f"ablation policy {c}: judged score outside {SCALE}")
        V.help_mean[c] = float(vals[:, 0].mean())
        V.ped_mean[c] = float(vals[:, 1].mean())
        for v in (V.help_mean[c], V.ped_mean[c]):
            if not XLIM_ABL[0] < v < XLIM_ABL[1]:
                raise ValueError(f"ablation policy {c}: mean {v:.3f} falls outside "
                                 f"the panel (b) axis {XLIM_ABL} and would clip")
    hmeans = np.array([V.help_mean[c] for c in ORDER])
    pmeans = np.array([V.ped_mean[c] for c in ORDER])
    V.help_range = float(hmeans.max() - hmeans.min())
    V.ped_range = float(pmeans.max() - pmeans.min())
    for name, got in (("help_range", V.help_range), ("ped_range", V.ped_range)):
        if abs(got - ABL_CHECKPOINTS[name]) > 1e-6:
            raise ValueError(f"ablation {name} is {got:.6f}, checkpoint says "
                             f"{ABL_CHECKPOINTS[name]:.6f}")

    # cross-panel invariant: the ablation reuses the confirmatory Sonnet conv/ped
    # replicates, so panel (b)'s two baseline rows must reproduce panel (a)'s
    # Sonnet row exactly. Catches an ablation run pointed at a different freeze.
    son = next(b for b in V.bases if b["key"] == "sonnet")
    for which, mean_map in (("help", V.help_mean), ("ped", V.ped_mean)):
        gap = mean_map["conv"] - mean_map["ped"]
        if abs(gap - son[f"opus_{which}"]["value"]) > 1e-9:
            raise ValueError(f"panel (b) {which} conv-ped gap {gap:+.9f} does not "
                             f"match panel (a) Sonnet {son[f'opus_{which}']['value']:+.9f}")
    return V


# --------------------------------------------------------------------------- #
def build_figure(V: Fig2Data, width=FIG_W_IN, height=FIG_H_IN):
    W, H = width, height

    def rect(x0, y0, x1, y1):
        return [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]

    fig = plt.figure(figsize=(W, H))
    ax_h = fig.add_axes(rect(0.62, 2.34, 1.78, 3.24))   # (a) helpfulness gaps
    ax_p = fig.add_axes(rect(2.16, 2.34, 3.26, 3.24))   # (a) pedagogy gaps
    ax_b = fig.add_axes(rect(1.02, 0.50, 3.22, 1.92))   # (b) ablation dumbbell

    _panel_a(ax_h, V, "help", "Helpfulness", show_y=True)
    _panel_a(ax_p, V, "ped", "Pedagogy", show_y=False)
    _panel_b(fig, ax_b, V, W, H)

    # legend for panel (a): Opus filled square, Sol open circle, faded = undetected
    faded = (Line2D([0], [0], marker="s", ls="none", ms=4.6, mfc=_tint(OPUS),
                    mec=OPUS, mew=0.6),
             Line2D([0], [0], marker="o", ls="none", ms=4.8, mfc="none",
                    mec=_tint(SOL), mew=1.2))
    handles = [Line2D([0], [0], marker="s", color=OPUS, ls="none", ms=4.8,
                      label="Opus 4.8"),
               Line2D([0], [0], marker="o", mfc="none", mec=SOL, mew=1.3,
                      color=SOL, ls="none", ms=4.8, label="GPT-5.6 Sol"),
               faded]
    # The rule is "not (p < ALPHA)", i.e. p >= ALPHA, but "p > .05" reads better
    # and is equivalent here: at n = 10 the exact two-sided signed-rank p-value
    # cannot equal .05 (nearest attainable values are .0488 and .0645). ASCII ">"
    # on purpose -- "≥" is not guaranteed in Helvetica, and one missing glyph
    # re-embeds a second font family.
    fig.legend(handles=handles,
               labels=["Opus 4.8", "GPT-5.6 Sol",
                       "faded: p > %s" % ("%.2f" % ALPHA).lstrip("0")],
               handler_map={tuple: HandlerTuple(ndivide=None, pad=0.3)},
               loc="upper center", bbox_to_anchor=(0.53, 1.005), ncol=3,
               frameon=False, fontsize=6.6, handletextpad=0.32, columnspacing=0.85)

    # panel numbering in Figure 3's style: parenthesised, 8.0 pt semibold, #202020
    fig.text(0.012, 3.41 / H, "(a)", fontsize=8.0, fontweight="semibold",
             color=C_TEXT, ha="left", va="top")
    fig.text(0.012, 2.03 / H, "(b)", fontsize=8.0, fontweight="semibold",
             color=C_TEXT, ha="left", va="top")
    return fig


def _panel_a(ax, V, which, title, show_y):
    ax.set_xlim(*XLIM[which])
    ax.set_ylim(-0.6, 2.6)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.7)
    ax.axvline(0, color="#888888", lw=0.9, zorder=1)
    for b in V.bases:
        y = b["y"]
        o, s = b["opus_" + which], b["sol_" + which]
        _connect(ax, o["value"], s["value"], y, "#B0B0B0", 1.1, shrink=2.8)
        # Opus: filled square, faded face + coloured edge when undetected
        ax.plot(o["value"], y, "s", ms=5.2, zorder=5,
                mfc=OPUS if o["sig"] else _tint(OPUS),
                mec="white" if o["sig"] else OPUS, mew=0.6)
        # Sol: open circle with a TRANSPARENT face, so a near-coincident Opus
        # marker (Gemini helpfulness) stays visible through the ring
        ax.plot(s["value"], y, "o", ms=5.4, zorder=6, mfc="none",
                mec=SOL if s["sig"] else _tint(SOL), mew=1.4)
    ax.set_yticks([b["y"] for b in V.bases])
    ax.set_yticklabels([b["row_label"] for b in V.bases] if show_y else [],
                       fontsize=7.0)
    ax.tick_params(axis="y", length=0, pad=2)
    ax.tick_params(axis="x", length=2.3, labelsize=6.6, pad=1.5)
    ax.set_title(title, fontsize=7.6, pad=3)
    ax.set_xlabel(f"Conv {MINUS} Ped", fontsize=6.8, labelpad=1)


def _panel_b(fig, ax, V, W, H):
    ypos, y = {}, 0.0
    for c in ORDER:
        if c == "ped":
            y += 0.5
        ypos[c] = -y
        y += 1.0
    ys = np.array([ypos[c] for c in ORDER])
    ax.set_xlim(*XLIM_ABL)
    ax.set_ylim(ys.min() - 0.8, ys.max() + 0.8)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.7)
    for xv in XTICKS_ABL:
        ax.axvline(xv, color="#EFEFEF", lw=0.6, zorder=0)
    ax.set_xticks(XTICKS_ABL)
    ax.tick_params(axis="x", length=2.5, labelsize=7.2, pad=1.5)
    ax.set_yticks([])
    ax.set_xlabel("Opus judged score", fontsize=7.6, labelpad=2)

    for c in ORDER:
        fam = FAMILY[c]
        col, mk = FAMILY_COLOR[fam], FAMILY_MARKER[fam]
        ms = FAMILY_MS[mk]
        h, p, yy = V.help_mean[c], V.ped_mean[c], ypos[c]
        _connect(ax, h, p, yy, col, 1.3, shrink=ms / 2 + 0.2, alpha=0.55)
        ax.plot(p, yy, mk, ms=ms, color=col, mec="white", mew=0.6, zorder=5)
        # transparent (not white) face: on `Socratic` and `No cascade` the two
        # means are ~0.06 and ~0.11 apart, so a white face would hide the
        # pedagogy marker underneath -- including the highest pedagogy mean in
        # the panel, which is the ablation's headline
        ax.plot(h, yy, mk, ms=ms, mfc="none", mec=col, mew=1.5, zorder=6)
    trans = ax.get_yaxis_transform()
    for c in ORDER:
        header = bool(IS_HEADER.get(c))
        # family colour carries the grouping on the baseline labels; the variant
        # labels sit in plain ink, with family still read off marker + connector
        ax.text(HEADER_X if header else LABEL_X, ypos[c], POLICY_LABEL[c],
                transform=trans, ha="left" if header else "right",
                va="center", clip_on=False, fontsize=7.0,
                color=FAMILY_COLOR[FAMILY[c]] if header else C_TEXT,
                fontweight="bold" if header else "normal")

    def pair(filled):
        return tuple(
            Line2D([0], [0], marker=FAMILY_MARKER[f], ms=FAMILY_MS[FAMILY_MARKER[f]] - 1.2,
                   lw=0, mec=FAMILY_COLOR[f], mew=1.0 if filled else 1.3,
                   mfc=FAMILY_COLOR[f] if filled else "none")
            for f in ("conv", "ped"))

    ax.legend([pair(False), pair(True)], ["helpfulness", "pedagogy"],
              handler_map={tuple: HandlerTuple(ndivide=None, pad=0.25)},
              loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2,
              frameon=False, fontsize=7.0, handletextpad=0.4, columnspacing=1.0,
              borderpad=0.0)


def export(fig, out_dir: Path, stem: str = STEM) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"pdf": out_dir / f"{stem}.pdf", "svg": out_dir / f"{stem}.svg",
             "png": out_dir / f"{stem}.png", "tiff": out_dir / f"{stem}.tiff"}
    fig.savefig(paths["pdf"], metadata={"CreationDate": None})
    fig.savefig(paths["svg"], metadata={"Date": None})
    fig.savefig(paths["png"], dpi=400)
    fig.savefig(paths["tiff"], dpi=600, pil_kwargs={"compression": "tiff_lzw"})
    return paths


def print_qa(V: Fig2Data):
    print("== Figure 2 QA ==")
    print("   gap (Conv - Ped), mean of 10 paired replicate differences;"
          " * = detected (p < %.2f)" % ALPHA)
    for b in V.bases:
        bits = []
        for which in ("help", "ped"):
            for j in ("opus", "sol"):
                c = b[f"{j}_{which}"]
                bits.append(f"{j} {c['value']:+.3f}{'*' if c['sig'] else ' '}"
                            f" (p={c['p']:.4g})")
        print(f"  {b['label']:10s} help: {bits[0]} {bits[1]}")
        print(f"  {'':10s} ped : {bits[2]} {bits[3]}")
    faded = [(b["key"], f"{j}_{w}") for b in V.bases for w in ("help", "ped")
             for j in ("opus", "sol") if not b[f"{j}_{w}"]["sig"]]
    print(f"  faded (undetected) markers: {faded}")
    print(f"  ablation: help range {V.help_range:.3f}, ped range {V.ped_range:.3f}")


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render Figure 2 (evaluator dependence).")
    ap.add_argument("--repo-root", type=Path, default=default_repo_root())
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--sync-manuscript", action="store_true")
    args = ap.parse_args(argv)
    repo_root = args.repo_root.resolve()
    out_dir = (args.output_dir or (repo_root / "analysis/figures")).resolve()
    V = load_and_validate(repo_root)
    print_qa(V)
    fig = build_figure(V)
    paths = export(fig, out_dir)
    plt.close(fig)
    for kind in ("pdf", "svg", "png", "tiff"):
        print("wrote %-5s %s" % (kind, paths[kind]))
    if args.sync_manuscript:
        dst = repo_root / "AI4EDU/Figures" / f"{STEM}.pdf"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths["pdf"], dst)
        if _sha(paths["pdf"]) != _sha(dst):
            raise RuntimeError("manuscript PDF sync mismatch")
        print("synced manuscript PDF -> %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
