from __future__ import annotations

import re
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

from .io_utils import append_jsonl, iter_jsonl, read_json, write_csv, write_json, write_jsonl
from .layers import objective_layer_dir
from .model_client import ChatClient, load_model_config


SYSTEM_PROMPT = (
    "你是保险合规 benchmark 的被测模型。请只输出选项字母，不要解释。"
    "单选题只输出一个字母，例如 B。多选题输出全部选项，用中文顿号连接，例如 A、C。"
)


def normalize_answer(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = "".join(str(v) for v in value)
    else:
        raw = str(value)
    letters = re.findall(r"[A-D]", raw.upper())
    out: List[str] = []
    seen = set()
    for letter in letters:
        if letter not in seen:
            seen.add(letter)
            out.append(letter)
    return out


def parse_model_answer(text: str, question_type: str) -> List[str]:
    if not text:
        return []
    upper = text.upper()
    tail = re.split(r"(?:答案|正确选项|应选|选择|ANSWER)\s*[:：]?", upper)[-1]
    multi = re.findall(r"[A-D](?:[、,，\s]+[A-D])+", tail)
    if multi:
        letters = normalize_answer(multi[-1])
    else:
        letters = normalize_answer(upper)
    if question_type == "single_choice":
        return letters[:1]
    return letters


def option_f1(gold: List[str], pred: List[str]) -> float:
    gold_set = set(gold)
    pred_set = set(pred)
    if not gold_set and not pred_set:
        return 1.0
    if not gold_set or not pred_set:
        return 0.0
    hit = len(gold_set & pred_set)
    precision = hit / len(pred_set)
    recall = hit / len(gold_set)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def build_prompt(item: Dict[str, Any]) -> str:
    parts = []
    if item.get("scenario"):
        parts.append("【背景情景】\n" + str(item["scenario"]))
    parts.append("【题目】\n" + str(item.get("question") or ""))
    options = item.get("options") or {}
    if isinstance(options, dict):
        option_text = "\n".join(f"{key}. {options[key]}" for key in ("A", "B", "C", "D") if key in options)
    else:
        option_text = str(options)
    parts.append("【选项】\n" + option_text)
    return "\n\n".join(parts)


def layer_paths(root: Path, layer: str) -> Tuple[Path, Path]:
    base = root / "data" / objective_layer_dir(layer)
    return base / "questions.jsonl", base / "scoring_key.jsonl"


def done_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {str(row.get("item_id")) for row in iter_jsonl(path) if not row.get("error")}


def spread_sample(items: List[Dict[str, Any]], count: int) -> List[Dict[str, Any]]:
    if count <= 0 or count >= len(items):
        return items
    if count == 1:
        return [items[len(items) // 2]]
    indices = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in indices]


def run_layer(
    root: Path,
    layer: str,
    model_config: Path,
    output: Path,
    *,
    limit: int = 0,
    sample_count: int = 0,
    resume: bool = False,
    sleep_seconds: float = 0.0,
) -> None:
    questions_path, _ = layer_paths(root, layer)
    items = list(iter_jsonl(questions_path))
    if limit and sample_count:
        raise ValueError("Use either limit or sample_count, not both")
    if sample_count:
        items = spread_sample(items, sample_count)
    elif limit:
        items = items[:limit]
    if output.exists() and not resume:
        output.unlink()
    seen = done_keys(output) if resume else set()
    client = ChatClient(load_model_config(model_config))
    print(f"layer={layer} total={len(items)} output={output} skip={len(seen)}")

    for index, item in enumerate(items, 1):
        item_id = str(item["item_id"])
        if item_id in seen:
            continue
        try:
            result = client.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(item)},
                ]
            )
            raw = result.get("content") or ""
            parsed = parse_model_answer(raw, item.get("question_type", "single_choice"))
            record = {
                "item_id": item_id,
                "layer": item.get("layer", layer),
                "dataset_id": item.get("dataset_id"),
                "question_type": item.get("question_type"),
                "raw_response": raw,
                "parsed_answer": parsed,
                "model": client.config.get("model"),
                "assistant_meta": {
                    "finish_reason": result.get("finish_reason"),
                    "usage": result.get("usage"),
                    "response_model": result.get("response_model"),
                    "response_id": result.get("response_id"),
                },
            }
        except Exception as exc:
            record = {
                "item_id": item_id,
                "layer": item.get("layer", layer),
                "dataset_id": item.get("dataset_id"),
                "question_type": item.get("question_type"),
                "raw_response": "",
                "parsed_answer": [],
                "error": str(exc),
            }
        append_jsonl(output, record)
        if index % 25 == 0 or index == len(items):
            print(f"  progress {index}/{len(items)}")
        if sleep_seconds:
            time.sleep(sleep_seconds)


def score_layer(
    root: Path,
    layer: str,
    responses: Path,
    scores_output: Path,
    summary_json: Path,
    summary_csv: Path,
) -> Dict[str, Any]:
    questions_path, scoring_key_path = layer_paths(root, layer)
    questions = {str(row["item_id"]): row for row in iter_jsonl(questions_path)}
    keys = {str(row["item_id"]): row for row in iter_jsonl(scoring_key_path)}
    rows = []

    for response in iter_jsonl(responses):
        item_id = str(response.get("item_id"))
        q = questions.get(item_id, {})
        key = keys.get(item_id, {})
        gold = normalize_answer(key.get("correct_answer"))
        pred = normalize_answer(response.get("parsed_answer"))
        is_correct = set(gold) == set(pred) and bool(gold)
        rows.append(
            {
                "item_id": item_id,
                "layer": layer,
                "dataset_id": q.get("dataset_id") or response.get("dataset_id"),
                "question_type": q.get("question_type") or response.get("question_type"),
                "risk_id": q.get("metadata", {}).get("risk_id", ""),
                "risk_name": q.get("metadata", {}).get("risk_name", ""),
                "domain": q.get("metadata", {}).get("domain", ""),
                "difficulty": q.get("metadata", {}).get("difficulty", ""),
                "correct_answer": gold,
                "pred_answer": pred,
                "is_correct": is_correct,
                "option_f1": option_f1(gold, pred),
                "raw_response": response.get("raw_response", ""),
                "error": response.get("error", ""),
            }
        )

    def acc(subset: List[Dict[str, Any]]) -> float:
        return sum(1 for r in subset if r["is_correct"]) / len(subset) if subset else 0.0

    total = len(rows)
    correct = sum(1 for r in rows if r["is_correct"])
    missing = sum(1 for r in rows if not r["pred_answer"])
    by_dataset: Dict[str, Dict[str, Any]] = {}
    by_type: Dict[str, Dict[str, Any]] = {}
    for field, container in (("dataset_id", by_dataset), ("question_type", by_type)):
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[str(row.get(field) or "UNKNOWN")].append(row)
        for name, subset in sorted(groups.items()):
            container[name] = {
                "n": len(subset),
                "accuracy": acc(subset),
                "score_100": acc(subset) * 100,
                "mean_option_f1": mean(float(r["option_f1"]) for r in subset) if subset else 0.0,
            }

    summary = {
        "layer": layer,
        "n": total,
        "correct": correct,
        "missing_answer_count": missing,
        "accuracy": correct / total if total else 0.0,
        "score_100": (correct / total * 100) if total else 0.0,
        "mean_option_f1": mean(float(r["option_f1"]) for r in rows) if rows else 0.0,
        "by_dataset": by_dataset,
        "by_question_type": by_type,
        "scoring_rule": "单选和多选均采用 strict set match；option_f1 仅作为多选辅助指标。",
    }
    write_jsonl(scores_output, rows)
    write_json(summary_json, summary)
    write_csv(
        summary_csv,
        [
            {
                "layer": layer,
                "n": total,
                "correct": correct,
                "accuracy": summary["accuracy"],
                "score_100": summary["score_100"],
                "mean_option_f1": summary["mean_option_f1"],
            }
        ],
        ["layer", "n", "correct", "accuracy", "score_100", "mean_option_f1"],
    )
    print(f"wrote {scores_output}")
    print(f"wrote {summary_json}")
    return summary
