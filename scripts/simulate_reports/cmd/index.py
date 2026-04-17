"""python -m scripts.simulate_reports index"""
from ..index_page import build_index


def run(argv):
    p = build_index()
    print(f"index.html → {p}")
    return 0
