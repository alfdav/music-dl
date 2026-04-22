import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = PROJECT_ROOT / "tidal_dl" / "gui" / "static" / "app.js"


def test_upgrade_quality_context_menu_has_download_icon_template():
    source = APP_JS.read_text()

    assert "icon: 'download'" in source
    match = re.search(r"const _ctxIcons = \{(.*?)\n\};", source, re.S)
    assert match is not None
    ctx_icons_block = match.group(1)
    assert "download: '<svg" in ctx_icons_block
