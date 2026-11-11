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
from backlog_assistant.parser import export_stories_to_github

console = Console()


def _parse_kv(pairs: list[str] | None) -> dict[str, Any]:
    return dict(item.split("=", 1) for item in (pairs or []) if "=" in item)


def cmd_analyze(args: argparse.Namespace) -> int:
    cfg = load_scenario_config(args.config, overrides=_parse_kv(args.set))
    result = BacklogEngine(config=cfg, force_offline=args.offline).analyze(args.input, backlog_path=args.backlog, github_repo=args.github_repo)
    console.print(Panel.fit(
        f"[bold cyan]{cfg.project_title}[/bold cyan] | Domain: [yellow]{cfg.domain_name}[/yellow]\n"
        f"Source: [bold]{result.metadata.source_file}[/bold] | Mode: [green]{result.metadata.execution_mode}[/green]\n\n"
        f"[bold]Summary:[/bold] {result.summary.executive_summary}", title=f"Scenario: {cfg.scenario_id}",
    ))
    table = Table(title=f"Extracted {cfg.output_item_label}s ({len(result.stories)})", show_lines=True)
    for col in ["ID", "Title & Story", "Priority", "Category", "Alignment / Refs", "Pts / ACs"]:
        table.add_column(col)
    for s in result.stories:
        refs = f" ({', '.join(s.related_backlog_ids)})" if s.related_backlog_ids else ""
        table.add_row(s.id, f"[bold]{s.title}[/bold]\n[italic]{s.user_story}[/italic]", s.priority, s.category, f"{s.backlog_alignment.value}{refs}", f"{s.story_points} pts ({len(s.acceptance_criteria)} ACs)")
    console.print(table)

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args.input).stem
        (out / f"{stem}_result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{stem}_report.md").write_text(result.to_markdown(cfg), encoding="utf-8")
    if args.export_github:
        for line in export_stories_to_github(result.stories, repo=args.github_repo or cfg.github.repo, labels=cfg.github.issue_labels, dry_run=args.dry_run):
            console.print(f"[magenta]{line}[/magenta]")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    cfg = load_scenario_config(args.config, overrides=_parse_kv(args.set))
    engine = BacklogEngine(config=cfg, force_offline=args.offline)
    samples = sorted(p for p in Path(cfg.paths.samples_dir).iterdir() if p.suffix.lower() in {".txt", ".md", ".pdf"})
    table = Table(title=f"Golden Evaluation Scorecard — {cfg.project_title}", show_lines=True)
    for col in ["Sample Scenario", "Items", "Min ACs >= 3", "Dedup/Alignment", "Open Questions", "Status"]:
        table.add_column(col, justify="center")

    all_passed = True
    for sample in samples:
        res = engine.analyze(sample)
        ac_ok = all(len(s.acceptance_criteria) >= cfg.min_acceptance_criteria for s in res.stories)
        oq_ok = len(res.summary.open_questions) >= 1
        passed = bool(res.stories) and ac_ok and oq_ok
        all_passed = all_passed and passed
        table.add_row(sample.name, str(len(res.stories)), "PASS" if ac_ok else "FAIL", ", ".join(sorted({s.backlog_alignment.value for s in res.stories})), str(len(res.summary.open_questions)), "[bold green]PASS[/bold green]" if passed else "[bold red]FAIL[/bold red]")
    console.print(table)
    return 0 if all_passed else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Configurable FDE Smart Backlog Assistant CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    p_an = sub.add_parser("analyze", help="Analyze a requirement document (.txt, .md, .pdf)")
    p_an.add_argument("input")
    for flag in ["--config", "--backlog", "--github-repo"]:
        p_an.add_argument(flag)
    p_an.add_argument("--set", action="append", help="Override scenario variable (key=value)")
    p_an.add_argument("--export-github", action="store_true")
    p_an.add_argument("--dry-run", action="store_true", default=True)
    p_an.add_argument("--offline", action="store_true")
    p_an.add_argument("--output-dir", default="outputs")

    p_ev = sub.add_parser("evaluate", help="Run the Golden Evaluation Suite across all sample scenarios")
    p_ev.add_argument("--config")
    p_ev.add_argument("--set", action="append")
    p_ev.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    return cmd_analyze(args) if args.command == "analyze" else cmd_evaluate(args)


if __name__ == "__main__":
    sys.exit(main())
