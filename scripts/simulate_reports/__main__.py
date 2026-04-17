"""CLI entrypoint: python -m scripts.simulate_reports <subcommand>"""
import sys

SUBCOMMANDS = {
    "prepare":  "scripts.simulate_reports.cmd.prepare",
    "run":      "scripts.simulate_reports.cmd.run",
    "run-one":  "scripts.simulate_reports.cmd.run_one",
    "rerun-after-fix": "scripts.simulate_reports.cmd.rerun",
    "show":     "scripts.simulate_reports.cmd.show",
    "diff":     "scripts.simulate_reports.cmd.diff",
    "verify":   "scripts.simulate_reports.cmd.verify",
    "issues":   "scripts.simulate_reports.cmd.verify",  # alias
    "index":    "scripts.simulate_reports.cmd.index",
    "reset":    "scripts.simulate_reports.cmd.reset",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python -m scripts.simulate_reports <subcommand> [args...]")
        print("Subcommands: " + ", ".join(SUBCOMMANDS))
        return 0
    cmd = sys.argv[1]
    if cmd not in SUBCOMMANDS:
        print(f"Unknown subcommand: {cmd}", file=sys.stderr)
        return 2
    import importlib
    module = importlib.import_module(SUBCOMMANDS[cmd])
    return module.run(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main() or 0)
