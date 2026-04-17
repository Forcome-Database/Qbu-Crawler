"""Freezegun wrapper for simulating 'today' during business code calls."""
from contextlib import contextmanager
from datetime import datetime, date, time
from freezegun import freeze_time


@contextmanager
def frozen_today(d: date, at: time = time(9, 30)):
    """Freeze time to `d at`. Use around business report calls."""
    dt = datetime.combine(d, at)
    with freeze_time(dt):
        yield dt
