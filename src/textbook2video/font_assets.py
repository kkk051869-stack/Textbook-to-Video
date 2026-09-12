"""Deterministic packaging helpers for the project's CJK web font."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any


CJK_FONT_FAMILY = "T2V-CJK"
CJK_FONT_STACK = f"'{CJK_FONT_FAMILY}', sans-serif"
CJK_FONT_RELATIVE_PATH = Path("fonts") / "msyh.ttc"


def cjk_font_face_css(relative_path: str = "fonts/msyh.ttc") -> str:
    """Return the fixed @font-face declaration embedded in generated HTML."""

    css_path = relative_path.replace("\\", "/").lstrip("/")
    return (
        "@font-face {\n"
        f"    font-family: \"{CJK_FONT_FAMILY}\";\n"
        f"    src: url(\"./{css_path}\") format(\"truetype\");\n"
        "    font-weight: 100 900;\n"
        "    font-style: normal;\n"
        "    font-display: block;\n"
        "}\n"
    )


def _configured_source() -> Path | None:
    for name in ("T2V_CJK_FONT_SOURCE", "T2V_FONT_SOURCE"):
        value = os.environ.get(name)
        if value:
            path = Path(value).expanduser()
            if path.is_file():
                return path.resolve()

    windows_dir = os.environ.get("WINDIR")
    if windows_dir:
        path = Path(windows_dir) / "Fonts" / "msyh.ttc"
        if path.is_file():
            return path.resolve()

    path = Path("C:/Windows/Fonts/msyh.ttc")
    if path.is_file():
        return path.resolve()
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packaged_cjk_font_info(artifact_root: str | Path) -> dict[str, Any]:
    """Describe the self-contained font asset without changing the artifact."""

    root = Path(artifact_root).resolve()
    path = root / CJK_FONT_RELATIVE_PATH
    info: dict[str, Any] = {
        "font_family": CJK_FONT_FAMILY,
        "font_asset_relative_path": CJK_FONT_RELATIVE_PATH.as_posix(),
        "font_asset_source": None,
        "font_asset_source_kind": None,
        "font_sha256": None,
        "font_asset_exists": path.is_file(),
    }
    if path.is_file():
        info["font_sha256"] = sha256_file(path)
        info["font_asset_source"] = str(path)
        info["font_asset_source_kind"] = "candidate_artifact"
    return info


def package_cjk_font(artifact_root: str | Path, source: str | Path | None = None) -> dict[str, Any]:
    """Copy the existing CJK font into an artifact and return provenance.

    The font binary is deliberately not part of the source distribution.  A
    configured source or the local Windows system copy is packaged alongside
    each generated HTML artifact.  Missing source is reported as a diagnostic
    so legacy generation remains usable; Font Gate remains responsible for
    failing a candidate that has no self-contained font.
    """

    root = Path(artifact_root).resolve()
    destination = root / CJK_FONT_RELATIVE_PATH
    source_path = Path(source).expanduser().resolve() if source else _configured_source()
    info: dict[str, Any] = {
        "font_family": CJK_FONT_FAMILY,
        "font_asset_relative_path": CJK_FONT_RELATIVE_PATH.as_posix(),
        "font_asset_source": str(source_path) if source_path else None,
        "font_asset_source_kind": "configured" if source else (
            "configured_or_windows_system" if source_path else None
        ),
        "font_sha256": None,
        "font_asset_exists": False,
    }
    if source_path is None or not source_path.is_file():
        return info

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != destination.resolve():
        shutil.copyfile(source_path, destination)
    info["font_sha256"] = sha256_file(destination)
    info["font_asset_exists"] = True
    info["font_asset_source_kind"] = "configured" if source else "windows_system_font"
    return info
