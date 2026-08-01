#!/usr/bin/env python3
"""Focused checks for the Figure 2 generator.

Confirms validation accepts the frozen inputs and reproduces the published
numbers (values AND two-sided p-values), that the significance pattern the
figure asserts is the one in the data, that the two panels stay mutually
consistent, that malformed or mis-provenanced inputs are rejected, that all four
outputs are written deterministically, that no second font family sneaks into the
PDF, that --sync-manuscript produces a byte-identical manuscript PDF, and that
the script runs from a working directory other than the repository root.

Run with an environment that has matplotlib + scipy (the figure was rendered
under miniforge base, matplotlib 3.10.8), e.g.:
    ~/miniforge3/bin/python -m pytest analysis/figures/test_fig2_dissociation.py -q
"""
import importlib.util
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIG = HERE / "fig2_dissociation.py"

_spec = importlib.util.spec_from_file_location("fig2_dissociation", FIG)
fig2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fig2)

# Every artifact load_and_validate touches. Kept explicit: a loader that grows a
# new input must be reflected here, or the malformed-data tests silently start
# failing on a missing file instead of the guard under test.
RESULT_FILES = [
    "results/confirmatory/inference.json",
    "results/confirmatory/per_replicate.csv",
    "results/confirmatory_gpt/inference.json",
    "results/confirmatory_gpt/per_replicate.csv",
    "results/confirmatory_gemini/inference.json",
    "results/confirmatory_gemini/per_replicate.csv",
    "results/judge_robustness/gpt-5.6-sol/sonnet/judge_inference.json",
    "results/judge_robustness/gpt-5.6-sol/gpt/judge_inference.json",
    "results/judge_robustness/gpt-5.6-sol/gemini/judge_inference.json",
    "results/ablation/per_replicate.csv",
]

CONF = "results/confirmatory/per_replicate.csv"
ABL = "results/ablation/per_replicate.csv"
SOL_SONNET = "results/judge_robustness/gpt-5.6-sol/sonnet/judge_inference.json"

# Published numbers, restated independently of fig2.CHECKPOINTS so that editing
# the module's checkpoints cannot quietly bless a new number.
PUBLISHED = {
    "sonnet": {"opus_help": (-0.093866, 0.16015625, False),
               "sol_help": (+0.115044, 0.00390625, True),
               "opus_ped": (-1.720646, 0.001953125, True),
               "sol_ped": (-1.240325, 0.001953125, True)},
    "gpt": {"opus_help": (-0.375897, 0.001953125, True),
            "sol_help": (+0.085595, 0.015625, True),
            "opus_ped": (-2.364190, 0.001953125, True),
            "sol_ped": (-2.017611, 0.001953125, True)},
    "gemini": {"opus_help": (+0.088380, 0.01953125, True),
               "sol_help": (+0.064566, 0.015625, True),
               "opus_ped": (-0.181271, 0.42578125, False),
               "sol_ped": (-0.016211, 1.0, False)},
}


def _make_repo(tmp_path):
    """A minimal repo tree holding copies of the frozen result artifacts."""
    dst = tmp_path / "repo"
    for rel in RESULT_FILES:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, dst / rel)
    return dst


def _edit_csv(repo, rel, fn):
    p = repo / rel
    df = pd.read_csv(p)
    fn(df).to_csv(p, index=False)


# --------------------------------------------------------------------------- #
# Accepts the real frozen inputs, with the published numbers
# --------------------------------------------------------------------------- #
def test_validation_accepts_frozen_inputs():
    V = fig2.load_and_validate(REPO)
    assert [b["key"] for b in V.bases] == ["sonnet", "gpt", "gemini"]
    for b in V.bases:
        for name, (value, p, sig) in PUBLISHED[b["key"]].items():
            cell = b[name]
            assert abs(cell["value"] - value) < 1e-6, (b["key"], name)
            assert abs(cell["p"] - p) < 1e-9, (b["key"], name)
            assert cell["sig"] is sig, (b["key"], name)


def test_significance_pattern_is_the_one_claimed():
    """Exactly three gaps go undetected -- the figure fades those three."""
    V = fig2.load_and_validate(REPO)
    undetected = {(b["key"], f"{j}_{w}")
                  for b in V.bases for w in ("help", "ped") for j in ("opus", "sol")
                  if not b[f"{j}_{w}"]["sig"]}
    assert undetected == {("sonnet", "opus_help"),
                          ("gemini", "opus_ped"), ("gemini", "sol_ped")}
    by_key = {b["key"]: b for b in V.bases}
    # the ONE base where both judges detect a helpfulness gap of opposite sign
    reversals = [k for k, b in by_key.items()
                 if b["opus_help"]["sig"] and b["sol_help"]["sig"]
                 and np.sign(b["opus_help"]["value"]) != np.sign(b["sol_help"]["value"])]
    assert reversals == ["gpt"]
    # Sonnet crosses zero from a null, not from a detected reversal
    assert by_key["sonnet"]["opus_help"]["sig"] is False
    assert by_key["sonnet"]["sol_help"]["sig"] is True
    # pedagogy never flips sign where it is detected
    for b in V.bases:
        if b["opus_ped"]["sig"] and b["sol_ped"]["sig"]:
            assert np.sign(b["opus_ped"]["value"]) == np.sign(b["sol_ped"]["value"]) == -1


def test_ablation_means_and_ranges():
    V = fig2.load_and_validate(REPO)
    assert abs(V.help_range - 0.245315474) < 1e-6
    assert abs(V.ped_range - 2.285473785) < 1e-6
    for c, h, p in [("conv", 4.703114478, 2.577910053),
                    ("conv_socratic", 4.804274892, 4.863383838),
                    ("ped_no_cascade", 4.948429952, 4.833816425)]:
        assert abs(V.help_mean[c] - h) < 1e-6
        assert abs(V.ped_mean[c] - p) < 1e-6
    assert set(V.help_mean) == set(fig2.ORDER)


def test_panels_agree_on_the_shared_replicates():
    """Panel (b)'s conv/ped rows ARE the confirmatory Sonnet replicates."""
    V = fig2.load_and_validate(REPO)
    son = next(b for b in V.bases if b["key"] == "sonnet")
    assert abs((V.help_mean["conv"] - V.help_mean["ped"])
               - son["opus_help"]["value"]) < 1e-9
    assert abs((V.ped_mean["conv"] - V.ped_mean["ped"])
               - son["opus_ped"]["value"]) < 1e-9


def test_figure_size_is_the_paginated_one():
    """Height changes move Figure 2 across pages; pin it."""
    V = fig2.load_and_validate(REPO)
    fig = fig2.build_figure(V)
    try:
        assert tuple(round(v, 4) for v in fig.get_size_inches()) == (3.3125, 3.55)
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


# --------------------------------------------------------------------------- #
# Rejects malformed data
# --------------------------------------------------------------------------- #
def test_missing_condition_fails(tmp_path):
    repo = _make_repo(tmp_path)
    _edit_csv(repo, CONF, lambda df: df[df.condition != "ped"])
    with pytest.raises(ValueError, match="expected 10 replicates"):
        fig2.load_and_validate(repo)


def test_mismatched_replicate_ids_fail(tmp_path):
    repo = _make_repo(tmp_path)

    def bump(df):
        idx = df.index[(df.condition == "ped") & (df.replicate_id == 9)][0]
        df.loc[idx, "replicate_id"] = 99
        return df
    _edit_csv(repo, CONF, bump)
    with pytest.raises(ValueError, match="replicate_id sets differ"):
        fig2.load_and_validate(repo)


def test_duplicate_rows_fail(tmp_path):
    repo = _make_repo(tmp_path)
    _edit_csv(repo, CONF, lambda df: pd.concat(
        [df, df[(df.condition == "conv") & (df.replicate_id == 0)]]))
    with pytest.raises(ValueError, match="expected 10 replicates|duplicate"):
        fig2.load_and_validate(repo)


def test_non_finite_fails(tmp_path):
    repo = _make_repo(tmp_path)

    def spoil(df):
        df.loc[df.index[df.condition == "conv"][0], "helpfulness_mean"] = np.inf
        return df
    _edit_csv(repo, ABL, spoil)
    with pytest.raises(ValueError, match="non-finite"):
        fig2.load_and_validate(repo)


def test_missing_value_fails(tmp_path):
    """A NaN must raise, not vanish into a skipna mean."""
    repo = _make_repo(tmp_path)

    def spoil(df):
        df.loc[df.index[df.condition == "conv"][0], "pedagogy_mean"] = None
        return df
    _edit_csv(repo, CONF, spoil)
    with pytest.raises(ValueError, match="non-finite"):
        fig2.load_and_validate(repo)


def test_out_of_scale_fails(tmp_path):
    repo = _make_repo(tmp_path)

    def spoil(df):
        df.loc[df.index[df.condition == "conv"][0], "helpfulness_mean"] = 7.5
        return df
    _edit_csv(repo, CONF, spoil)
    with pytest.raises(ValueError, match="outside"):
        fig2.load_and_validate(repo)


def test_ablation_replicate_count_fails(tmp_path):
    repo = _make_repo(tmp_path)
    _edit_csv(repo, ABL, lambda df: df.drop(
        df.index[(df.condition == "conv_socratic") & (df.replicate_id == 0)]))
    with pytest.raises(ValueError, match="expected 10"):
        fig2.load_and_validate(repo)


def test_shifted_value_trips_the_checkpoint(tmp_path):
    """Any drift in a published number must stop the build."""
    repo = _make_repo(tmp_path)

    def nudge(df):
        idx = df.index[(df.condition == "conv")][0]
        df.loc[idx, "pedagogy_mean"] = df.loc[idx, "pedagogy_mean"] + 0.5
        return df
    _edit_csv(repo, CONF, nudge)
    with pytest.raises(ValueError, match="checkpoint says"):
        fig2.load_and_validate(repo)


# --------------------------------------------------------------------------- #
# Rejects broken provenance
# --------------------------------------------------------------------------- #
def test_wrong_robustness_judge_fails(tmp_path):
    repo = _make_repo(tmp_path)
    p = repo / SOL_SONNET
    p.write_text(p.read_text().replace('"returned_model": "openai/gpt-5.6-sol"',
                                       '"returned_model": "openai/gpt-5.5"'))
    with pytest.raises(ValueError, match="robustness judge"):
        fig2.load_and_validate(repo)


def test_judges_on_different_freezes_fail(tmp_path):
    repo = _make_repo(tmp_path)
    p = repo / SOL_SONNET
    p.write_text(p.read_text().replace("1a12b566bb825ff91359fb7c526e24b161ae38d3",
                                       "0" * 40))
    with pytest.raises(ValueError, match="freeze"):
        fig2.load_and_validate(repo)


def test_value_outside_axis_fails(monkeypatch):
    """A gap that would clip against a hardcoded axis limit must raise."""
    monkeypatch.setattr(fig2, "XLIM", {"help": (-0.20, 0.22), "ped": (-2.55, 0.35)})
    with pytest.raises(ValueError, match="would clip"):
        fig2.load_and_validate(REPO)


def test_connector_is_dropped_only_when_markers_touch():
    """Geometry-dependent, so reproduce the real helpfulness panel rectangle."""
    import matplotlib.pyplot as plt
    W, H = fig2.FIG_W_IN, fig2.FIG_H_IN
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([0.62 / W, 2.34 / H, (1.78 - 0.62) / W, (3.24 - 2.34) / H])
    try:
        ax.set_xlim(*fig2.XLIM["help"])
        assert fig2._connect(ax, -0.40, 0.15, 0.0, "#B0B0B0", 1.1, shrink=2.8) is True
        assert fig2._connect(ax, 0.088, 0.065, 0.0, "#B0B0B0", 1.1, shrink=2.8) is False
    finally:
        plt.close(fig)


# --------------------------------------------------------------------------- #
# Rendering, determinism, fonts, sync, path-independence
# --------------------------------------------------------------------------- #
def test_all_outputs_created(tmp_path):
    import matplotlib.pyplot as plt
    V = fig2.load_and_validate(REPO)
    fig = fig2.build_figure(V)
    paths = fig2.export(fig, tmp_path / "out")
    plt.close(fig)
    for kind in ("pdf", "svg", "png", "tiff"):
        assert paths[kind].exists() and paths[kind].stat().st_size > 0


def test_render_is_deterministic(tmp_path):
    repo = _make_repo(tmp_path)
    for name in ("one", "two"):
        assert fig2.main(["--repo-root", str(repo),
                          "--output-dir", str(tmp_path / name)]) == 0
    for kind in ("pdf", "svg", "png", "tiff"):
        a = (tmp_path / "one" / f"{fig2.STEM}.{kind}").read_bytes()
        b = (tmp_path / "two" / f"{fig2.STEM}.{kind}").read_bytes()
        assert a == b, f"{kind} render is not byte-reproducible"


def test_pdf_embeds_no_fallback_font(tmp_path):
    """The label minus must come from the text font, not mathtext's DejaVu."""
    import matplotlib as mpl
    from matplotlib import font_manager as fm
    primary = mpl.rcParams["font.sans-serif"][0]          # Helvetica, as in Figure 3
    try:
        fm.findfont(fm.FontProperties(family=primary), fallback_to_default=False)
    except Exception:
        pytest.skip(f"{primary} unavailable: every glyph falls back, nothing to assert")
    import matplotlib.pyplot as plt
    V = fig2.load_and_validate(REPO)
    fig = fig2.build_figure(V)
    paths = fig2.export(fig, tmp_path / "fonts")
    plt.close(fig)
    assert b"DejaVu" not in paths["pdf"].read_bytes()


def test_sync_manuscript_is_byte_identical(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "manuscript/Figures").mkdir(parents=True, exist_ok=True)
    out = repo / "analysis/figures"
    assert fig2.main(["--repo-root", str(repo), "--output-dir", str(out),
                      "--sync-manuscript"]) == 0
    assert (out / f"{fig2.STEM}.pdf").read_bytes() == \
           (repo / "manuscript/Figures" / f"{fig2.STEM}.pdf").read_bytes()


def test_runs_from_other_cwd(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path)
    out = tmp_path / "elsewhere"
    monkeypatch.chdir(tmp_path)          # a cwd that is not the repo root
    assert fig2.main(["--repo-root", str(repo), "--output-dir", str(out)]) == 0
    assert (out / f"{fig2.STEM}.pdf").exists()
