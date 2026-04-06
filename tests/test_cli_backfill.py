import subprocess
import sys


def test_backfill_analysis_help():
    result = subprocess.run(
        [sys.executable, "-m", "qbu_crawler.cli", "backfill-analysis", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "backfill-analysis" in result.stdout.lower() or "re-process" in result.stdout.lower()
