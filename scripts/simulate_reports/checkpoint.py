"""Per-day snapshot of simulation.db for fast single-scenario replay."""
import shutil
from datetime import date, datetime
from pathlib import Path
from . import config


def checkpoint_name(d: date) -> str:
    return f"{d.isoformat()}.db"


def parse_checkpoint_name(fname: str) -> date:
    stem = fname.rsplit(".db", 1)[0]
    return datetime.strptime(stem, "%Y-%m-%d").date()


def save(d: date) -> Path:
    config.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    dst = config.CHECKPOINT_DIR / checkpoint_name(d)
    shutil.copy2(config.SIM_DB, dst)
    return dst


def restore_before(d: date) -> date | None:
    """Copy the latest checkpoint strictly before `d` into SIM_DB. Return its date."""
    if not config.CHECKPOINT_DIR.exists():
        return None
    candidates = sorted(
        (parse_checkpoint_name(p.name), p)
        for p in config.CHECKPOINT_DIR.glob("*.db")
    )
    valid = [(cd, cp) for cd, cp in candidates if cd < d]
    if not valid:
        return None
    latest_date, latest_path = valid[-1]
    shutil.copy2(latest_path, config.SIM_DB)
    return latest_date
