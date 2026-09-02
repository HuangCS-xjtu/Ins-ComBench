from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]

LAYER_DIRS = {
    "layer1_basic_knowledge": 1100,
    "layer2_cognitive_reasoning": 1200,
    "layer3_case_analysis": 92,
    "layer4_multiturn_attack": 90,
}

FORBIDDEN_QUESTION_KEYS = {
    "answer",
    "correct_answer",
    "answer_explanation",
    "explanation",
    "references",
    "gold_a",
    "gold_b",
    "gold_reasoning",
    "gold_statutes_full",
    "gold_statute_keys",
    "conclusion_label",
    "legal_boundary",
    "legal_basis",
    "target_violation",
    "compliant_behavior",
    "scoring_points",
}

ATTACK_STRATEGIES = {
    "business_pressure",
    "information_weakening",
    "process_bypass",
    "authority_pressure",
    "default_consent",
    "bundled_consent",
    "roleplay_or_training_frame",
    "vendor_pressure",
}


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSONL: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            yield row


def validate_layer(layer_dir: str, expected_count: int) -> dict[str, Any]:
    base = REPO_ROOT / "data" / layer_dir
    questions_path = base / "questions.jsonl"
    scoring_path = base / "scoring_key.jsonl"
    if not questions_path.exists():
        raise FileNotFoundError(questions_path)
    if not scoring_path.exists():
        raise FileNotFoundError(scoring_path)

    questions = list(iter_jsonl(questions_path))
    scoring = list(iter_jsonl(scoring_path))
    q_ids = [str(row.get("item_id")) for row in questions]
    s_ids = [str(row.get("item_id")) for row in scoring]

    if len(questions) != expected_count:
        raise ValueError(f"{layer_dir}: expected {expected_count} questions, found {len(questions)}")
    if len(scoring) != expected_count:
        raise ValueError(f"{layer_dir}: expected {expected_count} scoring rows, found {len(scoring)}")
    if len(set(q_ids)) != len(q_ids):
        dupes = [item for item, count in Counter(q_ids).items() if count > 1]
        raise ValueError(f"{layer_dir}: duplicate question item_id: {dupes[:10]}")
    if len(set(s_ids)) != len(s_ids):
        dupes = [item for item, count in Counter(s_ids).items() if count > 1]
        raise ValueError(f"{layer_dir}: duplicate scoring item_id: {dupes[:10]}")
    if set(q_ids) != set(s_ids):
        missing = sorted(set(q_ids) - set(s_ids))[:10]
        extra = sorted(set(s_ids) - set(q_ids))[:10]
        raise ValueError(f"{layer_dir}: item_id mismatch, missing={missing}, extra={extra}")

    leaked = []
    for row in questions:
        bad = sorted(FORBIDDEN_QUESTION_KEYS & set(row))
        if bad:
            leaked.append({"item_id": row.get("item_id"), "keys": bad})
    if leaked:
        raise ValueError(f"{layer_dir}: forbidden evaluator keys in questions: {leaked[:5]}")

    if layer_dir in {"layer1_basic_knowledge", "layer2_cognitive_reasoning"}:
        for row in questions:
            options = row.get("options")
            if not isinstance(options, dict) or sorted(options) != ["A", "B", "C", "D"]:
                raise ValueError(f"{layer_dir}: invalid options for {row.get('item_id')}")
        for row in scoring:
            answer = row.get("correct_answer")
            if not isinstance(answer, list) or not answer:
                raise ValueError(f"{layer_dir}: missing correct_answer for {row.get('item_id')}")
    elif layer_dir == "layer3_case_analysis":
        for row in questions:
            if not row.get("conclusion_task") or not row.get("reasoning_task"):
                raise ValueError(f"{layer_dir}: missing case task prompts for {row.get('item_id')}")
            track = row.get("metadata", {}).get("label_track")
            expected_labels = {
                "民事": ["支持", "部分支持", "驳回"],
                "刑事": ["有罪", "无罪"],
            }.get(track)
            if expected_labels is None or row["conclusion_task"].get("labels") != expected_labels:
                raise ValueError(
                    f"{layer_dir}: invalid conclusion labels for {row.get('item_id')}"
                )
        for row in scoring:
            if not row.get("conclusion_label") or not row.get("gold_reasoning"):
                raise ValueError(f"{layer_dir}: missing case scoring fields for {row.get('item_id')}")
    elif layer_dir == "layer4_multiturn_attack":
        for row in questions:
            turns = row.get("user_turns")
            if not isinstance(turns, list) or len(turns) != 4:
                raise ValueError(f"{layer_dir}: missing user_turns for {row.get('item_id')}")
            strategies = row.get("attack_strategies")
            if not isinstance(strategies, list) or not strategies:
                raise ValueError(f"{layer_dir}: missing attack strategies for {row.get('item_id')}")
            unknown = sorted(set(strategies) - ATTACK_STRATEGIES)
            if unknown or len(strategies) != len(set(strategies)):
                raise ValueError(
                    f"{layer_dir}: invalid attack strategies for {row.get('item_id')}: {strategies}"
                )
        for row in scoring:
            if not row.get("legal_boundary") or not row.get("compliant_behavior"):
                raise ValueError(f"{layer_dir}: missing attack scoring fields for {row.get('item_id')}")
            if row.get("attack_strategies") != next(
                question["attack_strategies"]
                for question in questions
                if question["item_id"] == row["item_id"]
            ):
                raise ValueError(
                    f"{layer_dir}: strategy mismatch for {row.get('item_id')}"
                )

    return {
        "layer": layer_dir,
        "questions": len(questions),
        "scoring_key": len(scoring),
        "sample_item_id": q_ids[0] if q_ids else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate canonical benchmark data files.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable JSON summary.")
    args = parser.parse_args()

    results = [validate_layer(layer, expected) for layer, expected in LAYER_DIRS.items()]
    if args.json:
        print(json.dumps({"ok": True, "layers": results}, ensure_ascii=False, indent=2))
    else:
        print("OK: dataset validation passed")
        for result in results:
            print(
                f"- {result['layer']}: questions={result['questions']} "
                f"scoring_key={result['scoring_key']} sample={result['sample_item_id']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
