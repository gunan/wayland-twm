#!/usr/bin/env python3
"""Compare the complete M4 geometry cross-product under twm and wtwm."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import traceback
from typing import Any


def configure_imports(source_root: Path) -> None:
    sys.path.insert(0, str(source_root / "tests/reference"))
    sys.path.insert(0, str(source_root / "tests/integration"))


def normalize_reference(observation: dict[str, object]) -> dict[str, object]:
    client = observation["client"]
    frame = observation["frame"]
    title = observation["title"]
    assert isinstance(client, dict) and isinstance(frame, dict)
    return {
        "client_inner": client["inner"],
        "extents": observation["extents"],
        "frame_outer": frame["outer"],
        "title_outer": title["outer"] if isinstance(title, dict) else None,
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def materialize_configurations(
    directory: Path, configurations: list[dict[str, object]],
) -> dict[str, tuple[Path, dict[str, object]]]:
    directory.mkdir()
    result: dict[str, tuple[Path, dict[str, object]]] = {}
    for config in configurations:
        config_id = str(config["id"])
        path = directory / f"{config_id}.twmrc"
        path.write_text(str(config["text"]), encoding="utf-8")
        metadata = {key: value for key, value in config.items() if key != "text"}
        result[config_id] = (path, metadata)
    return result


def run_differential(args: argparse.Namespace) -> dict[str, object]:
    source_root = args.source_root.resolve()
    configure_imports(source_root)
    from geometry_cross_product import (  # pylint: disable=import-error
        generate_cases, generate_configurations, generated_hashes, load_manifest,
    )
    from run_reference_geometry_matrix import capture_case  # pylint: disable=import-error
    from run_xwayland_geometry_matrix import run_case  # pylint: disable=import-error

    manifest = load_manifest(source_root)
    matrix_path = source_root / str(manifest["base_matrix"]["path"])
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    clean_runs = int(matrix["capture"]["clean_runs"])
    stable_observations = int(matrix["capture"]["stable_observations_per_case"])
    cases = generate_cases(manifest)
    configurations = generate_configurations(manifest)
    run_records: list[list[dict[str, object]]] = []

    with tempfile.TemporaryDirectory(prefix="wtwm-m4-geometry-differential-") as raw:
        temporary = Path(raw)
        materialized = materialize_configurations(temporary / "configs", configurations)
        for run_index in range(clean_runs):
            records: list[dict[str, object]] = []
            for case_index, generated_case in enumerate(cases):
                case: dict[str, Any] = dict(generated_case)
                config_path, config = materialized[str(case["configuration_id"])]
                case["configuration"] = str(config_path)
                reference_observation = capture_case(
                    args.reference_twm.resolve(), args.reference_client.resolve(),
                    source_root, case, 210 + run_index * 100 + case_index,
                    matrix["screen"],
                )
                wtwm_observation = run_case(
                    args.compositor.resolve(), args.wtwm_client.resolve(), source_root,
                    case, config, run_index, case_index, stable_observations,
                )
                reference_normalized = normalize_reference(reference_observation)
                wtwm_normalized = wtwm_observation["normalized"]
                record = {
                    "axes": case["axes"],
                    "case_id": case["id"],
                    "configuration_id": case["configuration_id"],
                    "reference": reference_normalized,
                    "wtwm": wtwm_normalized,
                }
                records.append(record)
                if reference_normalized != wtwm_normalized:
                    raise RuntimeError(
                        f"exact geometry differs for {case['id']}: "
                        f"reference={reference_normalized!r} wtwm={wtwm_normalized!r}"
                    )
            run_records.append(records)

    if any(records != run_records[0] for records in run_records[1:]):
        raise RuntimeError("geometry differential differs across two clean runs")
    return {
        "case_count": len(cases),
        "clean_runs": clean_runs,
        "comparison": [
            "client_inner", "frame_outer", "title_outer", "extents"
        ],
        "generated": generated_hashes(manifest),
        "result": "exactly-equivalent",
        "schema_version": 1,
        "stable_observations_per_backend": stable_observations,
        "cases": run_records[0],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference-twm", type=Path, required=True)
    parser.add_argument("--compositor", type=Path, required=True)
    parser.add_argument("--reference-client", type=Path, required=True)
    parser.add_argument("--wtwm-client", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()

    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    report: dict[str, object] = {"result": "running", "schema_version": 1}
    write_report(args.output, report)
    try:
        report = run_differential(args)
    except Exception as error:  # Preserve evidence before failing the CI step.
        report = {
            "error": str(error),
            "result": "failed",
            "schema_version": 1,
        }
        write_report(args.output, report)
        (args.evidence_dir / "runner-error.log").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        raise
    write_report(args.output, report)
    (args.evidence_dir / "exact-comparison.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"M4 geometry differential exactly equivalent: {report['case_count']} cases, "
        f"{report['clean_runs']} clean runs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
