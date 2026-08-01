#!/usr/bin/env python3
"""Render Figure 3 from canonical machine-readable result artifacts.

Panel (a) compares the pre-registered pooled mixed model with the post hoc
policy-adjusted mixed model on each tutor base. Panel (b) shows descriptive
within-policy effects for the two primary-base policies and five pre-registered
variants. All plotted values and support counts are loaded directly from JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


STEM = "fig3_forest"
FIG_W_IN = 3.3125
FIG_H_IN = 3.0

C_PRIMARY = "#2B2B2B"
C_ADJUSTED = "#666666"
C_CONV = "#0072B2"
C_PED = "#D55E00"
C_GRID = "#E8E8E8"
C_ZERO = "#3E3E3E"
C_TEXT = "#202020"
C_MUTED = "#6A6A6A"

XMIN, XMAX = -1.0, 0.30
XTICKS = (-1.0, -0.75, -0.50, -0.25, 0.0, 0.25)

BASE_SPECS = (
    ("sonnet", "confirmatory", "Sonnet"),
    ("gpt", "confirmatory_gpt", "GPT-5.5"),
    ("gemini", "confirmatory_gemini", "Gemini"),
)

POLICY_SPECS = (
    ("conv", "ConvTutor", "conv", True),
    ("conv_no_final_answer", "no-final-answer", "conv", False),
    ("conv_socratic", "Socratic", "conv", False),
    ("ped", "PedTutor (full)", "ped", True),
    ("ped_no_cascade", "no-cascade", "ped", False),
    ("ped_no_gate", "no-gate", "ped", False),
    ("ped_no_tracker", "no-tracker", "ped", False),
)


@dataclass(frozen=True)
class BaseEstimate:
    key: str
    label: str
    n_turns: int
    pooled: float
    pooled_ci: tuple[float, float]
    adjusted: float
    adjusted_ci: tuple[float, float]


@dataclass(frozen=True)
class PolicyEstimate:
    key: str
    label: str
    family: str
    baseline: bool
    estimate: float
    ci: tuple[float, float]
    usable_replicates: int
    leaky_turns: int


@dataclass(frozen=True)
class Fig3Data:
    bases: tuple[BaseEstimate, ...]
    policies: tuple[PolicyEstimate, ...]


CAPTION = (
    "Observed association between answer leakage and next-turn student "
    "independence in the answer-phase window. (a) Filled squares show the "
    "pre-registered pooled leakage coefficients from crossed replicate and "
    "problem mixed models; open circles show post hoc coefficients from the "
    "same models with tutor policy included as a fixed effect. Whiskers are "
    "model-based 95% CIs. (b) Diamonds show descriptive mean within-replicate "
    "leaky-minus-nonleaky differences for the two baseline policies and five "
    "pre-registered variants on the primary Sonnet base; whiskers are "
    "percentile-bootstrap 95% CIs over usable replicate effects. All contrasts "
    "are oriented as next-turn independence after a leaky tutor turn minus "
    "next-turn independence after a nonleaky tutor turn; zero indicates no "
    "difference. Negative values mean leaky turns are followed by less "
    "independent student work. Every displayed "
    "estimate is negative, but the policy-level estimates are descriptive and "
    "two intervals include zero. Cross-base magnitude differences should not "
    "be attributed to model family because Gemini used a provider-enforced "
    "reasoning setting."
)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"required Figure 3 input missing: {path}")
    return json.loads(path.read_text())


def _finite_interval(value: float, ci: tuple[float, float], where: str) -> None:
    vals = (value, *ci)
    if not all(math.isfinite(x) for x in vals):
        raise ValueError(f"non-finite value in {where}: {vals}")
    if not (-1.0 <= ci[0] <= value <= ci[1] <= 1.0):
        raise ValueError(f"invalid risk-difference interval in {where}: {vals}")


def load_and_validate(repo_root: Path) -> Fig3Data:
    adjusted_path = repo_root / "results/condition_adjusted_sensitivity/analysis.json"
    adjusted_json = _load_json(adjusted_path)
    if adjusted_json.get("epistemic_status") != "post hoc sensitivity analysis":
        raise ValueError("condition-adjusted artifact lost its post hoc status label")
    if set(adjusted_json.get("eligible_conditions", [])) != {"conv", "ped"}:
        raise ValueError("condition-adjusted artifact must contain only conv and ped")

    bases: list[BaseEstimate] = []
    for adjusted_key, result_dir, label in BASE_SPECS:
        inference_path = repo_root / "results" / result_dir / "inference.json"
        inference = _load_json(inference_path)
        j2 = inference["j2"]
        pooled = j2["leak_to_next_independence"]["mixed_effects"]
        adjusted = adjusted_json["results"][adjusted_key]["models"]["next_turn_independence"]

        if not pooled.get("available") or not pooled.get("converged"):
            raise ValueError(f"pooled model unavailable or unconverged for {label}")
        if not adjusted.get("converged"):
            raise ValueError(f"policy-adjusted model unconverged for {label}")
        n_turns = int(j2["n_turns"])
        if int(pooled["n_obs"]) != n_turns or int(adjusted["n_obs"]) != n_turns:
            raise ValueError(f"turn-count mismatch for {label}")
        if adjusted.get("formula") != "indep_i ~ leaks_i + C(condition)":
            raise ValueError(f"unexpected adjusted formula for {label}: {adjusted.get('formula')}")

        pooled_ci = tuple(float(x) for x in pooled["ci95"])
        adjusted_ci = tuple(float(x) for x in adjusted["confidence_interval_95"])
        base = BaseEstimate(
            key=adjusted_key,
            label=label,
            n_turns=n_turns,
            pooled=float(pooled["coef"]),
            pooled_ci=pooled_ci,
            adjusted=float(adjusted["coefficient"]),
            adjusted_ci=adjusted_ci,
        )
        _finite_interval(base.pooled, base.pooled_ci, f"{label} pooled")
        _finite_interval(base.adjusted, base.adjusted_ci, f"{label} adjusted")
        bases.append(base)

    ablation_path = repo_root / "results/ablation/ablation_analysis.json"
    ablation = _load_json(ablation_path)
    node = ablation["leak_to_next_independence_coupling_per_condition"]
    expected_policy_keys = {spec[0] for spec in POLICY_SPECS}
    if set(node) != expected_policy_keys:
        raise ValueError(
            "policy key mismatch: expected %s, found %s"
            % (sorted(expected_policy_keys), sorted(node))
        )

    policies: list[PolicyEstimate] = []
    for key, label, family, baseline in POLICY_SPECS:
        raw = node[key]
        cluster = raw["cluster_within_replicate"]
        descriptive = raw["descriptive_pooled"]
        policy = PolicyEstimate(
            key=key,
            label=label,
            family=family,
            baseline=baseline,
            estimate=float(cluster["mean_within_replicate_effect"]),
            ci=tuple(float(x) for x in cluster["effect_ci95"]),
            usable_replicates=int(cluster["n_replicates_used"]),
            leaky_turns=int(descriptive["n_leaky"]),
        )
        _finite_interval(policy.estimate, policy.ci, key)
        if not 1 <= policy.usable_replicates <= 10:
            raise ValueError(f"unexpected usable replicate count for {key}")
        if policy.leaky_turns < policy.usable_replicates:
            raise ValueError(f"fewer leaky turns than usable replicates for {key}")
        policies.append(policy)

    data = Fig3Data(tuple(bases), tuple(policies))
    all_estimates = [x for b in data.bases for x in (b.pooled, b.adjusted)]
    all_estimates.extend(p.estimate for p in data.policies)
    if not all(x < 0 for x in all_estimates):
        raise ValueError("Figure 3 direction claim failed: a displayed estimate is nonnegative")
    if sum(p.ci[0] <= 0 <= p.ci[1] for p in data.policies) != 2:
        raise ValueError("Figure 3 policy-CI claim failed: expected exactly two intervals spanning zero")
    return data


def _draw_whisker(ax, lo, hi, y, color, *, lw=1.1, cap=0.11, ls="-", zorder=3):
    ax.plot([lo, hi], [y, y], color=color, lw=lw, ls=ls, zorder=zorder,
            solid_capstyle="butt", dash_capstyle="butt")
    for x in (lo, hi):
        ax.plot([x, x], [y - cap, y + cap], color=color, lw=lw, zorder=zorder)


def build_figure(data: Fig3Data):
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.transforms import blended_transform_factory

    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans", "sans-serif"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 8.5,
        "axes.linewidth": 0.8,
        "lines.linewidth": 1.0,
        "legend.frameon": False,
    })

    fig, ax = plt.subplots(figsize=(FIG_W_IN, FIG_H_IN))
    fig.subplots_adjust(left=0.40, right=0.97, top=0.925, bottom=0.125)

    ylim = (0.65, 14.35)
    ax.set_xlim(XMIN, XMAX)
    ax.set_ylim(*ylim)
    ax.set_yticks([])
    ax.set_xticks(XTICKS)
    ax.tick_params(axis="x", labelsize=6.8, length=3, width=0.8)
    ax.set_xlabel(
        "Difference in next-turn independence",
        fontsize=6.6,
        labelpad=3,
    )
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)

    for tick in XTICKS:
        if tick != 0:
            ax.axvline(tick, color=C_GRID, lw=0.8, zorder=0)
    ax.axvline(0, color=C_ZERO, lw=1.35, zorder=1)
    ax.text(
        -0.03,
        13.58,
        "No difference",
        fontsize=6.2,
        fontstyle="italic",
        color=C_MUTED,
        ha="right",
        va="center",
    )

    label_transform = blended_transform_factory(ax.transAxes, ax.transData)
    header_x = -0.70
    label_x = -0.03

    # Panel (a): base-model replications.
    ax.text(header_x, 13.72, "(a) Across tutor bases", transform=label_transform,
            fontsize=8.0, fontweight="semibold", color=C_TEXT, ha="left", va="center",
            clip_on=False)
    base_y = (12.42, 11.32, 10.22)
    offset = 0.24
    for base, y in zip(data.bases, base_y):
        yp = y + offset
        ya = y - offset
        _draw_whisker(ax, *base.pooled_ci, yp, C_PRIMARY, lw=1.2, cap=0.10, zorder=4)
        ax.plot(base.pooled, yp, marker="s", ms=5.8, color=C_PRIMARY, ls="none", zorder=5)
        _draw_whisker(ax, *base.adjusted_ci, ya, C_ADJUSTED, lw=1.05, cap=0.10,
                      ls=(0, (3, 2)), zorder=3)
        ax.plot(base.adjusted, ya, marker="o", ms=5.2, mfc="white", mec=C_ADJUSTED,
                mew=1.15, ls="none", zorder=5)
        ax.text(label_x, y, f"{base.label} ({base.n_turns})",
                transform=label_transform, fontsize=6.6, color=C_TEXT,
                ha="right", va="center")

    legend_handles = [
        Line2D([0], [0], marker="s", color=C_PRIMARY, ls="-", lw=1.2, ms=5.5,
               label="Pre-registered pooled"),
        Line2D([0], [0], marker="o", mfc="white", mec=C_ADJUSTED,
               color=C_ADJUSTED, ls=(0, (3, 2)), lw=1.05, mew=1.1, ms=5.0,
               label="Post hoc policy-adjusted"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(-0.02, 1.05),
              ncol=1, fontsize=6.3, handlelength=1.6, handletextpad=0.4,
              columnspacing=0.9, borderaxespad=0, labelspacing=0.3)

    # Separator and panel (b): primary-base policies.
    ax.plot([XMIN, XMAX], [9.42, 9.42], color="#C8C8C8", lw=0.85,
            zorder=0, clip_on=False)
    ax.text(header_x, 8.92, "(b) Primary base (Sonnet)",
            transform=label_transform, fontsize=8.0, fontweight="semibold",
            color=C_TEXT, ha="left", va="center", clip_on=False)

    ax.text(header_x, 7.94, "ConvTutor", transform=label_transform,
            fontsize=6.9, fontweight="semibold", color=C_CONV,
            ha="left", va="center", clip_on=False)
    ax.text(header_x, 4.68, "PedTutor", transform=label_transform,
            fontsize=6.9, fontweight="semibold", color=C_PED,
            ha="left", va="center", clip_on=False)

    policy_y = (7.35, 6.45, 5.55, 4.08, 3.18, 2.28, 1.38)
    for policy, y in zip(data.policies, policy_y):
        color = C_CONV if policy.family == "conv" else C_PED
        _draw_whisker(ax, *policy.ci, y, color, lw=1.15, cap=0.12, zorder=4)
        ax.plot(policy.estimate, y, marker="D", ms=5.5 if policy.baseline else 5.0,
                color=color, mec="white", mew=0.45, ls="none", zorder=5)
        ax.text(label_x, y, policy.label, transform=label_transform, fontsize=6.6,
                fontweight="semibold" if policy.baseline else "normal",
                color=C_TEXT, ha="right", va="center")

    return fig


def export(fig, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "pdf": output_dir / f"{STEM}.pdf",
        "svg": output_dir / f"{STEM}.svg",
        "png": output_dir / f"{STEM}.png",
        "caption": output_dir / f"{STEM}_caption.txt",
    }
    fig.savefig(paths["pdf"], metadata={"CreationDate": None})
    fig.savefig(paths["svg"], metadata={"Date": None})
    fig.savefig(paths["png"], dpi=400)
    paths["caption"].write_text("Figure 3. " + CAPTION + "\n")
    return paths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def print_qa(data: Fig3Data) -> None:
    print("== Figure 3 numerical QA (loaded from canonical JSON) ==")
    for base in data.bases:
        print(
            f"{base.label:24s} n={base.n_turns:3d}  "
            f"pooled {base.pooled:+.6f} [{base.pooled_ci[0]:+.6f}, {base.pooled_ci[1]:+.6f}]  "
            f"adjusted {base.adjusted:+.6f} [{base.adjusted_ci[0]:+.6f}, {base.adjusted_ci[1]:+.6f}]"
        )
    for policy in data.policies:
        print(
            f"{policy.key:24s} {policy.estimate:+.6f} "
            f"[{policy.ci[0]:+.6f}, {policy.ci[1]:+.6f}]  "
            f"usable_reps={policy.usable_replicates} leaky_turns={policy.leaky_turns}"
        )
    print("ALL PASS: 13 displayed estimates loaded; all negative; 2/7 policy CIs span zero")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=default_repo_root())
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--verify", action="store_true",
                        help="load and strictly validate inputs without rendering")
    parser.add_argument("--sync-manuscript", action="store_true",
                        help="copy the rendered PDF to manuscript/Figures and verify byte identity")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    output_dir = (args.output_dir or (repo_root / "analysis/figures")).resolve()
    data = load_and_validate(repo_root)
    print_qa(data)
    if args.verify:
        return 0

    import matplotlib.pyplot as plt

    fig = build_figure(data)
    paths = export(fig, output_dir)
    plt.close(fig)
    for kind, path in paths.items():
        print(f"wrote {kind:7s} {path}")

    if args.sync_manuscript:
        destination = repo_root / "manuscript/Figures" / f"{STEM}.pdf"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths["pdf"], destination)
        source_hash = _sha256(paths["pdf"])
        destination_hash = _sha256(destination)
        if source_hash != destination_hash:
            raise RuntimeError("manuscript Figure 3 synchronization failed")
        print(f"synced manuscript PDF (sha256 {source_hash}) -> {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
