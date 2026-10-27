# Ephys Insertion Tracking and Metadata

This repository has three separate workflows:

- The transform converter and browser viewer in `code/` inspect insertion trajectories. They do not create full acquisition metadata.
- [Metadata generation notebook](./notebooks/metadata%20generation%20v4.ipynb) creates ephys session and rig JSON files.
- [Ephys transfer notebook](./notebooks/ephys_transfer.ipynb) submits a prepared session to the internal AIND data-transfer service.

## Configure Paths

Edit [project_config.ini](./project_config.ini) to set the tracking workbook, rig constants CSV, and ephys sessions directory. Relative paths are resolved from the repository root. The rig constants CSV is included in `code/metadata_support/`; the workbook and large session recordings remain on the shared drive by default.

## Generate and View Trajectories

From the repository root, install the project environment and regenerate the viewer data:

```powershell
uv sync
uv run python code/insertion_tracking.py
```

The converter reads the `Targets` sheet from the configured Excel workbook and writes `data/insertion_transforms.csv`. That generated file is ignored by Git and recreated by the command above. It also accepts a CSV or workbook for a one-off run:

```powershell
uv run python code/insertion_tracking.py "C:\path\to\tracking.xlsx" --output data/insertion_transforms.csv --head-angle 14
```

For sheets where `Arc AP` is positive anterior, add `--anterior-positive`. This
uses `-(Arc AP - head angle)` for the probe tilt. Without the flag, the converter
keeps the legacy `Arc AP + head angle` convention. The selected convention is
recorded in the output CSV.

Then serve the viewer from the repository root:

```powershell
uv run python -m http.server 8000 --bind 127.0.0.1
```

Open http://localhost:8000/code/insertion_viewer.html. Choose an insertion and transform step to inspect its pose. The converted CSV can also be selected with the file picker. Tracking data is processed locally; the viewer needs network access for Three.js and atlas meshes.

Rows are retained even when they cannot produce a trajectory. The `status` column indicates `ok`, `not_inserted`, or `invalid`; warnings include missing targets and depth discrepancies.

## Metadata Generation

Use the repository's `.venv` as the Jupyter kernel and run the cells in the [metadata generation notebook](./notebooks/metadata%20generation%20v4.ipynb) in order. Set `insertion_numbers` in the paths/setup cell to the setup numbers to generate. The notebook uses all three paths in `project_config.ini` and requires the corresponding OpenEphys session folders, including:

If the sheet's `Arc AP` values are positive anterior, set `anterior_positive_arc_ap = True` in that setup cell. It defaults to `False` to preserve the legacy `Arc AP + 14` correction.

- `ecephys/Record Node 101/settings.xml`
- `continuous/Neuropix-PXI-116.*/timestamps.npy`

The notebook currently writes the ephys session and rig JSON files. It does not submit them to the transfer service.

## Transfer a Session

The transfer workflow is separate from metadata generation. The [ephys transfer notebook](./notebooks/ephys_transfer.ipynb) expects the session to contain `acquisition_ecephys.json`, uses the sessions directory in `project_config.ini`, and requires access to the internal `aind-data-transfer-service` endpoint. Check the session folder selected in the notebook before submitting.

## Transform Notes

- In the converter's default probe orientation, manipulator +X maps to probe -Z, +Y to probe +X, and +Z to probe -Y.
- Positive `Arc ML` is negated as a local probe-X rotation; the convention is positive rotation toward the mouse's right.
- The default head-angle correction is 14 degrees and is added to `Arc AP`.
- This is a diagnostic visualization, not individual-animal anatomical registration. CCF placement is approximate, and target areas show intended targets, not verified hits.
- Offsets are applied in the rotated probe frame. Spin can therefore change the displayed tip position; inspect the intermediate steps as well as the final pose.

The historical tracking export had probe coordinates swapped for entries between December 4 and December 12. The archived local copies have been removed; verify those entries in the active workbook before relying on them.

## Project Contents and Tests

- `code/`: trajectory converter, browser viewer, config loader, helper modules, and rig constants.
- `notebooks/`: metadata-generation and transfer workflows.
- `data/`: created automatically for the generated viewer CSV when the converter runs.
- `project_config.ini`: shared path settings; the loader is in `code/project_config.py`.
- `tests/`: Python and JavaScript regression tests.
- `wheels/`: bundled biodata-schema dependency.

Run the tests with:

```powershell
uv run pytest
node --test tests/insertion_viewer.test.cjs
```

Node.js 18 or newer is needed for the JavaScript tests.
