"""Score current P0 decisions against A's reviewed gold for one case."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from textbook2video.research.gold_alignment import evaluate_reviewed_gold  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--proposition-graph", required=True, type=Path)
    parser.add_argument("--visual-decisions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(evaluate_reviewed_gold(
        gold_path=args.gold,
        proposition_graph_path=args.proposition_graph,
        visual_decisions_path=args.visual_decisions,
        output_path=args.output,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
