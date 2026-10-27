"""Shared paths configured in project_config.ini."""

from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "project_config.ini"

_config = ConfigParser()
if not _config.read(CONFIG_PATH):
    raise FileNotFoundError(f"Project configuration not found: {CONFIG_PATH}")

def configured_path(name: str) -> Path:
    value = _config.get("paths", name).strip()
    if not value:
        raise ValueError(f"Set paths.{name} in project_config.ini.")
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


TRACKING_WORKBOOK = configured_path("tracking_workbook")
RIG_CONSTANTS_CSV = configured_path("rig_constants_csv")
SESSIONS_DIR = configured_path("sessions_dir")