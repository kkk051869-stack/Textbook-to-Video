"""Deterministic packaging helpers for the project's canonical CJK web font."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any


CJK_FONT_FAMILY = "T2V-CJK"
CJK_FONT_STACK = f"'{CJK_FONT_FAMILY}', sans-serif"
CANONICAL_FONT_NAME = "Noto Sans CJK SC"
CANONICAL_FONT_FILENAME = "t2v-cjk.otf"
CJK_FONT_RELATIVE_PATH = Path("fonts") / CANONICAL_FONT_FILENAME
PROJECT_FONT_RELATIVE_PATH = Path("assets") / "fonts" / CANONICAL_FONT_FILENAME
CANONICAL_FONT_SHA256 = "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9"
CANONICAL_FONT_LICENSE = "SIL Open Font License 1.1"


class CJKFontError(RuntimeError):
    """Raised when the configured canonical font cannot be used safely."""


def cjk_font_face_css(relative_path: str | None = None) -> str:
    """Return the fixed @font-face declaration embedded in generated HTML."""

    relative_path = relative_path or CJK_FONT_RELATIVE_PATH.as_posix()
    css_path = relative_path.replace("\\", "/").lstrip("/")
    return (
        "@font-face {\n"
        f"    font-family: \"{CJK_FONT_FAMILY}\";\n"
        f"    src: url(\"./{css_path}\") format(\"opentype\");\n"
        "    font-weight: 400;\n"
        "    font-style: normal;\n"
        "    font-display: block;\n"
        "}\n"
    )


def _project_font_path() -> Path:
    return Path(__file__).resolve().parents[2] / PROJECT_FONT_RELATIVE_PATH


def _development_fallback_path() -> Path | None:
    configured = os.environ.get("T2V_DEVELOPMENT_FONT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    windows_dir = os.environ.get("WINDIR")
    if windows_dir:
        path = Path(windows_dir) / "Fonts" / "msyh.ttc"
        if path.is_file():
            return path.resolve()
    path = Path("C:/Windows/Fonts/msyh.ttc")
    return path.resolve() if path.is_file() else None


def _resolve_source(source: str | Path | None = None) -> tuple[Path | None, str]:
    """Resolve the canonical source using explicit, project, then dev-only order."""

    if source is not None:
        return Path(source).expanduser().resolve(), "configured_external"

    for name in ("T2V_CJK_FONT_PATH", "T2V_CJK_FONT_SOURCE", "T2V_FONT_SOURCE"):
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser().resolve(), "configured_external"

    project = _project_font_path()
    if project.is_file():
        return project.resolve(), "canonical_asset"

    if os.environ.get("T2V_ALLOW_DEVELOPMENT_FONT_FALLBACK") == "1":
        fallback = _development_fallback_path()
        if fallback is not None:
            return fallback, "development_fallback"
    return None, "unavailable"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font_identity(path: Path | None) -> dict[str, Any]:
    exists = bool(path and path.is_file())
    actual = sha256_file(path) if exists and path is not None else None
    return {
        "font_sha256": actual,
        "expected_font_sha256": CANONICAL_FONT_SHA256,
        "font_sha256_matches": actual == CANONICAL_FONT_SHA256 if actual else False,
        "font_asset_exists": exists,
    }


def packaged_cjk_font_info(artifact_root: str | Path) -> dict[str, Any]:
    """Describe the self-contained canonical font without changing the artifact."""

    root = Path(artifact_root).resolve()
    path = root / CJK_FONT_RELATIVE_PATH
    identity = _font_identity(path)
    return {
        "font_family": CJK_FONT_FAMILY,
        "canonical_font_name": CANONICAL_FONT_NAME,
        "font_asset_relative_path": CJK_FONT_RELATIVE_PATH.as_posix(),
        "font_asset_source": str(path) if path.is_file() else None,
        "font_source_path": str(path) if path.is_file() else None,
        "font_source_type": "candidate_artifact" if path.is_file() else None,
        "font_asset_source_kind": "candidate_artifact" if path.is_file() else None,
        "font_license": CANONICAL_FONT_LICENSE,
        **identity,
    }


def package_cjk_font(
    artifact_root: str | Path,
    source: str | Path | None = None,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Copy the canonical CJK font into an artifact and return provenance.

    A configured external source and the tracked project asset must have the
    same canonical SHA.  The Windows Microsoft YaHei file is only available
    through an explicit development opt-in and is never an implicit source.
    """

    root = Path(artifact_root).resolve()
    destination = root / CJK_FONT_RELATIVE_PATH
    source_path, source_type = _resolve_source(source)
    info: dict[str, Any] = {
        "font_family": CJK_FONT_FAMILY,
        "canonical_font_name": CANONICAL_FONT_NAME,
        "font_asset_relative_path": CJK_FONT_RELATIVE_PATH.as_posix(),
        "font_asset_source": str(source_path) if source_path else None,
        "font_source_path": str(source_path) if source_path else None,
        "font_source_type": source_type,
        "font_asset_source_kind": source_type,
        "font_license": CANONICAL_FONT_LICENSE,
        "font_sha256": None,
        "expected_font_sha256": CANONICAL_FONT_SHA256,
        "font_sha256_matches": False,
        "font_asset_exists": False,
    }
    if source_path is None or not source_path.is_file():
        message = "T2V canonical CJK font unavailable or hash mismatch."
        if strict:
            raise CJKFontError(message)
        info["error"] = message
        return info

    actual = sha256_file(source_path)
    info["font_sha256"] = actual
    info["font_sha256_matches"] = actual == CANONICAL_FONT_SHA256
    if actual != CANONICAL_FONT_SHA256:
        message = "T2V canonical CJK font unavailable or hash mismatch."
        if strict:
            raise CJKFontError(message)
        info["error"] = message
        return info

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != destination.resolve():
        shutil.copyfile(source_path, destination)
    info["font_asset_exists"] = True
    return info
