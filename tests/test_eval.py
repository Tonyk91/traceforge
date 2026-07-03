"""The golden-set eval gate must pass — this is the same check CI runs as a build gate."""

from eval.runner import evaluate


def test_eval_gate_passes():
    card = evaluate()
    failed = [m.name for m in card.metrics if not m.passed]
    assert card.passed, f"eval gate failed on: {failed}"


def test_every_capability_is_scored():
    names = {m.name for m in evaluate().metrics}
    assert {"extraction", "quality_flags", "conflicts", "grounding",
            "access_control_leaks"} <= names
