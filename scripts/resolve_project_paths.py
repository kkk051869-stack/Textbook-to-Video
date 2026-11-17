"""Read relocated historical paths without rewriting frozen experiment files.

Produces a derived JSON view or a script copy; never executes a historical script.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = ROOT / ".local/backups/root-consolidation-20261117/moves.json"


def relocate(value, moves):
    if isinstance(value, list):
        return [relocate(item, moves) for item in value]
    if isinstance(value, dict):
        return {relocate(key, moves): relocate(item, moves) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    current = value.replace("\\", "/")
    for move in moves:
        old = move["from"].replace("\\", "/").rstrip("/")
        new = move["to"].replace("\\", "/").rstrip("/")
        if current.lower() == old.lower() or current.lower().startswith(old.lower() + "/"):
            current = new + current[len(old) :]
    # Preserve strings that are not affected, including their slash convention.
    return current if current != value.replace("\\", "/") else value


def relocated_script(text, moves):
    lowered = text.lower()
    for move in moves:
        old = move["from"].replace("\\", "/")
        new = move["to"].replace("\\", "/")
        pairs = [
            (old, new),
            (old.replace("/", "\\"), new.replace("/", "\\")),
            (old.replace("/", "\\\\"), new.replace("/", "\\\\")),
        ]
        if Path(old).is_absolute() and Path(new).is_absolute():
            pairs.append((Path(old).as_uri(), Path(new).as_uri()))
        for source, target in pairs:
            if source.lower() not in lowered:
                continue
            text = re.sub(
                re.escape(source) + r'(?=[/\\\s\'"\)]|$)',
                lambda _: target,
                text,
                flags=re.IGNORECASE,
            )
            lowered = text.lower()
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--path")
    group.add_argument("--json", type=Path)
    group.add_argument("--script", type=Path)
    group.add_argument("--html", type=Path)
    parser.add_argument("--output", type=Path, help="New derived file; refuses overwrite")
    args = parser.parse_args()
    moves = json.loads(args.map.read_text(encoding="utf-8-sig"))
    if args.path is not None:
        resolved = relocate(args.path, moves)
        output = json.dumps(
            {"original": args.path, "resolved": resolved, "exists": Path(resolved).exists()},
            ensure_ascii=False,
            indent=2,
        )
    elif args.json:
        source = Path(relocate(str(args.json), moves))
        output = json.dumps(
            relocate(json.loads(source.read_text(encoding="utf-8-sig")), moves),
            ensure_ascii=False,
            indent=2,
        )
    elif args.script:
        if not args.output:
            parser.error("--script requires --output; the original is never executed or modified")
        source = Path(relocate(str(args.script), moves))
        original = source.read_bytes()
        output = (
            "# Derived relocation copy; original SHA256: "
            + hashlib.sha256(original).hexdigest()
            + "\n"
        )
        output += relocated_script(original.decode("utf-8-sig"), moves)
    else:
        if not args.output:
            parser.error("--html requires --output")
        source = Path(relocate(str(args.html.resolve()), moves))
        if args.output.resolve().parent != source.resolve().parent:
            parser.error("HTML copy must stay beside its original to preserve relative assets")
        original = source.read_bytes()
        output = (
            "<!-- Derived relocation copy; original SHA256: "
            + hashlib.sha256(original).hexdigest()
            + " -->\n"
        )
        output += relocated_script(original.decode("utf-8-sig"), moves)
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="") as stream:
            stream.write(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
