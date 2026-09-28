"""SQLite experiment registry with resume/idempotence support."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .config import REGISTRY_PATH, ensure_research_dirs


def _json(value: Any) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, default=str)


class ExperimentRegistry:
    def __init__(self, path: str | Path = REGISTRY_PATH):
        ensure_research_dirs()
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            create table if not exists experiments (
                experiment_id text primary key,
                run_id text not null,
                system_configuration_id text not null,
                dataset_id text not null,
                symbol text not null,
                horizon_bars integer not null,
                model_name text not null,
                window_json text not null,
                settings_json text not null,
                status text not null,
                started_at text,
                finished_at text,
                metrics_json text,
                regime_json text,
                error text
            );
            create table if not exists runs (
                run_id text primary key,
                manifest_json text not null,
                status text not null,
                started_at text,
                finished_at text
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def record_run(self, run_id: str, manifest: dict[str, Any], status: str = "running") -> None:
        self.connection.execute(
            "insert or replace into runs(run_id, manifest_json, status, started_at, finished_at) values(?, ?, ?, coalesce((select started_at from runs where run_id=?), datetime('now')), null)",
            (run_id, _json(manifest), status, run_id),
        )
        self.connection.commit()

    def finish_run(self, run_id: str, status: str) -> None:
        self.connection.execute("update runs set status=?, finished_at=datetime('now') where run_id=?", (status, run_id))
        self.connection.commit()

    def get_status(self, experiment_id: str) -> str | None:
        row = self.connection.execute("select status from experiments where experiment_id=?", (experiment_id,)).fetchone()
        return str(row["status"]) if row else None

    def start_experiment(self, experiment_id: str, payload: dict[str, Any]) -> bool:
        status = self.get_status(experiment_id)
        if status == "success":
            return False
        self.connection.execute(
            """
            insert or replace into experiments(
                experiment_id, run_id, system_configuration_id, dataset_id, symbol,
                horizon_bars, model_name, window_json, settings_json, status, started_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', datetime('now'))
            """,
            (
                experiment_id,
                payload["run_id"],
                payload["system_configuration_id"],
                payload["dataset_id"],
                payload["symbol"],
                payload["horizon_bars"],
                payload["model_name"],
                _json(payload["window"]),
                _json(payload["settings"]),
            ),
        )
        self.connection.commit()
        return True

    def finish_experiment(self, experiment_id: str, metrics: dict[str, Any], regime: dict[str, Any]) -> None:
        self.connection.execute(
            "update experiments set status='success', finished_at=datetime('now'), metrics_json=?, regime_json=?, error=null where experiment_id=?",
            (_json(metrics), _json(regime), experiment_id),
        )
        self.connection.commit()

    def fail_experiment(self, experiment_id: str, error: str) -> None:
        self.connection.execute(
            "update experiments set status='failed', finished_at=datetime('now'), error=? where experiment_id=?",
            (error, experiment_id),
        )
        self.connection.commit()

    def rows(self, run_id: str | None = None) -> list[sqlite3.Row]:
        if run_id:
            return list(self.connection.execute(
                """
                select e.*,
                       coalesce(x.status, e.status) as execution_status,
                       coalesce(x.run_id, e.run_id) as execution_run_id
                from experiments e
                left join executions x on e.experiment_id=x.experiment_id and x.run_id=?
                where x.run_id=? or e.run_id=?
                order by e.experiment_id
                """,
                (run_id, run_id, run_id),
            ))
        return list(self.connection.execute("select * from experiments order by started_at, experiment_id"))

    def summary(self, run_id: str | None = None) -> dict[str, Any]:
        rows = self.rows(run_id)
        return {
            "experiment_count": len(rows),
            "success_count": sum(1 for row in rows if row["status"] == "success"),
            "failed_count": sum(1 for row in rows if row["status"] == "failed"),
            "running_count": sum(1 for row in rows if row["status"] == "running"),
        }


# Phase 1A.2 active registry overlay with schema migration and normalized tables.
from datetime import datetime, timezone  # noqa: E402

from .config import SCHEMA_VERSION  # noqa: E402


class ExperimentRegistry:
    def __init__(self, path: str | Path = REGISTRY_PATH):
        ensure_research_dirs()
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.initialize()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            create table if not exists schema_version (
                version integer primary key,
                applied_at text not null
            );
            create table if not exists runs (
                run_id text primary key,
                manifest_json text not null,
                status text not null,
                started_at text,
                finished_at text
            );
            create table if not exists experiments (
                experiment_id text primary key,
                run_id text not null,
                system_configuration_id text not null,
                dataset_id text not null,
                symbol text not null,
                horizon_bars integer not null,
                model_name text not null,
                window_json text not null,
                settings_json text not null,
                status text not null,
                started_at text,
                finished_at text,
                metrics_json text,
                regime_json text,
                error text
            );
            create table if not exists datasets (
                dataset_id text primary key,
                dataset_hash text not null,
                symbol text not null,
                exchange text,
                interval text,
                source_type text,
                quality_status text,
                manifest_json text not null,
                registered_at text not null
            );
            create table if not exists dataset_quality (
                quality_report_id text primary key,
                dataset_id text not null,
                status text not null,
                issue_count integer not null,
                report_json text not null
            );
            create table if not exists experiment_specs (
                experiment_id text primary key,
                forecast_identity_id text not null,
                analysis_identity_id text not null,
                dataset_id text not null,
                dataset_hash text not null,
                symbol text not null,
                exchange text,
                cutoff text not null,
                context_start text not null,
                context_end text not null,
                future_start text not null,
                future_end text not null,
                lookback integer not null,
                horizon integer not null,
                stride integer not null,
                interval text not null,
                session_policy text not null,
                model_id text not null,
                tokenizer_id text,
                temperature real,
                top_k integer,
                top_p real,
                sample_count integer,
                seed integer,
                preprocessing_version text,
                metric_definition_version text,
                regime_definition_version text,
                benchmark_profile_version text,
                system_configuration_id text not null,
                purpose text,
                code_commit text,
                code_dirty_state integer,
                spec_json text not null
            );
            create table if not exists executions (
                execution_id text primary key,
                run_id text not null,
                experiment_id text not null,
                status text not null,
                started_at text,
                finished_at text,
                error_type text,
                human_message text,
                traceback_artifact text
            );
            create table if not exists metrics (
                experiment_id text primary key,
                model_name text not null,
                horizon_bars integer not null,
                symbol text not null,
                metric_json text not null,
                mae real,
                normalized_mae real,
                rmse real,
                mase real,
                directional_match integer,
                inference_seconds real
            );
            create table if not exists regimes (
                experiment_id text primary key,
                regime_json text not null,
                trend text,
                volatility text,
                open_close_zone text,
                momentum text,
                relative_volume text,
                cross_session integer,
                gap_state text
            );
            create table if not exists artifacts (
                artifact_id text primary key,
                experiment_id text not null,
                artifact_type text not null,
                relative_path text not null,
                hash text not null,
                rows integer,
                schema_version text,
                created_at text not null
            );
            create table if not exists run_logs (
                id integer primary key autoincrement,
                run_id text not null,
                experiment_id text,
                level text not null,
                event text not null,
                message text not null,
                created_at text not null
            );
            """
        )
        self.connection.execute("insert or ignore into schema_version(version, applied_at) values(?, datetime('now'))", (SCHEMA_VERSION,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_run(self, run_id: str, manifest: dict[str, Any], status: str = "running") -> None:
        self.connection.execute(
            "insert or replace into runs(run_id, manifest_json, status, started_at, finished_at) values(?, ?, ?, coalesce((select started_at from runs where run_id=?), datetime('now')), null)",
            (run_id, _json(manifest), status, run_id),
        )
        self.log(run_id, None, "INFO", "run_status", f"Run marked {status}.")
        self.connection.commit()

    def finish_run(self, run_id: str, status: str) -> None:
        self.connection.execute("update runs set status=?, finished_at=datetime('now') where run_id=?", (status, run_id))
        self.log(run_id, None, "INFO", "run_status", f"Run marked {status}.")
        self.connection.commit()

    def get_run_manifest(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("select manifest_json from runs where run_id=?", (run_id,)).fetchone()
        return json.loads(row["manifest_json"]) if row else None

    def register_dataset(self, manifest: Any, quality: Any | None = None) -> None:
        data = manifest.as_dict() if hasattr(manifest, "as_dict") else dict(manifest)
        self.connection.execute(
            "insert or replace into datasets(dataset_id,dataset_hash,symbol,exchange,interval,source_type,quality_status,manifest_json,registered_at) values(?,?,?,?,?,?,?,?,?)",
            (data["dataset_id"], data["dataset_hash_full"], data["symbol"], data["exchange"], data["interval"], data["source_type"], data["quality_status"], _json(data), data["registered_at"]),
        )
        if quality is not None:
            report = quality.as_dict() if hasattr(quality, "as_dict") else dict(quality)
            self.connection.execute(
                "insert or replace into dataset_quality(quality_report_id,dataset_id,status,issue_count,report_json) values(?,?,?,?,?)",
                (report["report_id"], data["dataset_id"], report["status"], report["issue_count"], _json(report)),
            )
        self.connection.commit()

    def record_spec(self, spec: Any) -> None:
        data = spec.as_dict() if hasattr(spec, "as_dict") else dict(spec)
        self.connection.execute(
            """
            insert or replace into experiment_specs(
                experiment_id, forecast_identity_id, analysis_identity_id, dataset_id, dataset_hash,
                symbol, exchange, cutoff, context_start, context_end, future_start, future_end,
                lookback, horizon, stride, interval, session_policy, model_id, tokenizer_id,
                temperature, top_k, top_p, sample_count, seed, preprocessing_version,
                metric_definition_version, regime_definition_version, benchmark_profile_version,
                system_configuration_id, purpose, code_commit, code_dirty_state, spec_json
            ) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data["scientific_experiment_id"], data["forecast_identity_id"], data["analysis_identity_id"],
                data["dataset_id"], data["dataset_hash"], data["symbol"], data["exchange"], data["cutoff"],
                data["context_start"], data["context_end"], data["future_start"], data["future_end"],
                data["lookback"], data["horizon"], data["stride"], data["interval"], data["session_policy"],
                data["model_id"], data["tokenizer_id"], data["temperature"], data["top_k"], data["top_p"],
                data["sample_count"], data["seed"], data["preprocessing_version"], data["metric_definition_version"],
                data["regime_definition_version"], data["benchmark_profile_version"], data["system_configuration_id"],
                data["purpose"], data["code_commit"], int(bool(data["code_dirty_state"])), _json(data),
            ),
        )
        self.connection.commit()

    def get_status(self, experiment_id: str) -> str | None:
        row = self.connection.execute("select status from experiments where experiment_id=?", (experiment_id,)).fetchone()
        return str(row["status"]) if row else None

    def start_experiment(self, experiment_id: str, payload: dict[str, Any], *, force: bool = False) -> bool:
        if not force and self.get_status(experiment_id) in {"success", "succeeded"}:
            execution_id = f"{payload['run_id']}:{experiment_id}:cached"
            self.connection.execute(
                "insert or replace into executions(execution_id,run_id,experiment_id,status,started_at,finished_at) values(?,?,?,?,datetime('now'),datetime('now'))",
                (execution_id, payload["run_id"], experiment_id, "skipped_cached"),
            )
            self.log(payload["run_id"], experiment_id, "INFO", "skipped_cached", "Existing successful scientific experiment reused.")
            self.connection.commit()
            return False
        execution_id = f"{payload['run_id']}:{experiment_id}"
        self.connection.execute(
            """
            insert or replace into experiments(
                experiment_id, run_id, system_configuration_id, dataset_id, symbol,
                horizon_bars, model_name, window_json, settings_json, status, started_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', datetime('now'))
            """,
            (
                experiment_id, payload["run_id"], payload["system_configuration_id"], payload["dataset_id"],
                payload["symbol"], payload["horizon_bars"], payload["model_name"], _json(payload["window"]), _json(payload["settings"]),
            ),
        )
        self.connection.execute(
            "insert or replace into executions(execution_id,run_id,experiment_id,status,started_at) values(?,?,?,?,datetime('now'))",
            (execution_id, payload["run_id"], experiment_id, "running"),
        )
        self.log(payload["run_id"], experiment_id, "INFO", "experiment_started", f"{payload['model_name']} horizon {payload['horizon_bars']} started.")
        self.connection.commit()
        return True

    def finish_experiment(self, experiment_id: str, metrics: dict[str, Any], regime: dict[str, Any], *, run_id: str | None = None, artifacts: list[dict[str, Any]] | None = None) -> None:
        self.connection.execute(
            "update experiments set status='succeeded', finished_at=datetime('now'), metrics_json=?, regime_json=?, error=null where experiment_id=?",
            (_json(metrics), _json(regime), experiment_id),
        )
        self.connection.execute(
            """
            insert or replace into metrics(experiment_id,model_name,horizon_bars,symbol,metric_json,mae,normalized_mae,rmse,mase,directional_match,inference_seconds)
            select experiment_id, model_name, horizon_bars, symbol, ?, ?, ?, ?, ?, ?, ? from experiments where experiment_id=?
            """,
            (_json(metrics), metrics.get("mae"), metrics.get("normalized_mae"), metrics.get("rmse"), metrics.get("mase"), int(bool(metrics.get("directional_match"))) if metrics.get("directional_match") is not None else None, metrics.get("inference_seconds"), experiment_id),
        )
        self.connection.execute(
            "insert or replace into regimes(experiment_id,regime_json,trend,volatility,open_close_zone,momentum,relative_volume,cross_session,gap_state) values(?,?,?,?,?,?,?,?,?)",
            (experiment_id, _json(regime), regime.get("trend"), regime.get("volatility"), regime.get("open_close_zone"), regime.get("momentum"), regime.get("relative_volume"), int(bool(regime.get("cross_session"))), regime.get("gap_state")),
        )
        for artifact in artifacts or []:
            self.record_artifact(artifact, commit=False)
        if run_id:
            self.connection.execute("update executions set status='succeeded', finished_at=datetime('now') where run_id=? and experiment_id=? and status='running'", (run_id, experiment_id))
            self.log(run_id, experiment_id, "INFO", "experiment_succeeded", "Experiment completed.")
        self.connection.commit()

    def fail_experiment(self, experiment_id: str, error: str, *, run_id: str | None = None, error_type: str = "Exception") -> None:
        message = str(error).splitlines()[0][:500]
        self.connection.execute("update experiments set status='failed', finished_at=datetime('now'), error=? where experiment_id=?", (message, experiment_id))
        if run_id:
            self.connection.execute(
                "update executions set status='failed', finished_at=datetime('now'), error_type=?, human_message=? where run_id=? and experiment_id=? and status='running'",
                (error_type, message, run_id, experiment_id),
            )
            self.log(run_id, experiment_id, "ERROR", "experiment_failed", message)
        self.connection.commit()

    def interrupt_experiment(self, experiment_id: str, run_id: str) -> None:
        self.connection.execute("update experiments set status='interrupted', finished_at=datetime('now') where experiment_id=? and status='running'", (experiment_id,))
        self.connection.execute("update executions set status='interrupted', finished_at=datetime('now') where run_id=? and experiment_id=? and status='running'", (run_id, experiment_id))
        self.log(run_id, experiment_id, "WARNING", "experiment_interrupted", "Benchmark interrupted safely.")
        self.connection.commit()

    def record_artifact(self, artifact: dict[str, Any], *, commit: bool = True) -> None:
        self.connection.execute(
            "insert or replace into artifacts(artifact_id,experiment_id,artifact_type,relative_path,hash,rows,schema_version,created_at) values(?,?,?,?,?,?,?,datetime('now'))",
            (artifact["artifact_id"], artifact["experiment_id"], artifact["artifact_type"], artifact["relative_path"], artifact["hash"], artifact.get("rows"), artifact.get("schema_version")),
        )
        if commit:
            self.connection.commit()

    def log(self, run_id: str, experiment_id: str | None, level: str, event: str, message: str) -> None:
        self.connection.execute(
            "insert into run_logs(run_id,experiment_id,level,event,message,created_at) values(?,?,?,?,?,datetime('now'))",
            (run_id, experiment_id, level, event, message[:1000]),
        )

    def rows(self, run_id: str | None = None) -> list[sqlite3.Row]:
        if run_id:
            return list(self.connection.execute("select * from experiments where run_id=? order by experiment_id", (run_id,)))
        return list(self.connection.execute("select * from experiments order by started_at, experiment_id"))

    def metric_records(self, run_id: str | None = None) -> list[dict[str, Any]]:
        query = """
            select e.run_id, e.experiment_id, e.model_name, e.horizon_bars, e.symbol, s.exchange, s.cutoff, s.session_policy,
                   m.metric_json, r.regime_json
            from experiments e
            left join metrics m on e.experiment_id=m.experiment_id
            left join regimes r on e.experiment_id=r.experiment_id
            left join experiment_specs s on e.experiment_id=s.experiment_id
        """
        params: tuple[Any, ...] = ()
        if run_id:
            query += " left join executions x on e.experiment_id=x.experiment_id and x.run_id=? where x.run_id=? or e.run_id=?"
            params = (run_id, run_id, run_id)
        records = []
        for row in self.connection.execute(query, params):
            if not row["metric_json"]:
                continue
            metrics = json.loads(row["metric_json"])
            regime = json.loads(row["regime_json"]) if row["regime_json"] else {}
            records.append({**dict(row), **metrics, "regime": regime})
        return records

    def artifacts(self, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "select a.* from artifacts a join experiments e on a.experiment_id=e.experiment_id"
        params: tuple[Any, ...] = ()
        if run_id:
            query += " where a.relative_path like ?"
            params = (f"runs/{run_id}/%",)
        query += " order by a.created_at desc limit ?"
        return [dict(row) for row in self.connection.execute(query, (*params, limit))]

    def summary(self, run_id: str | None = None) -> dict[str, Any]:
        if run_id:
            executions = list(self.connection.execute("select status from executions where run_id=?", (run_id,)))
            if executions:
                return {
                    "experiment_count": len(executions),
                    "success_count": sum(1 for row in executions if row["status"] in {"succeeded", "success", "skipped_cached"}),
                    "failed_count": sum(1 for row in executions if row["status"] == "failed"),
                    "running_count": sum(1 for row in executions if row["status"] == "running"),
                    "interrupted_count": sum(1 for row in executions if row["status"] == "interrupted"),
                    "skipped_cached_count": sum(1 for row in executions if row["status"] == "skipped_cached"),
                    "schema_version": SCHEMA_VERSION,
                }
        rows = self.rows(run_id)
        success_states = {"success", "succeeded"}
        return {
            "experiment_count": len(rows),
            "success_count": sum(1 for row in rows if row["status"] in success_states),
            "failed_count": sum(1 for row in rows if row["status"] == "failed"),
            "running_count": sum(1 for row in rows if row["status"] == "running"),
            "interrupted_count": sum(1 for row in rows if row["status"] == "interrupted"),
            "schema_version": SCHEMA_VERSION,
        }
