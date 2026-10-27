"""Extract notebook insertion transforms, without generating acquisition metadata.

Run with the project's Python environment:
    python code/insertion_tracking.py
    python -m http.server 8000
Then open http://localhost:8000/code/insertion_viewer.html.

By default, reads the Targets sheet from the workbook path in project_config.ini
and writes data/insertion_transforms.csv.

The CSV contains JSON-encoded biodata-schema coordinate systems and transforms,
plus computed poses in BREGMA_RAS millimeters for the viewer. Manipulator +X/+Y/+Z
maps to probe +X/+Z/-Y; the other notebook math, including its potentially problematic
local-frame offset translation, is preserved. This is not an anatomically
registered solution.
"""

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from biodata_models.brain_atlas import CCFv3
from biodata_models.units import SizeUnit

from biodata_schema.components.coordinates import (
    Axis,
    AxisName,
    CoordinateSystem,
    Direction,
    Handedness,
    Origin,
    ReferenceCoordinateSystem,
    Rotation,
    Translation,
)
from project_config import TRACKING_WORKBOOK

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "setup_no", "mouse", "date", "target", "target_name", "target_id",
    "inserted", "recorded", "on_target", "status", "error", "warnings",
    "head_angle_deg", "depth_mm", "depth_difference_mm", "manipulator_offset_mm",
    "global_coordinate_system", "probe_coordinate_system", "transforms", "steps", "source",
]
STEP_LABELS = [
    "At rest",
    "1. Default probe orientation (global XYZ)",
    "2. Arc AP + head angle (global X)",
    "3. Arc ML (local X)",
    "4. Spin (local Y)",
    "5. Move to surface (local XYZ, using Surface Z)",
    "6. Recording depth (local -Y)",
]
Vector = list[float]
Transform = Rotation | Translation


def coordinate_systems() -> tuple[CoordinateSystem, CoordinateSystem]:
    """Both systems have the RAS axes declared in the notebook."""
    axes = [
        Axis(name=AxisName.ML, direction=Direction.LR),
        Axis(name=AxisName.AP, direction=Direction.PA),
        Axis(name=AxisName.SI, direction=Direction.IS),
    ]
    global_cs = CoordinateSystem(
        name="BREGMA_RAS", origin=Origin.BREGMA, axis_unit=SizeUnit.MM,
        handedness=Handedness.RIGHT, axes=axes,
    )
    probe_cs = CoordinateSystem(
        name="PROBE_RUFD", origin=Origin.TIP, axis_unit=SizeUnit.MM,
        handedness=Handedness.RIGHT,
        axes=[
            Axis(name=AxisName.X, direction=Direction.LR),
            Axis(name=AxisName.Y, direction=Direction.PA),
            Axis(name=AxisName.Z, direction=Direction.IS),
        ],
    )
    return global_cs, probe_cs


def number(row: dict[str, str], key: str) -> float:
    """Reject absent/nonfinite inputs instead of inventing positions."""
    value = row.get(key, "").strip()
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{key}: expected a finite number, got {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"{key}: expected a finite number, got {value!r}")
    return result


def notebook_transforms(
    row: dict[str, str], head_angle: float,
) -> tuple[list[Transform], float, Vector]:
    """Notebook cell 3 transforms, with manipulator +X/+Y/+Z mapped to probe +X/+Z/-Y."""
    offset = [
        (number(row, actual) - number(row, bregma)) / 1000
        for actual, bregma in [
            ("Manipulator X", "Bregma X"), ("Manipulator Y", "Bregma Y"), ("Surface Z", "Bregma Z"),
        ]
    ]
    depth = (number(row, "Final Z") - number(row, "Surface Z")) / 1000
    local = ReferenceCoordinateSystem.LOCAL
    transforms: list[Transform] = [
        Rotation(angles=[90, 0, -90]),
        Rotation(angles=[number(row, "Arc AP") + head_angle, 0, 0]),
        Rotation(angles=[-number(row, "Arc ML"), 0, 0], reference_coordinate_system=local),
        Rotation(angles=[0, number(row, "Spin"), 0], reference_coordinate_system=local),
        Translation(translation=[offset[1], -offset[2], -offset[0]], reference_coordinate_system=local),
        Translation(translation=[0, -depth, 0], reference_coordinate_system=local),
    ]
    return transforms, depth, offset


def rotate(vector: Vector, axis: Vector, degrees: float) -> Vector:
    """Right-hand Rodrigues rotation around a unit axis."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    dot = sum(a * b for a, b in zip(axis, vector))
    cross = [
        axis[1] * vector[2] - axis[2] * vector[1],
        axis[2] * vector[0] - axis[0] * vector[2],
        axis[0] * vector[1] - axis[1] * vector[0],
    ]
    return [vector[i] * c + cross[i] * s + axis[i] * dot * (1 - c) for i in range(3)]


def compute_steps(transforms: list[Transform]) -> list[dict]:
    """Evaluate schema transforms in RAS; basis columns are the moving probe axes."""
    global_basis = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    basis = [axis[:] for axis in global_basis]
    position = [0.0, 0.0, 0.0]
    steps = [{"label": STEP_LABELS[0], "position": position[:], "basis": [axis[:] for axis in basis]}]
    for index, transform in enumerate(transforms, 1):
        reference = basis if transform.reference_coordinate_system == ReferenceCoordinateSystem.LOCAL else global_basis
        if isinstance(transform, Translation):
            position = [
                position[i] + sum(transform.translation[j] * reference[j][i] for j in range(3))
                for i in range(3)
            ]
        else:
            # Snapshot local axes for an extrinsic Euler rotation; do not mutate
            # the reference axes while applying the individual angles.
            rotation_axes = [axis[:] for axis in reference]
            for axis_name, angle in zip(transform.axis_order, transform.angles):
                axis = rotation_axes["xyz".index(axis_name)]
                basis = [rotate(vector, axis, angle) for vector in basis]
                if transform.pivot == ReferenceCoordinateSystem.GLOBAL:
                    position = rotate(position, axis, angle)
        steps.append({
            "label": STEP_LABELS[index], "position": position[:], "basis": [axis[:] for axis in basis],
        })
    return steps


def target_details(target: str) -> tuple[str, str, str]:
    """Resolve exact notebook acronyms to CCF structures."""
    if not target:
        return "", "", "Missing target; no target region can be displayed."
    try:
        region = CCFv3.by_acronym(target)
    except ValueError:
        return "", "", f"Unknown CCFv3 target {target!r}; no target region can be displayed."
    return region.name, region.id, ""


def convert_row(row: dict[str, str], head_angle: float) -> dict:
    """Keep unusable and not-inserted rows visible, with no fabricated transforms."""
    global_cs, probe_cs = coordinate_systems()
    target_name, target_id, target_warning = target_details(row.get("Target", "").strip())
    warnings = [target_warning] if target_warning else []
    result = {
        "setup_no": row["Setup No"].strip(), "mouse": row.get("Mouse", ""),
        "date": row.get("Date", ""), "target": row.get("Target", ""),
        "target_name": target_name, "target_id": target_id,
        "inserted": row.get("Inserted?", ""), "recorded": row.get("Recorded?", ""),
        "on_target": row.get("On target?", ""), "status": "", "error": "", "warnings": "",
        "head_angle_deg": head_angle, "depth_mm": "", "depth_difference_mm": "",
        "manipulator_offset_mm": [], "global_coordinate_system": global_cs.model_dump(mode="json"),
        "probe_coordinate_system": probe_cs.model_dump(mode="json"), "transforms": [], "steps": [],
        "source": row,
    }
    if row.get("Inserted?", "").strip().lower() not in {"y", "yes"}:
        result["status"] = "not_inserted"
        result["warnings"] = "; ".join(warnings + ["Not confirmed inserted; no trajectory generated."])
        return result
    try:
        transforms, depth, offset = notebook_transforms(row, head_angle)
    except ValueError as exc:
        result["status"], result["error"] = "invalid", str(exc)
    else:
        result.update(
            status="ok", depth_mm=depth, manipulator_offset_mm=offset,
            transforms=[transform.model_dump(mode="json") for transform in transforms],
            steps=compute_steps(transforms),
        )
        if depth < 0:
            warnings.append("Negative recording depth (Final Z < Surface Z).")
        if row.get("Insertion Z", "").strip():
            try:
                difference = number(row, "Insertion Z") / 1000 - depth
            except ValueError as exc:
                warnings.append(str(exc))
            else:
                result["depth_difference_mm"] = difference
                if abs(difference) > 0.001:
                    warnings.append(f"Insertion Z differs from Final Z - Surface Z by {difference:.6g} mm.")
    result["warnings"] = "; ".join(warnings)
    return result


def read_tracking(path: Path) -> list[dict[str, str]]:
    """Ignore spreadsheet padding; retain duplicate nonempty header values."""
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        try:
            frame = pd.read_excel(path, sheet_name="Targets", dtype=str, keep_default_na=False)
        except ValueError as exc:
            raise ValueError(f"Input workbook must contain a 'Targets' sheet: {path}") from exc
        rows = []
        seen = set()
        for line, values in enumerate(frame.to_dict(orient="records"), 2):
            row = {
                str(key).strip(): "" if pd.isna(value) else str(value).strip()
                for key, value in values.items()
                if str(key).strip() and not str(key).strip().startswith("Unnamed:")
            }
            if not row.get("Setup No", ""):
                continue
            if row["Setup No"] in seen:
                raise ValueError(f"Line {line}: duplicate Setup No {row['Setup No']!r}.")
            seen.add(row["Setup No"])
            rows.append(row)
        if not rows:
            raise ValueError("Input workbook contains no rows with Setup No in the 'Targets' sheet.")
        return rows

    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ValueError("Input CSV is empty.") from exc
        if "Setup No" not in headers:
            raise ValueError("Input CSV must contain a 'Setup No' column.")
        counts: Counter = Counter()
        keys = []
        for header in headers:
            header = header.strip()
            counts[header] += 1
            keys.append(header if counts[header] == 1 else f"{header} [{counts[header]}]")
        rows = []
        seen = set()
        for line, values in enumerate(reader, 2):
            row = {key: value.strip() for key, value in zip(keys, values) if key and not key.startswith(" [")}
            if not row.get("Setup No", "").strip():
                continue
            if row["Setup No"] in seen:
                raise ValueError(f"Line {line}: duplicate Setup No {row['Setup No']!r}.")
            seen.add(row["Setup No"])
            rows.append(row)
    if not rows:
        raise ValueError("Input CSV contains no rows with Setup No.")
    return rows


def convert_file(source: Path, destination: Path, head_angle: float = 14.0) -> list[dict]:
    """Write one CSV row per setup, with schema-validated JSON in complex columns."""
    if not math.isfinite(head_angle):
        raise ValueError("Head angle must be finite.")
    if source.resolve() == destination.resolve():
        raise ValueError("Output must not overwrite the insertion tracking input.")
    rows = [convert_row(row, head_angle) for row in read_tracking(source)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, allow_nan=False, separators=(",", ":")) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            })
    return rows


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, nargs="?", default=TRACKING_WORKBOOK)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "insertion_transforms.csv")
    parser.add_argument(
        "--head-angle", type=float, default=14.0,
        help="Head-angle correction in degrees, added to Arc AP (default: 14).",
    )
    args = parser.parse_args()
    try:
        rows = convert_file(args.input, args.output, args.head_angle)
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"Conversion failed: {exc}\n")
    print(f"Wrote {len(rows)} setups to {args.output}: {dict(Counter(row['status'] for row in rows))}")
    for row in rows:
        if row["error"] or row["warnings"]:
            print(f"Setup {row['setup_no']}: {row['error'] or row['warnings']}", file=sys.stderr)
    print("View: python -m http.server 8000 --bind 127.0.0.1")
    print("Open http://localhost:8000/code/insertion_viewer.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
