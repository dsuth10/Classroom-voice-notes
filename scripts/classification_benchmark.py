"""Repeatable classification regression and latency benchmark.

The default fixture backend is deterministic and makes no network requests. Use
``--backend ollama`` explicitly to time the configured local model through the
application's public ``OllamaClassifier.classify`` contract.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "tests" / "fixtures" / "classification_benchmark_cases.json"
DEFAULT_P95_LIMIT_MS = 15_000.0


class ClassificationBackend(Protocol):
    """Minimal contract used by the benchmark."""

    name: str
    timing_source: str

    def classify(self, case: Mapping[str, Any]) -> Mapping[str, Any]: ...


class FixtureBackend:
    """Return recorded outputs and deterministic synthetic timings."""

    name = "fixture"
    timing_source = "simulated"

    def classify(self, case: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(case["scripted_result"])


class OllamaBackend:
    """Lazy adapter around the production classifier, for opt-in local runs."""

    timing_source = "measured"

    def __init__(
        self,
        url: str,
        model: str,
        fallback_model: str | None,
        total_budget_seconds: float,
    ) -> None:
        # Direct ``python scripts/classification_benchmark.py`` execution puts
        # ``scripts`` rather than the repository root on ``sys.path``.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app.ollama_router.classifier import OllamaClassifier

        self.name = f"ollama:{model}"
        self._classifier = OllamaClassifier(
            url=url,
            model=model,
            fallback_model=fallback_model,
            total_budget_seconds=total_budget_seconds,
        )

    def classify(self, case: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._classifier.classify(
            str(case["transcript"]),
            str(case.get("recorded_at", "")),
            int(case.get("duration_seconds", 0)),
        )


@dataclass(frozen=True)
class CaseRun:
    case_id: str
    kind: str
    repetition: int
    latency_ms: float
    passed: bool
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkReport:
    backend: str
    timing_source: str
    case_count: int
    sample_count: int
    p50_ms: float
    p95_ms: float
    maximum_ms: float
    p95_limit_ms: float
    latency_passed: bool
    correctness_passed: bool
    runs: tuple[CaseRun, ...]

    @property
    def passed(self) -> bool:
        return self.latency_passed and self.correctness_passed

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


def load_cases(path: Path = DEFAULT_FIXTURES) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"Unsupported fixture schema in {path}")
    if payload.get("data_classification") != "synthetic_only_no_real_student_data":
        raise ValueError(f"Benchmark fixtures must be explicitly marked synthetic: {path}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"No classification cases found in {path}")
    return cases


def percentile_nearest_rank(samples: Sequence[float], percentile: float) -> float:
    """Return a deterministic nearest-rank percentile."""

    if not samples:
        raise ValueError("At least one latency sample is required")
    if not 0 < percentile <= 100:
        raise ValueError("Percentile must be greater than 0 and at most 100")
    ordered = sorted(float(sample) for sample in samples)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return ordered[rank - 1]


def get_path(value: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def validate_result(
    result: Mapping[str, Any], expected: Mapping[str, Any]
) -> tuple[str, ...]:
    mismatches: list[str] = []
    for path, expected_value in expected.items():
        actual = get_path(result, path)
        if actual is _MISSING:
            mismatches.append(f"{path}: missing")
        elif actual != expected_value:
            # Reports may be retained as timing evidence. Do not echo transcripts,
            # recipients, subjects, bodies, or any other classification content.
            mismatches.append(f"{path}: value mismatch")
    return tuple(mismatches)


def run_benchmark(
    cases: Sequence[Mapping[str, Any]],
    backend: ClassificationBackend,
    *,
    repetitions: int = 1,
    p95_limit_ms: float = DEFAULT_P95_LIMIT_MS,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkReport:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    if p95_limit_ms <= 0:
        raise ValueError("p95_limit_ms must be positive")

    selected = [
        case
        for case in cases
        if backend.timing_source == "simulated" or case.get("run_with_live_model", True)
    ]
    if not selected:
        raise ValueError("No cases apply to the selected backend")

    runs: list[CaseRun] = []
    for repetition in range(1, repetitions + 1):
        for case in selected:
            started = clock()
            try:
                result = backend.classify(case)
                mismatches = validate_result(result, case["expected"])
            except Exception as exc:  # benchmark records failures instead of aborting the suite
                mismatches = (f"backend raised {type(exc).__name__}",)
            measured_ms = (clock() - started) * 1_000.0
            latency_ms = (
                float(case["simulated_latency_ms"])
                if backend.timing_source == "simulated"
                else measured_ms
            )
            runs.append(
                CaseRun(
                    case_id=str(case["id"]),
                    kind=str(case["kind"]),
                    repetition=repetition,
                    latency_ms=round(latency_ms, 3),
                    passed=not mismatches,
                    mismatches=mismatches,
                )
            )

    latencies = [run.latency_ms for run in runs]
    p95_ms = percentile_nearest_rank(latencies, 95)
    return BenchmarkReport(
        backend=backend.name,
        timing_source=backend.timing_source,
        case_count=len(selected),
        sample_count=len(runs),
        p50_ms=percentile_nearest_rank(latencies, 50),
        p95_ms=p95_ms,
        maximum_ms=max(latencies),
        p95_limit_ms=p95_limit_ms,
        latency_passed=p95_ms <= p95_limit_ms,
        correctness_passed=all(run.passed for run in runs),
        runs=tuple(runs),
    )


def format_report(report: BenchmarkReport) -> str:
    lines = [
        f"Classification benchmark: {report.backend}",
        f"Timing source: {report.timing_source}",
        f"Cases/samples: {report.case_count}/{report.sample_count}",
        (
            f"Latency p50/p95/max: {report.p50_ms:.1f}/{report.p95_ms:.1f}/"
            f"{report.maximum_ms:.1f} ms (p95 limit {report.p95_limit_ms:.1f} ms)"
        ),
        f"Result: {'PASS' if report.passed else 'FAIL'}",
    ]
    for run in report.runs:
        if run.mismatches:
            lines.append(f"- {run.case_id} run {run.repetition}: {'; '.join(run.mismatches)}")
    if report.timing_source == "simulated":
        lines.append("Fixture timings are deterministic test data, not real Ollama performance.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic or live classification regression benchmarks."
    )
    parser.add_argument("--backend", choices=("fixture", "ollama"), default="fixture")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--max-p95-ms", type=float, default=DEFAULT_P95_LIMIT_MS)
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--model", default="qwen3.5:latest")
    parser.add_argument("--fallback-model", default="phi4-mini:3.8b")
    parser.add_argument("--total-budget-seconds", type=float, default=18.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend: ClassificationBackend
    if args.backend == "ollama":
        backend = OllamaBackend(
            args.ollama_url,
            args.model,
            args.fallback_model or None,
            args.total_budget_seconds,
        )
    else:
        backend = FixtureBackend()
    report = run_benchmark(
        load_cases(args.fixtures),
        backend,
        repetitions=args.repetitions,
        p95_limit_ms=args.max_p95_ms,
    )
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))
    return 0 if report.passed else 1


_MISSING = object()


if __name__ == "__main__":
    raise SystemExit(main())
