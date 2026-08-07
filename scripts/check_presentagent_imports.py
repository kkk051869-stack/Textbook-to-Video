from __future__ import annotations

import importlib
import traceback


MODULES = [
    "fastapi",
    "pdf2image",
    "pptx",
    "cv2",
    "pandas",
    "pptagent.document",
    "pptagent.model_utils",
    "pptagent.multimodal",
    "presentagent.backend",
]


def main() -> None:
    failures = 0
    for module in MODULES:
        try:
            importlib.import_module(module)
            print(f"OK {module}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {module}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
    print(f"failures {failures}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
