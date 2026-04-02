from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class StaticAssetTests(unittest.TestCase):
    def _assert_asset_has_valid_module_syntax(self, filename: str) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")

        asset_path = (
            WORKSPACE_ROOT
            / "apps"
            / "api"
            / "src"
            / "quant_platform_api"
            / "static"
            / filename
        )
        completed = subprocess.run(
            [node, "--check", str(asset_path)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            0,
            completed.returncode,
            msg=completed.stderr or completed.stdout or f"{filename} syntax check failed",
        )

    def test_rules_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("rules.js")

    def test_admin_js_has_valid_module_syntax(self) -> None:
        self._assert_asset_has_valid_module_syntax("admin.js")


if __name__ == "__main__":
    unittest.main()
