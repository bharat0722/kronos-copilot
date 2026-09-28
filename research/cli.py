"""Command-line interface for the Phase 1 research lab."""

from __future__ import annotations

import argparse
import json

from .profiles import get_profile
from .phase1c import phase1c_report, run_phase1c
from .phase1d import (
    build_phase1d_subset,
    freeze_phase1d_policy,
    launch_phase1d_round,
    phase1d_candidates,
    phase1d_failure_diagnosis,
    phase1d_inference_audit,
    phase1d_round_report,
    phase1d_status,
    phase1d_validation_report,
    run_phase1d_round,
)
from .real_market import (
    acquire_pilot_datasets,
    build_segmentation,
    inspect_collection,
    lock_collection,
    readiness_report,
    register_collection,
    run_real_pilot,
    validate_collection,
)
from .registry import ExperimentRegistry
from .reporting import generate_markdown_report
from .runner import resume_run, run_profile
from .training_data import build_saved_yahoo_proof, protected_evaluation_boundaries, propose_training_universe, training_cutoff_spec


def main() -> None:
    parser = argparse.ArgumentParser(description="Kronos Copilot Phase 1 research lab")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a benchmark profile")
    run.add_argument("--profile", default="smoke", choices=["dry-run", "smoke", "quick", "standard", "full", "locked_test"])
    run.add_argument("--adapter", default="fake", choices=["fake", "kronos"])
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--run-id")
    run.add_argument("--force", action="store_true")
    run.add_argument("--retry-failed", action="store_true")
    run.add_argument("--interrupt-after", type=int)

    resume = sub.add_parser("resume", help="Resume a previous benchmark run")
    resume.add_argument("run_id")
    resume.add_argument("--retry-failed", action="store_true")
    resume.add_argument("--force", action="store_true")

    report = sub.add_parser("report", help="Generate a report for an existing run")
    report.add_argument("--run-id", required=True)

    status = sub.add_parser("status", help="Show registry status")
    status.add_argument("--run-id")

    list_runs = sub.add_parser("list-runs", help="List benchmark runs")
    list_runs.add_argument("--limit", type=int, default=20)

    inspect = sub.add_parser("inspect", help="Inspect one experiment")
    inspect.add_argument("experiment_id")

    acquire = sub.add_parser("acquire-data", help="Acquire Phase 1B pilot Yahoo/yfinance datasets")
    acquire.add_argument("--period", default="60d")
    acquire.add_argument("--interval", default="5m")
    acquire.add_argument("--limit", type=int, default=12)

    validate_data = sub.add_parser("validate-data", help="Validate Phase 1B acquired datasets")

    register_data = sub.add_parser("register-data", help="Register Phase 1B dataset manifests in the research registry")

    segment_data = sub.add_parser("segment-data", help="Create deterministic Phase 1B benchmark segmentation")
    segment_data.add_argument("--stride", type=int, default=120)
    segment_data.add_argument("--horizons", default="24,75,120")

    lock_data = sub.add_parser("lock-data", help="Lock the Phase 1B final test subset")
    lock_data.add_argument("--token", required=True)

    inspect_data = sub.add_parser("inspect-data", help="Inspect Phase 1B dataset, quality, segmentation, and lock status")

    pilot = sub.add_parser("run-pilot", help="Run a tiny Phase 1B real-market pilot benchmark")
    pilot.add_argument("--split", default="validation", choices=["development", "validation", "locked_test"])
    pilot.add_argument("--adapter", default="kronos", choices=["fake", "kronos"])
    pilot.add_argument("--run-id")
    pilot.add_argument("--max-symbols", type=int, default=1)
    pilot.add_argument("--max-windows", type=int, default=1)
    pilot.add_argument("--horizons", default="24")
    pilot.add_argument("--unlock-token")
    pilot.add_argument("--force", action="store_true")

    ready = sub.add_parser("phase1b-report", help="Generate Phase 1B readiness report")
    ready.add_argument("--pilot-run-id")

    phase1c_run = sub.add_parser("phase1c-run", help="Run Phase 1C canonical real-market benchmark")
    phase1c_run.add_argument("--split", required=True, choices=["development", "validation"])
    phase1c_run.add_argument("--models", required=True, choices=["baselines", "kronos", "all"])
    phase1c_run.add_argument("--run-id")
    phase1c_run.add_argument("--horizons", default="24,75,120")
    phase1c_run.add_argument("--retry-failed", action="store_true")
    phase1c_run.add_argument("--force", action="store_true")

    phase1c_ready = sub.add_parser("phase1c-report", help="Generate Phase 1C canonical benchmark report")
    phase1c_ready.add_argument("--split", required=True, choices=["development", "validation"])
    phase1c_ready.add_argument("--run-id")

    phase1d_diag = sub.add_parser("phase1d-diagnose", help="Generate Phase 1D failure diagnosis from Phase 1C artifacts")

    phase1d_audit = sub.add_parser("phase1d-audit", help="Audit Phase 1D inference path before tuning")

    phase1d_subset = sub.add_parser("phase1d-subset", help="Build deterministic Phase 1D tuning subset")
    phase1d_subset.add_argument("--per-symbol-horizon", type=int, default=2)

    phase1d_cands = sub.add_parser("phase1d-candidates", help="Write Phase 1D candidate configuration plan")

    phase1d_run = sub.add_parser("phase1d-run-round", help="Run a Phase 1D tournament round")
    phase1d_run.add_argument("--round", required=True, choices=["round1", "round2", "round3", "validation"])
    phase1d_run.add_argument("--dry-run", action="store_true")
    phase1d_run.add_argument("--retry-failed", action="store_true")
    phase1d_run.add_argument("--force", action="store_true")

    phase1d_rep = sub.add_parser("phase1d-report", help="Generate/read a Phase 1D round report")
    phase1d_rep.add_argument("--round", required=True, choices=["round1", "round2", "round3", "validation"])

    phase1d_freeze = sub.add_parser("phase1d-freeze", help="Freeze Phase 1D optimized development winner")

    phase1d_val = sub.add_parser("phase1d-validation-report", help="Generate Phase 1D validation report after the one pass")

    phase1d_launch = sub.add_parser("phase1d-launch", help="Launch a persistent local Phase 1D round")
    phase1d_launch.add_argument("--round", required=True, choices=["round1", "round2", "round3", "validation"])
    phase1d_launch.add_argument("--retry-failed", action="store_true")

    phase1d_stat = sub.add_parser("phase1d-status", help="Show Phase 1D local run status")
    phase1d_stat.add_argument("--run-id", required=True)

    sub.add_parser("phase1e-boundaries", help="Inspect Phase 1E protected benchmark boundaries")
    phase1e_proof = sub.add_parser("phase1e-proof-data", help="Build the Phase 1E-B no-network saved-Yahoo proof artifact")
    phase1e_proof.add_argument("--rows-per-symbol", type=int, default=150)

    args = parser.parse_args()
    if args.command == "run":
        result = run_profile(
            get_profile(args.profile),
            adapter_name=args.adapter,
            run_id=args.run_id,
            dry_run=args.dry_run,
            force=args.force,
            retry_failed=args.retry_failed,
            interrupt_after=args.interrupt_after,
        )
        print(json.dumps(result, indent=2))
    elif args.command == "resume":
        print(json.dumps(resume_run(args.run_id, retry_failed=args.retry_failed, force=args.force), indent=2))
    elif args.command == "report":
        print(generate_markdown_report(args.run_id))
    elif args.command == "status":
        registry = ExperimentRegistry()
        print(json.dumps(registry.summary(args.run_id), indent=2))
        registry.close()
    elif args.command == "list-runs":
        registry = ExperimentRegistry()
        rows = registry.connection.execute("select run_id,status,started_at,finished_at from runs order by started_at desc limit ?", (args.limit,)).fetchall()
        print(json.dumps([dict(row) for row in rows], indent=2))
        registry.close()
    elif args.command == "inspect":
        registry = ExperimentRegistry()
        row = registry.connection.execute("select * from experiment_specs where experiment_id=?", (args.experiment_id,)).fetchone()
        print(json.dumps(dict(row) if row else {"error": "not found"}, indent=2))
        registry.close()
    elif args.command == "acquire-data":
        print(json.dumps(acquire_pilot_datasets(period=args.period, interval=args.interval, limit=args.limit), indent=2))
    elif args.command == "validate-data":
        print(json.dumps(validate_collection(), indent=2))
    elif args.command == "register-data":
        print(json.dumps(register_collection(), indent=2))
    elif args.command == "segment-data":
        horizons = tuple(int(item.strip()) for item in args.horizons.split(",") if item.strip())
        segmentation = build_segmentation(horizons=horizons, stride=args.stride)
        print(json.dumps({
            "created_at": segmentation["created_at"],
            "schema_version": segmentation["schema_version"],
            "horizons": segmentation["horizons"],
            "stride": segmentation["stride"],
            "counts": segmentation["counts"],
            "segmentation_path": "research/data/phase1b_pilot/segmentation.json",
        }, indent=2))
    elif args.command == "lock-data":
        print(json.dumps(lock_collection(args.token), indent=2))
    elif args.command == "inspect-data":
        inspection = inspect_collection()
        segmentation = inspection.get("segmentation") or {}
        print(json.dumps({
            "collection_id": inspection.get("collection", {}).get("collection_id"),
            "dataset_count": inspection.get("quality", {}).get("dataset_count"),
            "quality_errors": inspection.get("quality", {}).get("error_count"),
            "quality_warnings": inspection.get("quality", {}).get("warning_count"),
            "segmentation_counts": segmentation.get("counts"),
            "lock": inspection.get("lock"),
        }, indent=2))
    elif args.command == "run-pilot":
        horizons = tuple(int(item.strip()) for item in args.horizons.split(",") if item.strip())
        print(json.dumps(run_real_pilot(
            split=args.split,
            adapter_name=args.adapter,
            run_id=args.run_id,
            max_symbols=args.max_symbols,
            max_windows=args.max_windows,
            horizons=horizons,
            unlock_token=args.unlock_token,
            force=args.force,
        ), indent=2))
    elif args.command == "phase1b-report":
        print(readiness_report(args.pilot_run_id))
    elif args.command == "phase1c-run":
        horizons = tuple(int(item.strip()) for item in args.horizons.split(",") if item.strip())
        print(json.dumps(run_phase1c(
            split=args.split,
            model_set=args.models,
            run_id=args.run_id,
            horizons=horizons,
            retry_failed=args.retry_failed,
            force=args.force,
        ), indent=2))
    elif args.command == "phase1c-report":
        print(phase1c_report(split=args.split, run_id=args.run_id))
    elif args.command == "phase1d-diagnose":
        print(json.dumps(phase1d_failure_diagnosis(), indent=2, default=str))
    elif args.command == "phase1d-audit":
        print(json.dumps(phase1d_inference_audit(), indent=2, default=str))
    elif args.command == "phase1d-subset":
        print(json.dumps(build_phase1d_subset(per_symbol_horizon=args.per_symbol_horizon), indent=2, default=str))
    elif args.command == "phase1d-candidates":
        print(json.dumps(phase1d_candidates(), indent=2, default=str))
    elif args.command == "phase1d-run-round":
        print(json.dumps(run_phase1d_round(args.round, retry_failed=args.retry_failed, force=args.force, dry_run=args.dry_run), indent=2, default=str))
    elif args.command == "phase1d-report":
        print(json.dumps(phase1d_round_report(args.round), indent=2, default=str))
    elif args.command == "phase1d-freeze":
        print(json.dumps(freeze_phase1d_policy(), indent=2, default=str))
    elif args.command == "phase1d-validation-report":
        print(json.dumps(phase1d_validation_report(), indent=2, default=str))
    elif args.command == "phase1d-launch":
        print(json.dumps(launch_phase1d_round(args.round, retry_failed=args.retry_failed), indent=2, default=str))
    elif args.command == "phase1d-status":
        print(json.dumps(phase1d_status(args.run_id), indent=2, default=str))
    elif args.command == "phase1e-boundaries":
        print(json.dumps({
            "protected_boundaries": protected_evaluation_boundaries(),
            "training_cutoff": training_cutoff_spec(),
            "proposed_universe": propose_training_universe(),
        }, indent=2, default=str))
    elif args.command == "phase1e-proof-data":
        print(json.dumps(build_saved_yahoo_proof(rows_per_symbol=args.rows_per_symbol), indent=2, default=str))


if __name__ == "__main__":
    main()
