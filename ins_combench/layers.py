from __future__ import annotations


LAYER1_BASIC = "layer1_basic_knowledge"
LAYER2_COGNITIVE = "layer2_cognitive_reasoning"
LAYER3_CASE = "layer3_case_analysis"
LAYER4_ATTACK = "layer4_multiturn_attack"

OBJECTIVE_LAYER_DIRS = {
    "basic": LAYER1_BASIC,
    "cognitive": LAYER2_COGNITIVE,
}

LAYER_SCORE_KEYS = {
    "basic": LAYER1_BASIC,
    "cognitive": LAYER2_COGNITIVE,
    "case": LAYER3_CASE,
    "attack": LAYER4_ATTACK,
}


def objective_layer_dir(layer: str) -> str:
    try:
        return OBJECTIVE_LAYER_DIRS[layer]
    except KeyError as exc:
        raise ValueError("objective layer must be `basic` or `cognitive`") from exc
