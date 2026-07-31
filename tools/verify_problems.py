"""Independently verify domain/algebra/problems.yaml.

Checks:
  1. Each canonical_answer matches an independent sympy re-derivation (equations
     hardcoded here, mirroring each prompt — a second pair of eyes on the math).
  2. delayed/transfer answers differ from ALL training answers (anti-memorization).
  3. canonical_answer does not appear as a number token in the problem text
     (so a leakage numeric hit really means the answer was revealed).
  4. role counts match the §5 design (6/3/4/3/3); isomorph_of references exist.
Run: python tools/verify_problems.py
"""
import re
import sys
from pathlib import Path

import yaml
from sympy import Rational, symbols, solve, Eq

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "domain/algebra/problems.yaml"

x = symbols("x")
P = lambda n: Rational(n, 100)  # percent as exact fraction


def _d(eq_lhs, eq_rhs):
    return float(solve(Eq(eq_lhs, eq_rhs), x)[0])


# Independent re-derivations (id -> expected answer), written from the prompts.
EXPECTED = {
    # training — mixture
    "train-1": _d(P(50)*x + P(20)*48, P(30)*(x + 48)),       # add 50% to 48L 20% -> 30%
    "train-2": _d(P(40)*30, P(25)*(30 + x)),                 # water to 30L 40% -> 25%
    "train-3": _d(P(60)*x + P(20)*(40 - x), P(34)*40),       # L of 60% in 40L 34%
    "train-4": _d(x + P(20)*36, P(40)*(x + 36)),             # pure acid to 36L 20% -> 40%
    "train-5": _d(P(70)*x + P(10)*42, P(30)*(x + 42)),       # add 70% to 42L 10% -> 30%
    "train-6": _d(P(50)*18, P(20)*(18 + x)),                 # water to 18L 50% -> 20%
    # immediate — mixture
    "immediate-1": _d(P(80)*x + P(20)*46, P(40)*(x + 46)),   # add 80% to 46L 20% -> 40%
    "immediate-2": _d(P(60)*8, P(20)*(8 + x)),               # water to 8L 60% -> 20%
    "immediate-3": _d(P(80)*x + P(30)*(50 - x), P(54)*50),   # L of 80% in 50L 54%
    # interference — relative motion
    "interfere-1": _d(3*x + 3*(x + 4), 60),                  # slower cyclist
    "interfere-2": _d(50*(x + 2), 70*x),                     # hours for 2nd car to catch
    "interfere-3": _d(36*(10 - x), 24*(10 + x)),             # current
    "interfere-4": _d(3*x + 3*(x + 20), 300),                # slower train
    # delayed — mixture
    "delayed-1": _d(P(50)*x + P(20)*52, P(30)*(x + 52)),     # add 50% to 52L 20% -> 30%
    "delayed-2": _d(P(40)*55, P(25)*(55 + x)),               # water to 55L 40% -> 25%
    "delayed-3": _d(x + P(20)*57, P(40)*(x + 57)),           # pure acid to 57L 20% -> 40%
    # transfer — same weighted-average structure, new surface
    "transfer-1": _d(12*x + 7*(75 - x), 9*75),               # lb of $12 beans in 75lb $9
    "transfer-2": _d(x + P(30)*40, P(50)*(x + 40)),          # pure copper to 40kg 30% -> 50%
    "transfer-3": _d(93*x + 87*(30 - x), 91*30),             # gallons premium (octane blend)
}


def numbers_in(text):
    return set(float(n) for n in re.findall(r"\d+(?:\.\d+)?", text))


def main():
    data = yaml.safe_load(open(PATH))
    probs = data["problems"]
    ids = [p["id"] for p in probs]
    by_role = {}
    answers_by_role = {}
    ok = True

    for p in probs:
        by_role.setdefault(p["role"], []).append(p["id"])
        answers_by_role.setdefault(p["role"], []).append(float(p["canonical_answer"]))

        exp = EXPECTED.get(p["id"])
        got = float(p["canonical_answer"])
        if exp is None:
            print(f"FAIL {p['id']}: no independent check defined"); ok = False
        elif abs(float(exp) - got) > 1e-9:
            print(f"FAIL {p['id']}: yaml={got} but re-derived={float(exp)}"); ok = False

        if got in numbers_in(p["prompt"]):
            print(f"FAIL {p['id']}: answer {got} appears in the problem text"); ok = False

        iso = p.get("isomorph_of")
        if iso and iso not in ids:
            print(f"FAIL {p['id']}: isomorph_of '{iso}' not found"); ok = False

    train_ans = set(answers_by_role.get("training", []))
    for role in ("delayed", "transfer"):
        clash = set(answers_by_role.get(role, [])) & train_ans
        if clash:
            print(f"FAIL: {role} answers overlap training answers: {sorted(clash)}"); ok = False

    # all relationship-family answers should be two-digit (>=10) to avoid
    # incidental small-number leakage hits (step numbers, small counts).
    for p in probs:
        if p["role"] != "interference" and float(p["canonical_answer"]) < 10:
            print(f"WARN {p['id']}: single-digit answer {p['canonical_answer']} (leakage-noise risk)")

    want = {"training": 6, "immediate": 3, "interference": 4, "delayed": 3, "transfer": 3}
    counts = {r: len(v) for r, v in by_role.items()}
    if counts != want:
        print(f"FAIL: role counts {counts} != {want}"); ok = False

    print(f"\nTotal problems: {len(probs)}")
    print(f"Role counts: {counts}")
    print(f"Training answers: {sorted(train_ans)}")
    print(f"Delayed answers : {sorted(answers_by_role.get('delayed', []))}")
    print(f"Transfer answers: {sorted(answers_by_role.get('transfer', []))}")
    print("\n" + ("ALL CHECKS PASSED" if ok else "*** CHECKS FAILED ***"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
