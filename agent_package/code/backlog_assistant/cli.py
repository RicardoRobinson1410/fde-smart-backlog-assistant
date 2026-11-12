"""Command-line interface with runtime scenario variable overrides (`--set`) and golden rubric evaluator."""

from __future__ import annotations
import argparse, logging, sys
from pathlib import Path
from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from backlog_assistant.config import load_scenario_config
from backlog_assistant.engine import BacklogEngine

console = Console()


def _parse_kv(pairs: list[str] | None) -> dict[str, Any]:
    return dict(item.split("=", 1) for item in (pairs or []) if "=" in item)


def cmd_analyze(args: argparse.Namespace) -> int:
    cfg = load_scenario_config(args.config, overrides=_parse_kv(args.set))
    result = BacklogEngine(config=cfg, force_offline=args.offline).analyze(args.input, backlog_path=args.backlog)
    console.print(Panel.fit(
        f"[bold cyan]{cfg.project_title}[/bold cyan] | Domain: [yellow]{cfg.domain_name}[/yellow]\n"
        f"Source: [bold]{result.metadata.source_file}[/bold] (SHA256: `{result.metadata.document_sha256}`) | Mode: [green]{result.metadata.execution_mode}[/green]\n"
        f"PII Redacted: [bold]{result.metadata.pii_redacted_count}[/bold] | Est. Tokens: [bold]{result.metadata.estimated_tokens}[/bold] | Est. Cost: [bold]${result.metadata.estimated_cost_usd:.6f}[/bold]\n\n"
        f"[bold]Summary:[/bold] {result.summary.executive_summary}", title=f"Scenario: {cfg.scenario_id}",
    ))
    table = Table(title=f"Extracted {cfg.output_item_label}s ({len(result.stories)})", show_lines=True)
    for col in ["ID", "Title & Story", "Priority / HITL", "Category", "Alignment / Refs", "Pts / ACs"]:
        table.add_column(col)
    for s in result.stories:
        refs = f" ({', '.join(s.related_backlog_ids)})" if s.related_backlog_ids else ""
        hitl = "\n[bold yellow][HITL Gate][/bold yellow]" if s.requires_human_approval else ""
        table.add_row(s.id, f"[bold]{s.title}[/bold]\n[italic]{s.user_story}[/italic]", f"{s.priority}{hitl}", s.category, f"{s.backlog_alignment.value}{refs}", f"{s.story_points} pts ({len(s.acceptance_criteria)} ACs)")
    console.print(table)

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args.input).stem
        (out / f"{stem}_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{stem}_report.md").write_text(result.to_markdown(cfg), encoding="utf-8")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Run the golden-dataset evaluation harness (code graders + LLM judge) and gate on pass rate."""
    from backlog_assistant.evaluation import run_evaluation

    cfg = load_scenario_config(args.config, overrides=_parse_kv(args.set))
    run = run_evaluation(
        cfg, dataset_path=args.dataset, offline=args.offline, judge_enabled=not args.no_judge,
        judge_model=args.judge_model, case_ids=args.case or None, max_workers=args.workers,
    )
    table = Table(title=f"Agent Evaluation — {run.mode} • agent {run.agent_model} • judge {run.judge_model or 'off'}", show_lines=True)
    for col in ["Case", "Category", "Status", "Score", "Failed checks", "Cost $"]:
        table.add_column(col)
    for c in run.cases:
        failed = ", ".join(ch.name for ch in c.checks if ch.status == "fail") or "-"
        color = "green" if c.status == "PASS" else "red"
        table.add_row(f"{c.case.id} {c.case.name}", c.case.category, f"[bold {color}]{c.status}[/bold {color}]",
                      f"{c.score:.0%}", failed, f"{c.metrics.cost_usd + c.metrics.judge_cost_usd:.4f}")
    console.print(table)
    s = run.summary
    console.print(f"Passed {s.passed}/{s.total_cases} ({s.pass_rate:.0%}) • weighted score {s.avg_score:.0%} • "
                  f"critical failures {s.critical_failures} • judge avg {s.judge_avg} • real cost ${s.total_cost_usd:.4f} • run {run.run_id}")
    gate_ok = s.pass_rate >= args.min_pass_rate and s.critical_failures == 0 if args.strict else s.pass_rate >= args.min_pass_rate
    return 0 if gate_ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Configurable FDE Smart Backlog Assistant CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    p_an = sub.add_parser("analyze", help="Analyze a requirement document (.txt, .md, .pdf)")
    p_an.add_argument("input")
    for flag in ["--config", "--backlog"]:
        p_an.add_argument(flag)
    p_an.add_argument("--set", action="append", help="Override scenario variable (key=value)")
    p_an.add_argument("--offline", action="store_true")
    p_an.add_argument("--output-dir", default="outputs")

    p_ev = sub.add_parser("evaluate", help="Run the golden-dataset agent evaluation (code graders + LLM judge)")
    p_ev.add_argument("--config")
    p_ev.add_argument("--set", action="append")
    p_ev.add_argument("--offline", action="store_true", help="Evaluate the no-LLM heuristic baseline")
    p_ev.add_argument("--dataset", default="evals/golden_dataset.json")
    p_ev.add_argument("--case", action="append", help="Only run this case ID (repeatable)")
    p_ev.add_argument("--no-judge", action="store_true", help="Skip the LLM-as-judge stage")
    p_ev.add_argument("--judge-model", default="gpt-4o")
    p_ev.add_argument("--workers", type=int, default=4)
    p_ev.add_argument("--min-pass-rate", type=float, default=0.0, help="CI gate: exit 1 if pass rate is below this (0-1)")
    p_ev.add_argument("--strict", action="store_true", help="CI gate: also fail on any critical check failure")
    args = parser.parse_args(argv)
    return cmd_analyze(args) if args.command == "analyze" else cmd_evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
