"""Regression checks for the notebook-only insertion audit workflow."""

import csv
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from biodata_schema.components.coordinates import Rotation, Translation
from insertion_tracking import (
    compute_steps,
    convert_file,
    convert_row,
    notebook_transforms,
    read_tracking,
)


@pytest.fixture
def row():
    """An insertion with analytically predictable at-rest recording pose."""
    return {
        "Setup No": "1", "Mouse": "123", "Target": "MD", "Date": "10/27/25",
        "Inserted?": "y", "Manipulator X": "1000", "Manipulator Y": "2000",
        "Final Z": "4000", "Surface Z": "3000", "Insertion Z": "1000",
        "Bregma X": "0", "Bregma Y": "0", "Bregma Z": "0",
        "Arc AP": "-14", "Arc ML": "0", "Spin": "0", "comments": 'a, "quote"\nand newline',
    }


def test_notebook_transforms_with_swapped_manipulator_yz(row):
    transforms, depth, offset = notebook_transforms(row, 14)
    assert depth == 1
    assert offset == [1, 2, 4]
    rotations = [t for t in transforms if isinstance(t, Rotation)]
    translations = [t for t in transforms if isinstance(t, Translation)]
    assert [t.angles for t in rotations] == [[90, 0, -90], [0, 0, 0], [0, 0, 0], [0, 0, 0]]
    assert [t.translation for t in translations] == [[1, -3, 2], [0, -1, 0]]
    assert [t.reference_coordinate_system for t in transforms] == [
        "global", "global", "local", "local", "local", "local",
    ]
    for transform in transforms:
        dumped = transform.model_dump(mode="json")
        assert (Rotation if isinstance(transform, Rotation) else Translation).model_validate(dumped) == transform


def test_default_orientation_and_surface_to_tip(row):
    transforms, _, _ = notebook_transforms(row, 14)
    steps = compute_steps(transforms)
    for actual, expected in zip(steps[1]["basis"], [[0, -1, 0], [0, 0, 1], [-1, 0, 0]]):
        assert actual == pytest.approx(expected)
    assert steps[5]["position"] == pytest.approx([-2, -1, -3])
    assert steps[6]["position"] == pytest.approx([-2, -1, -4])


@pytest.mark.parametrize("axis", ["X", "Y", "Z"])
@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_manipulator_axes_map_to_probe_positive_x_positive_z_negative_y(row, axis, offset):
    row.update({
        "Manipulator X": "5000", "Manipulator Y": "5000", "Final Z": "5000",
        "Bregma X": "5000", "Bregma Y": "5000", "Bregma Z": "5000",
        "Surface Z": "3000",
    })
    source_key = {"X": "Manipulator X", "Y": "Manipulator Y", "Z": "Final Z"}[axis]
    row[source_key] = str(5000 + offset * 1000)
    result = convert_row(row, 14)
    assert result["status"] == "ok"
    expected_manipulator = [0, 0, 0]
    expected_manipulator["XYZ".index(axis)] = offset
    assert result["manipulator_offset_mm"] == expected_manipulator
    surface = result["transforms"][4]["translation"]
    depth = result["transforms"][5]["translation"]
    expected_probe = [expected_manipulator[0], -expected_manipulator[2], expected_manipulator[1]]
    assert [surface[i] + depth[i] for i in range(3)] == expected_probe
    assert surface[1] == pytest.approx(-(float(row["Surface Z"]) - float(row["Bregma Z"])) / 1000)
    assert depth == [0, -result["depth_mm"], 0]
    assert result["source"][source_key] == row[source_key]


@pytest.mark.parametrize("arc_ap,head_angle,expected_tilt", [(0, 14, 14), (-10, 14, 4), (-14, 14, 0), (30, 20, 50)])
def test_head_angle_is_added(row, arc_ap, head_angle, expected_tilt):
    row["Arc AP"] = str(arc_ap)
    transforms, _, _ = notebook_transforms(row, head_angle)
    rotation = transforms[1]
    assert isinstance(rotation, Rotation)
    assert rotation.angles == [expected_tilt, 0, 0]
    result = convert_row(row, head_angle)
    assert result["head_angle_deg"] == head_angle
    assert result["transforms"][1]["angles"] == [expected_tilt, 0, 0]
    axis = result["steps"][2]["basis"][1]
    angle = math.radians(expected_tilt)
    assert axis == pytest.approx([0, -math.sin(angle), math.cos(angle)])
    assert "Arc AP + head angle" in result["steps"][2]["label"]


def test_head_correction_and_nonzero_local_angles(row):
    row.update({"Arc AP": "0", "Arc ML": "30", "Spin": "90"})
    transforms, _, _ = notebook_transforms(row, 14)
    steps = compute_steps(transforms)
    # Global X tilt, then local X module rotation. Spin about local Y must
    # preserve the insertion direction while rotating the transverse offset.
    a, b = math.radians(14), math.radians(30)
    expected_axis = [-math.sin(b), -math.sin(a) * math.cos(b), math.cos(a) * math.cos(b)]
    assert steps[3]["basis"][1] == pytest.approx(expected_axis)
    assert steps[4]["basis"][1] == pytest.approx(expected_axis)
    displacement = [steps[6]["position"][i] - steps[5]["position"][i] for i in range(3)]
    assert displacement == pytest.approx([-v for v in expected_axis])
    for step in steps:
        basis = step["basis"]
        for i in range(3):
            for j in range(3):
                assert sum(x * y for x, y in zip(basis[i], basis[j])) == pytest.approx(float(i == j), abs=1e-12)


def test_notebook_spin_also_moves_tip_and_surface_depth_cancels(row):
    transforms, _, _ = notebook_transforms(row, 14)
    original = compute_steps(transforms)[-1]["position"]
    changed_surface = dict(row, **{"Surface Z": "2000", "Insertion Z": "2000"})
    transforms, _, _ = notebook_transforms(changed_surface, 14)
    assert compute_steps(transforms)[-1]["position"] == pytest.approx(original)
    transforms, _, _ = notebook_transforms(dict(row, Spin="90"), 14)
    assert compute_steps(transforms)[-1]["position"] != pytest.approx(original)


def test_surface_and_depth_are_separate_translations(row):
    original = convert_row(row, 14)
    changed_surface = convert_row(dict(row, **{"Surface Z": "2000", "Insertion Z": "2000"}), 14)
    assert original["transforms"][4]["translation"] == [1, -3, 2]
    assert changed_surface["transforms"][4]["translation"] == [1, -2, 2]
    assert original["transforms"][5]["translation"] == [0, -1, 0]
    assert changed_surface["transforms"][5]["translation"] == [0, -2, 0]
    assert changed_surface["steps"][5]["position"] != pytest.approx(original["steps"][5]["position"])
    assert changed_surface["steps"][6]["position"] == pytest.approx(original["steps"][6]["position"])
    changed_final = convert_row(dict(row, **{"Final Z": "5000", "Insertion Z": "2000"}), 14)
    assert changed_final["transforms"][4] == original["transforms"][4]
    assert changed_final["transforms"][5]["translation"] == [0, -2, 0]


@pytest.mark.parametrize("value", ["", "nan", "inf", "not a number"])
def test_invalid_numeric_inputs_are_reported(row, value):
    row["Final Z"] = value
    result = convert_row(row, 14)
    assert result["status"] == "invalid"
    assert "Final Z" in result["error"]
    assert result["transforms"] == result["steps"] == []


def test_not_inserted_and_unknown_targets(row):
    result = convert_row(dict(row, **{"Inserted?": "n"}), 14)
    assert result["status"] == "not_inserted"
    assert not result["steps"]
    result = convert_row(dict(row, Target="NOT_AN_AREA"), 14)
    assert result["status"] == "ok"
    assert not result["target_id"]
    assert "Unknown CCFv3 target" in result["warnings"]


def test_depth_discrepancy_and_negative_depth(row):
    result = convert_row(dict(row, **{"Insertion Z": "1077"}), 14)
    assert result["depth_difference_mm"] == pytest.approx(.077)
    assert "differs" in result["warnings"]
    result = convert_row(dict(row, **{"Surface Z": "5000"}), 14)
    assert "Negative recording depth" in result["warnings"]


def test_csv_round_trip_padding_bom_and_duplicate_headers(row, tmp_path):
    source, output = tmp_path / "tracking.csv", tmp_path / "output.csv"
    with source.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([*row, "Manip controller SN", "Manip controller SN", "", ""])
        writer.writerow([*row.values(), "111", "222", "", ""])
        writer.writerow([""] * (len(row) + 4))
    results = convert_file(source, output)
    assert len(results) == 1
    with output.open(newline="") as stream:
        parsed = next(csv.DictReader(stream))
    original = json.loads(parsed["source"])
    assert original["comments"] == row["comments"]
    assert original["Manip controller SN"] == "111"
    assert original["Manip controller SN [2]"] == "222"
    assert json.loads(parsed["transforms"]) == results[0]["transforms"]
    assert json.loads(parsed["steps"]) == results[0]["steps"]
    assert parsed["target_id"] == "362"


def test_workbook_reads_targets_sheet(row, tmp_path):
    source, output = tmp_path / "tracking.xlsx", tmp_path / "output.csv"
    pd.DataFrame([row]).to_excel(source, sheet_name="Targets", index=False)

    results = convert_file(source, output)

    assert len(results) == 1
    assert results[0]["setup_no"] == "1"
    assert results[0]["status"] == "ok"
    assert results[0]["source"]["comments"] == row["comments"]


def test_file_errors_are_explicit(tmp_path):
    source = tmp_path / "tracking.csv"
    source.write_text("")
    with pytest.raises(ValueError, match="empty"):
        read_tracking(source)
    source.write_text("Wrong header\n1\n")
    with pytest.raises(ValueError, match="Setup No"):
        read_tracking(source)
    source.write_text("Setup No\n\n")
    with pytest.raises(ValueError, match="no rows"):
        read_tracking(source)
    source.write_text("Setup No\n1\n1\n")
    with pytest.raises(ValueError, match="duplicate"):
        read_tracking(source)
    with pytest.raises(ValueError, match="overwrite"):
        convert_file(source, source)
    with pytest.raises(ValueError, match="finite"):
        convert_file(source, tmp_path / "out.csv", float("nan"))

