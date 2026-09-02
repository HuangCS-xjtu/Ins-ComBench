from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .aggregate import aggregate
from .io_utils import benchmark_root, resolve_path
from .layers import LAYER4_ATTACK, objective_layer_dir
from .objective import run_layer, score_layer


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print("\n$ " + " ".join(str(x) for x in cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def cmd_run_objective(args: argparse.Namespace) -> None:
    root = benchmark_root()
    out_dir = root / "runs" / args.run_id / objective_layer_dir(args.layer)
    run_layer(
        root,
        args.layer,
        resolve_path(root, args.model_config),
        out_dir / "responses.jsonl",
        limit=args.limit,
        sample_count=args.sample_count,
        resume=args.resume,
        sleep_seconds=args.sleep,
    )


def cmd_score_objective(args: argparse.Namespace) -> None:
    root = benchmark_root()
    out_dir = root / "runs" / args.run_id / objective_layer_dir(args.layer)
    score_layer(
        root,
        args.layer,
        out_dir / "responses.jsonl",
        out_dir / "scores.jsonl",
        out_dir / "summary.json",
        out_dir / "summary.csv",
    )


def cmd_run_case(args: argparse.Namespace) -> None:
    root = benchmark_root()
    engine_root = root / "ins_combench" / "case_analysis"
    target_config = resolve_path(root, args.target_config or "ins_combench/configs/target_model.json")
    judge_config = resolve_path(root, args.judge_config or "ins_combench/configs/judge_model.json")
    cmd = [
        sys.executable,
        str(engine_root / "run.py"),
        "--target-config",
        str(target_config),
        "--judge-config",
        str(judge_config),
        "--run-id",
        args.run_id,
    ]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.sample_count:
        cmd += ["--sample-count", str(args.sample_count)]
    if args.resume:
        cmd += ["--resume"]
    if args.judge_statutes:
        cmd += ["--judge-statutes"]
    run_cmd(cmd, engine_root)


def cmd_run_attack(args: argparse.Namespace) -> None:
    root = benchmark_root()
    engine_root = root / "ins_combench" / "multiturn_attack"
    run_dir = root / "runs" / args.run_id / LAYER4_ATTACK
    run_dir.mkdir(parents=True, exist_ok=True)
    responses = run_dir / "multiturn_attack_responses.jsonl"
    scores = run_dir / "multiturn_attack_scores.jsonl"
    score_summary = run_dir / "multiturn_attack_score_summary.csv"
    metrics_json = run_dir / "metrics_summary.json"
    group_csv = run_dir / "metrics_by_group.csv"

    target_config = resolve_path(root, args.target_config or "ins_combench/configs/target_model.json")
    judge_config = resolve_path(root, args.judge_config or "ins_combench/configs/judge_model.json")
    run_cmd(
        [
            sys.executable,
            str(engine_root / "run.py"),
            "--input",
            str(root / "data" / LAYER4_ATTACK / "questions.jsonl"),
            "--output",
            str(responses),
            "--config",
            str(target_config),
            "--run-id",
            args.run_id,
        ]
        + (["--limit", str(args.limit)] if args.limit else [])
        + (["--sample-count", str(args.sample_count)] if args.sample_count else [])
        + (["--resume"] if args.resume else []),
        engine_root,
    )
    run_cmd(
        [
            sys.executable,
            str(engine_root / "score.py"),
            "--responses",
            str(responses),
            "--output",
            str(scores),
            "--summary",
            str(score_summary),
            "--config",
            str(judge_config),
            "--prompt",
            str(engine_root / "prompts" / "judge_prompt.md"),
            "--scoring-key",
            str(root / "data" / LAYER4_ATTACK / "scoring_key.jsonl"),
        ]
        + (["--limit", str(args.limit)] if args.limit else [])
        + (["--resume"] if args.resume else []),
        engine_root,
    )
    run_cmd(
        [
            sys.executable,
            str(engine_root / "summarize.py"),
            "--scores",
            str(scores),
            "--metrics-json",
            str(metrics_json),
            "--group-csv",
            str(group_csv),
        ],
        engine_root,
    )


def cmd_aggregate(args: argparse.Namespace) -> None:
    root = benchmark_root()
    out_dir = root / "runs" / args.run_id
    aggregate(root, args.run_id, out_dir / "overall_summary.json", out_dir / "overall_summary.csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Insurance compliance benchmark CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run-objective", help="Run basic/cognitive objective questions.")
    p.add_argument("--layer", choices=["basic", "cognitive"], required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--model-config", default="ins_combench/configs/target_model.json")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--sample-count", type=int, default=0, help="Evenly sample items across the layer.")
    p.add_argument("--sleep", type=float, default=0.0)
    p.add_argument("--resume", action="store_true")
    p.set_defaults(func=cmd_run_objective)

    p = sub.add_parser("score-objective", help="Score basic/cognitive objective questions.")
    p.add_argument("--layer", choices=["basic", "cognitive"], required=True)
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_score_objective)

    p = sub.add_parser("run-case", help="Run layer 3 case benchmark.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--target-config", default="")
    p.add_argument("--judge-config", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--sample-count", type=int, default=0, help="Evenly sample cases across the layer.")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--judge-statutes", action="store_true")
    p.set_defaults(func=cmd_run_case)

    p = sub.add_parser("run-attack", help="Run layer 4 multiturn attack benchmark.")
    p.add_argument("--run-id", required=True)
    p.add_argument("--target-config", default="")
    p.add_argument("--judge-config", default="")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--sample-count", type=int, default=0, help="Evenly sample attacks across the layer.")
    p.add_argument("--resume", action="store_true")
    p.set_defaults(func=cmd_run_attack)

    p = sub.add_parser("aggregate", help="Aggregate all available layer summaries.")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_aggregate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
