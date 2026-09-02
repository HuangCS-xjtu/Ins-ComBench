import argparse
import csv
import json
import re
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = REPO_ROOT / "data" / "layer3_case_analysis" / "questions.jsonl"
DEFAULT_SCORING_KEY = REPO_ROOT / "data" / "layer3_case_analysis" / "scoring_key.jsonl"

A_LABELS = ["部分支持", "有罪", "支持", "驳回"]

CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

LAW_ALIASES = [
    ("最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（二）", "解释二"),
    ("最高人民法院关于适用中华人民共和国保险法若干问题的解释（二）", "解释二"),
    ("保险法司法解释（二）", "解释二"),
    ("保险法解释（二）", "解释二"),
    ("解释（二）", "解释二"),
    ("最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（三）", "解释三"),
    ("保险法司法解释（三）", "解释三"),
    ("保险法解释（三）", "解释三"),
    ("最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（四）", "解释四"),
    ("保险法司法解释（四）", "解释四"),
    ("保险法解释（四）", "解释四"),
    ("最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（一）", "解释一"),
    ("保险法司法解释（一）", "解释一"),
    ("保险法解释（一）", "解释一"),
    ("中华人民共和国保险法", "保险法"),
    ("保险法", "保险法"),
    ("中华人民共和国民法典", "民法典"),
    ("民法典", "民法典"),
    ("中华人民共和国合同法", "合同法"),
    ("合同法", "合同法"),
    ("中华人民共和国海商法", "海商法"),
    ("海商法", "海商法"),
    ("中华人民共和国道路交通安全法实施条例", "道交条例"),
    ("道路交通安全法实施条例", "道交条例"),
    ("道交条例", "道交条例"),
    ("中华人民共和国道路交通安全法", "道交法"),
    ("道路交通安全法", "道交法"),
    ("道交法", "道交法"),
    ("机动车交通事故责任强制保险条例", "交强险条例"),
    ("交强险条例", "交强险条例"),
    ("中华人民共和国侵权责任法", "侵权法"),
    ("侵权责任法", "侵权法"),
    ("侵权法", "侵权法"),
    ("中华人民共和国民事诉讼法", "民诉法"),
    ("民事诉讼法", "民诉法"),
    ("民诉法", "民诉法"),
    ("中华人民共和国刑事诉讼法", "刑诉法"),
    ("刑事诉讼法", "刑诉法"),
    ("刑诉法", "刑诉法"),
    ("中华人民共和国刑法", "刑法"),
    ("刑法", "刑法"),
    ("中华人民共和国公司法", "公司法"),
    ("公司法", "公司法"),
    ("中华人民共和国产品质量法", "产品质量法"),
    ("产品质量法", "产品质量法"),
    ("中华人民共和国物权法", "物权法"),
    ("物权法", "物权法"),
    ("中华人民共和国继承法", "继承法"),
    ("继承法", "继承法"),
    ("中华人民共和国突发事件应对法", "突发事件法"),
    ("突发事件应对法", "突发事件法"),
    ("突发事件法", "突发事件法"),
    ("农业保险条例", "农业保险条例"),
    ("中华人民共和国森林法", "森林法"),
    ("森林法", "森林法"),
    ("中华人民共和国城市房地产管理法", "房地产法"),
    ("城市房地产管理法", "房地产法"),
    ("房地产法", "房地产法"),
    ("最高人民法院关于适用《中华人民共和国民事诉讼法》的解释", "民诉法解释"),
    ("民事诉讼法解释", "民诉法解释"),
    ("民诉法解释", "民诉法解释"),
    ("最高人民法院关于民事诉讼证据的若干规定", "民诉证据规定"),
    ("民事诉讼证据规定", "民诉证据规定"),
    ("最高人民法院关于审理道路交通事故损害赔偿案件适用法律若干问题的解释", "道交赔偿解释"),
    ("道路交通事故损害赔偿解释", "道交赔偿解释"),
    ("道交赔偿解释", "道交赔偿解释"),
    ("最高人民法院关于审理人身损害赔偿案件适用法律若干问题的解释", "人身赔偿解释"),
    ("人身损害赔偿解释", "人身赔偿解释"),
    ("人身赔偿解释", "人身赔偿解释"),
    ("最高人民法院关于审理商品房买卖合同纠纷案件适用法律若干问题的解释", "商品房解释"),
    ("商品房买卖合同解释", "商品房解释"),
    ("商品房解释", "商品房解释"),
    ("最高人民法院关于确定民事侵权精神损害赔偿责任若干问题的解释", "精神损害赔偿解释"),
    ("精神损害赔偿解释", "精神损害赔偿解释"),
    ("中华人民共和国涉外民事关系法律适用法", "涉外法"),
    ("涉外民事关系法律适用法", "涉外法"),
    ("涉外法", "涉外法"),
    ("英国1906年海上保险法", "英1906海险"),
    ("1906年英国海上保险法", "英1906海险"),
]

KNOWN_CODES = sorted({code for _, code in LAW_ALIASES}, key=len, reverse=True)


def read_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_case_items(questions_path=DEFAULT_QUESTIONS, scoring_key_path=DEFAULT_SCORING_KEY):
    questions = {row["item_id"]: row for row in read_jsonl(questions_path)}
    scoring = {row["item_id"]: row for row in read_jsonl(scoring_key_path)}
    if set(questions) != set(scoring):
        missing = sorted(set(questions) - set(scoring))[:10]
        extra = sorted(set(scoring) - set(questions))[:10]
        raise ValueError(f"case question/scoring ids do not match: missing={missing}, extra={extra}")

    cases = {}
    for item_id, question in questions.items():
        key = scoring[item_id]
        metadata = question.get("metadata") or {}
        cases[item_id] = {
            "id": item_id,
            "source_id": question.get("source_id"),
            "category": question.get("category", ""),
            "case_title": question.get("case_title", ""),
            "case_no": question.get("case_no", ""),
            "fact": question.get("fact", ""),
            "question_a": (question.get("conclusion_task") or {}).get("prompt", ""),
            "gold_a": key.get("conclusion_label", ""),
            "question_b": (question.get("reasoning_task") or {}).get("prompt", ""),
            "gold_statutes_full": key.get("gold_statutes_full", ""),
            "gold_statute_keys": key.get("gold_statute_keys", []),
            "gold_reasoning": key.get("gold_reasoning", ""),
            "risk_ids": metadata.get("risk_ids", []),
            "difficulty": metadata.get("difficulty", ""),
            "note": key.get("note", ""),
        }
    return cases


def cn2num(text):
    text = str(text).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    number = 0
    units = {"十": 10, "百": 100, "千": 1000}
    for ch in text:
        if ch in CN_DIGITS:
            number = CN_DIGITS[ch]
        elif ch in units:
            if number == 0:
                number = 1
            section += number * units[ch]
            number = 0
        elif ch == "万":
            section = (section + number) * 10000
            total += section
            section = 0
            number = 0
    return total + section + number


def normalize_text(text):
    return (
        str(text or "")
        .replace("《", "")
        .replace("》", "")
        .replace("（", "(")
        .replace("）", ")")
        .replace(" ", "")
        .replace("\u3000", "")
    )


def make_key(code, article, clause=None):
    article_num = cn2num(article)
    if article_num is None:
        return None
    key = f"{code}{article_num}"
    if clause:
        clause_num = cn2num(clause)
        if clause_num is not None:
            key += f"第{clause_num}款"
    return key


def extract_law_keys(text):
    text = normalize_text(text)
    keys = set()
    num = r"([零〇一二两三四五六七八九十百千万0-9]+)"
    clause = rf"(?:第{num}款)?"

    for alias, code in sorted(LAW_ALIASES, key=lambda x: len(x[0]), reverse=True):
        alias_norm = re.escape(normalize_text(alias))
        pattern = re.compile(alias_norm + rf".{{0,12}}?第{num}条{clause}")
        for m in pattern.finditer(text):
            groups = m.groups()
            key = make_key(code, groups[0], groups[1] if len(groups) > 1 else None)
            if key:
                keys.add(key)

    for code in KNOWN_CODES:
        pattern = re.compile(re.escape(code) + rf"(?:第)?{num}(?:条)?{clause}")
        for m in pattern.finditer(text):
            groups = m.groups()
            key = make_key(code, groups[0], groups[1] if len(groups) > 1 else None)
            if key:
                keys.add(key)
    return keys


def stem_key(key):
    return re.sub(r"第[0-9]+款$", "", str(key).strip())


def score_a(model_a, gold_a):
    text = str(model_a or "")
    pred = None
    if re.search(r"(?<!不)(?<!未)(保险诈骗|保险欺诈|构成.{0,6}罪|犯.{0,6}罪|刑事处罚|判处.{0,6}刑罚)", text):
        pred = "有罪"
    elif any(x in text for x in ["不予支持", "不予以支持", "予以驳回", "应予驳回"]):
        pred = "驳回"
    else:
        for label in A_LABELS:
            if label in text:
                pred = label
                break
    return 1.0 if pred == gold_a else 0.0


def prf(gold_set, pred_set, effective_hit=None):
    hit = set(effective_hit) if effective_hit is not None else (gold_set & pred_set)
    if not gold_set:
        return 0.0, 0.0, 0.0, hit
    recall = len(hit) / len(gold_set)
    precision = len(hit) / len(pred_set) if pred_set else 0.0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) else 0.0
    return recall, precision, f1, hit


def score_b1(model_b1, gold_keys, applicable_extra=None):
    gold = {stem_key(k) for k in gold_keys if str(k).strip()}
    pred = {stem_key(k) for k in extract_law_keys(model_b1)}
    recall, precision, f1, hit = prf(gold, pred)

    applicable = {stem_key(k) for k in (applicable_extra or [])}
    effective_hit = (gold & pred) | (applicable & pred)
    r2, p2, f12, relaxed_hit = prf(gold, pred, effective_hit)

    return {
        # The published v2 protocol rewards gold-statute coverage. Extra
        # citations are reported for audit, but do not reduce the score.
        "score_strict": 5.0 * recall,
        "score_relaxed": 5.0 * r2,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "relaxed_recall": r2,
        "relaxed_precision": p2,
        "relaxed_f1": f12,
        "gold_keys": sorted(gold),
        "pred_keys": sorted(pred),
        "hit": sorted(hit),
        "extra": sorted(pred - gold),
        "applicable_extra": sorted(applicable & pred),
        "relaxed_hit": sorted(relaxed_hit),
    }


def cap_b2(a_score, b2):
    if b2 is None or b2 < 0:
        return -1
    if a_score == 0 and b2 > 2:
        return 2
    return b2


def parse_judgment_score(row):
    if not row:
        return -1
    if "b2" in row:
        return row["b2"]
    dims = [row.get(k) for k in ("focus", "law", "chain", "consist")]
    if all(isinstance(v, (int, float)) for v in dims):
        return int(sum(dims))
    if "score" in row:
        return row["score"]
    return -1


def mean(values):
    values = list(values)
    return round(sum(values) / len(values), 4) if values else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--scoring-key", default=str(DEFAULT_SCORING_KEY))
    parser.add_argument("--dataset", default="", help=argparse.SUPPRESS)
    parser.add_argument("--responses", required=True)
    parser.add_argument("--b2-judgments", required=True)
    parser.add_argument("--statute-judgments", default="")
    parser.add_argument("--scores-output", default="")
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--summary-csv", default="")
    args = parser.parse_args()

    responses_path = Path(args.responses)
    run_dir = responses_path.parent
    scores_output = Path(args.scores_output) if args.scores_output else run_dir / "scores.jsonl"
    summary_json = Path(args.summary_json) if args.summary_json else run_dir / "summary.json"
    summary_csv = Path(args.summary_csv) if args.summary_csv else run_dir / "summary.csv"

    if args.dataset:
        cases = {row["id"]: row for row in read_jsonl(args.dataset)}
    else:
        cases = load_case_items(Path(args.questions), Path(args.scoring_key))
    responses = {row["id"]: row for row in read_jsonl(args.responses)}
    b2_judgments = {row["id"]: row for row in read_jsonl(args.b2_judgments)}
    statute_judgments = {}
    if args.statute_judgments and Path(args.statute_judgments).exists():
        statute_judgments = {row["id"]: row for row in read_jsonl(args.statute_judgments)}

    rows = []
    for case_id, resp in responses.items():
        if case_id not in cases:
            continue
        case = cases[case_id]
        a_score = score_a(resp.get("A_text", ""), case["gold_a"])
        applicable_extra = statute_judgments.get(case_id, {}).get("applicable_extra", [])
        b1 = score_b1(resp.get("B1_text", ""), case["gold_statute_keys"], applicable_extra)
        b2_raw = parse_judgment_score(b2_judgments.get(case_id))
        b2 = cap_b2(a_score, b2_raw)
        total_strict = a_score + b1["score_strict"] + (b2 if b2 != -1 else 0)
        total_relaxed = a_score + b1["score_relaxed"] + (b2 if b2 != -1 else 0)

        rows.append(
            {
                "id": case_id,
                "category": case.get("category", ""),
                "difficulty": case.get("difficulty", ""),
                "gold_a": case["gold_a"],
                "A": round(a_score, 2),
                "B1_strict": round(b1["score_strict"], 4),
                "B1_relaxed": round(b1["score_relaxed"], 4),
                "B1_R": round(b1["recall"], 4),
                "B1_P": round(b1["precision"], 4),
                "B1_F1": round(b1["f1"], 4),
                "B2_raw": b2_raw,
                "B2": b2,
                "total_strict": round(total_strict, 4),
                "total_relaxed": round(total_relaxed, 4),
                "B1_gold_keys": b1["gold_keys"],
                "B1_pred_keys": b1["pred_keys"],
                "B1_hit": b1["hit"],
                "B1_extra": b1["extra"],
                "B1_applicable_extra": b1["applicable_extra"],
            }
        )

    valid = [r for r in rows if r["B2"] != -1]
    summary = {
        "n": len(rows),
        "valid_n": len(valid),
        "judge_failed": len(rows) - len(valid),
        "mean_total_strict": mean(r["total_strict"] for r in valid),
        "mean_total_relaxed": mean(r["total_relaxed"] for r in valid),
        "A_accuracy": mean(r["A"] for r in rows),
        "mean_B1_strict": mean(r["B1_strict"] for r in rows),
        "mean_B1_relaxed": mean(r["B1_relaxed"] for r in rows),
        "mean_B2": mean(r["B2"] for r in valid),
    }

    write_jsonl(scores_output, rows)
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(summary_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {scores_output}")
    print(f"wrote {summary_json}")
    print(f"wrote {summary_csv}")


if __name__ == "__main__":
    main()
