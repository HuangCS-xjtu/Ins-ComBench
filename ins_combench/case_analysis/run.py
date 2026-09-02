from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ins_combench.model_client import ChatClient, load_model_config  # noqa: E402
try:
    from .score import extract_law_keys, load_case_items, read_jsonl, stem_key
except ImportError:
    from score import extract_law_keys, load_case_items, read_jsonl, stem_key


DEFAULT_QUESTIONS = REPO_ROOT / "data" / "layer3_case_analysis" / "questions.jsonl"
DEFAULT_SCORING_KEY = REPO_ROOT / "data" / "layer3_case_analysis" / "scoring_key.jsonl"
DEFAULT_ANSWER_PROMPT = ENGINE_ROOT / "prompts" / "answer_prompt.md"
DEFAULT_REASONING_JUDGE_PROMPT = ENGINE_ROOT / "prompts" / "reasoning_judge_prompt.md"
DEFAULT_STATUTE_JUDGE_PROMPT = ENGINE_ROOT / "prompts" / "statute_judge_prompt.md"
LAYER_DIR = "layer3_case_analysis"


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {str(row["id"]) for row in read_jsonl(path) if "id" in row and not row.get("error")}


def spread_sample(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or count >= len(items):
        return items
    if count == 1:
        return [items[len(items) // 2]]
    indices = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in indices]


def render_template(path: Path, **kwargs: Any) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in kwargs.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def parse_answer(text: str) -> tuple[str, str, str]:
    text = (text or "").strip()
    conclusion = ""
    statutes = ""
    reasoning = ""

    m = re.search(r"A结论\s*[:：]\s*(.+)", text)
    if m:
        first_line = m.group(1).strip().splitlines()[0]
        for label in ["部分支持", "有罪", "无罪", "支持", "驳回"]:
            if label in first_line:
                conclusion = label
                break
        if not conclusion:
            conclusion = first_line

    m = re.search(r"B1法条\s*[:：]\s*(.*?)(?=\n\s*B2理由\s*[:：]|$)", text, re.S)
    if m:
        statutes = m.group(1).strip()

    m = re.search(r"B2理由\s*[:：]\s*(.*)", text, re.S)
    if m:
        reasoning = m.group(1).strip()

    return conclusion, statutes, reasoning


def pick_answer_text(content: str, reasoning: str) -> str:
    content = (content or "").strip()
    if content:
        return content
    reasoning = (reasoning or "").strip()
    if all(marker in reasoning for marker in ("A结论", "B1法条", "B2理由")):
        return reasoning[reasoning.rfind("A结论") :].strip()
    return ""


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return {}
    return {}


def normalize_b2_judgment(obj: dict[str, Any]) -> dict[str, Any]:
    dims: dict[str, int] = {}
    for key in ("focus", "law", "chain", "consist"):
        value = obj.get(key)
        if isinstance(value, (int, float)) and 0 <= value <= 1:
            dims[key] = int(round(value))
    if len(dims) == 4:
        score = sum(dims.values())
    else:
        try:
            score = int(round(float(obj.get("score", -1))))
        except Exception:
            score = -1
    if score < 0 or score > 4:
        score = -1
    return {
        "focus": dims.get("focus"),
        "law": dims.get("law"),
        "chain": dims.get("chain"),
        "consist": dims.get("consist"),
        "b2": score,
        "rationale": str(obj.get("rationale", "")),
    }


def answer_case(client: ChatClient, prompt_path: Path, case: dict[str, Any]) -> dict[str, Any]:
    user_prompt = render_template(
        prompt_path,
        fact=case["fact"],
        question_a=case["question_a"],
        question_b=case["question_b"],
    )
    result = client.chat(
        [
            {"role": "system", "content": "你是保险法律合规评测的被测模型，请严格按用户要求作答。"},
            {"role": "user", "content": user_prompt},
        ]
    )
    raw_text = pick_answer_text(result.get("content", ""), result.get("reasoning_content", ""))
    conclusion, statutes, reasoning = parse_answer(raw_text)
    return {
        "id": case["id"],
        "source_id": case.get("source_id"),
        "A_text": conclusion,
        "B1_text": statutes,
        "B2_text": reasoning,
        "raw_response": raw_text,
        "content_response": result.get("content", ""),
        "reasoning_response": result.get("reasoning_content", ""),
    }


def judge_reasoning(
    client: ChatClient,
    prompt_path: Path,
    case: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    user_prompt = render_template(
        prompt_path,
        fact=case["fact"],
        gold_reasoning=case["gold_reasoning"],
        model_b2=response.get("B2_text", ""),
    )
    result = client.chat(
        [
            {"role": "system", "content": "你是严格的保险法律案例评测阅卷人。"},
            {"role": "user", "content": user_prompt},
        ]
    )
    parsed = parse_json_object(result.get("content", "") or result.get("reasoning_content", ""))
    judgment = normalize_b2_judgment(parsed)
    judgment["id"] = response["id"]
    return judgment


def judge_statutes(
    client: ChatClient,
    prompt_path: Path,
    case: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    gold = {stem_key(key) for key in case["gold_statute_keys"]}
    pred = {stem_key(key) for key in extract_law_keys(response.get("B1_text", ""))}
    extra = sorted(pred - gold)
    if not extra:
        return {"id": response["id"], "extra_statute_keys": [], "applicable_extra": []}

    user_prompt = render_template(
        prompt_path,
        fact=case["fact"],
        gold_statute_keys=json.dumps(sorted(gold), ensure_ascii=False),
        extra_statute_keys=json.dumps(extra, ensure_ascii=False),
    )
    result = client.chat(
        [
            {"role": "system", "content": "你是严格的保险法律法条适用性裁判。"},
            {"role": "user", "content": user_prompt},
        ]
    )
    parsed = parse_json_object(result.get("content", "") or result.get("reasoning_content", ""))
    applicable = []
    allowed = set(extra)
    for key in parsed.get("applicable", []):
        normalized = stem_key(key)
        if normalized in allowed:
            applicable.append(normalized)
    return {
        "id": response["id"],
        "extra_statute_keys": extra,
        "applicable_extra": sorted(set(applicable)),
    }


def run_score(
    responses: Path,
    b2_judgments: Path,
    statute_judgments: Path | None,
) -> None:
    cmd = [
        sys.executable,
        str(ENGINE_ROOT / "score.py"),
        "--responses",
        str(responses),
        "--b2-judgments",
        str(b2_judgments),
    ]
    if statute_judgments:
        cmd += ["--statute-judgments", str(statute_judgments)]
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the layer 3 case-analysis benchmark.")
    parser.add_argument("--target-config", required=True)
    parser.add_argument("--judge-config", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--judge-statutes", action="store_true")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--scoring-key", default=str(DEFAULT_SCORING_KEY))
    parser.add_argument("--answer-prompt", default=str(DEFAULT_ANSWER_PROMPT))
    parser.add_argument("--reasoning-judge-prompt", default=str(DEFAULT_REASONING_JUDGE_PROMPT))
    parser.add_argument("--statute-judge-prompt", default=str(DEFAULT_STATUTE_JUDGE_PROMPT))
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("case_%Y%m%d_%H%M%S")
    run_dir = REPO_ROOT / "runs" / run_id / LAYER_DIR
    responses_path = run_dir / "responses.jsonl"
    b2_path = run_dir / "b2_judgments.jsonl"
    statute_path = run_dir / "statute_judgments.jsonl"

    if not args.resume:
        for path in (responses_path, b2_path, statute_path):
            if path.exists():
                path.unlink()

    cases = list(load_case_items(Path(args.questions), Path(args.scoring_key)).values())
    cases.sort(key=lambda row: row["id"])
    if args.limit and args.sample_count:
        raise ValueError("Use either --limit or --sample-count, not both")
    if args.sample_count:
        cases = spread_sample(cases, args.sample_count)
    elif args.limit:
        cases = cases[: args.limit]

    target_client = ChatClient(load_model_config(Path(args.target_config)))
    judge_config = load_model_config(Path(args.judge_config))
    judge_config.setdefault("response_format", {"type": "json_object"})
    judge_client = ChatClient(judge_config)

    answered = done_ids(responses_path) if args.resume else set()
    judged = done_ids(b2_path) if args.resume else set()
    statute_judged = done_ids(statute_path) if args.resume else set()

    print(f"run_id={run_id} output={run_dir} total={len(cases)}")
    case_by_id = {case["id"]: case for case in cases}

    for case in cases:
        if case["id"] in answered:
            continue
        try:
            record = answer_case(target_client, Path(args.answer_prompt), case)
        except Exception as exc:
            record = {"id": case["id"], "source_id": case.get("source_id"), "error": str(exc)}
        append_jsonl(responses_path, record)
        print(f"answered {case['id']}")

    responses = [row for row in read_jsonl(responses_path) if row.get("id") in case_by_id]
    for response in responses:
        if response.get("error") or response["id"] in judged:
            continue
        judgment = judge_reasoning(
            judge_client,
            Path(args.reasoning_judge_prompt),
            case_by_id[response["id"]],
            response,
        )
        append_jsonl(b2_path, judgment)
        print(f"judged reasoning {response['id']} -> {judgment['b2']}")

        if args.judge_statutes and response["id"] not in statute_judged:
            statute = judge_statutes(
                judge_client,
                Path(args.statute_judge_prompt),
                case_by_id[response["id"]],
                response,
            )
            append_jsonl(statute_path, statute)
            print(f"judged statutes {response['id']} applicable_extra={len(statute['applicable_extra'])}")

    run_score(responses_path, b2_path, statute_path if args.judge_statutes else None)
    print(f"\nDone. Results are in {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
