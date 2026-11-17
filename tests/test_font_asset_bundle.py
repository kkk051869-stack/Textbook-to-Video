import hashlib
from pathlib import Path

from textbook2video.font_assets import (
    CANONICAL_FONT_SHA256,
    CJK_FONT_RELATIVE_PATH,
    PROJECT_FONT_RELATIVE_PATH,
    package_cjk_font,
)

REPO_ROOT = Path(__file__).parents[1]
PROJECT_FONT = REPO_ROOT / PROJECT_FONT_RELATIVE_PATH


def test_canonical_font_asset_is_present_and_packageable(tmp_path: Path) -> None:
    assert PROJECT_FONT.is_file()
    assert hashlib.sha256(PROJECT_FONT.read_bytes()).hexdigest() == CANONICAL_FONT_SHA256

    info = package_cjk_font(tmp_path / "candidate")

    packaged = tmp_path / "candidate" / CJK_FONT_RELATIVE_PATH
    assert packaged.is_file()
    assert info["font_asset_exists"] is True
    assert info["font_sha256_matches"] is True
    assert hashlib.sha256(packaged.read_bytes()).hexdigest() == CANONICAL_FONT_SHA256
