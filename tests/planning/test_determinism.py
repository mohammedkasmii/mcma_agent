"""INC-05 — plan determinism property: same input (even with shuffled line
order) yields identical steps, input_hash, and plan_hash. No wall-clock,
randomness, or set-iteration order may leak into the plan."""

import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from mcma.mapping.wexia import parse_wexia
from mcma.planning.registry import default_registry

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "characterization"
    / "wexia_normal_synthetic.json"
)


def _raw():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw.pop("_comment", None)
    # A second labour line so there are 4 lines to shuffle meaningfully.
    raw["chiffrages"][0]["lignes_pieces"].append(
        {"item_type": "part", "item_name": "retroviseur", "part_type": "adaptable", "subtotal": 100}
    )
    raw["chiffrages"][0]["total_cost"] = 2100
    raw["chiffrages"][0]["tax_amount"] = 420
    raw["chiffrages"][0]["final_cost"] = 2520
    return raw


def _build(raw):
    return default_registry().get("mission_normal")(parse_wexia(raw))


@settings(max_examples=60, deadline=None)
@given(st.randoms(use_true_random=False))
def test_plan_is_deterministic_same_input_same_hash(rng):
    baseline = _build(_raw())

    shuffled = _raw()
    rng.shuffle(shuffled["chiffrages"][0]["lignes_pieces"])
    rng.shuffle(shuffled["chiffrages"][0]["lignes_mo"])
    other = _build(shuffled)

    assert other.steps == baseline.steps
    assert other.provenance.input_hash == baseline.provenance.input_hash
    assert other.provenance.plan_hash == baseline.provenance.plan_hash
    assert other == baseline


def test_repeated_builds_are_bit_identical():
    a, b = _build(_raw()), _build(_raw())
    assert a == b
    assert a.canonical_json() == b.canonical_json()
