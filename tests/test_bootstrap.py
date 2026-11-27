import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bootstrap.py"
SPEC = importlib.util.spec_from_file_location("bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_dry_run_writes_nothing(self):
        result = bootstrap.run_bootstrap(ROOT, self.home, apply=False)
        self.assertEqual(result["seeded"]["codex_config"], "planned")
        self.assertEqual(result["seeded"]["t3_settings"], "planned")
        self.assertEqual(result["seeded"]["t3_keybindings"], "planned")
        self.assertEqual(result["seeded"]["antigravity_cli_settings"], "planned")
        self.assertEqual(result["seeded"]["agent_chrome_desktop"], "planned")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_clean_home_seeds_templates_with_expanded_home_and_no_overwrite(self):
        result = bootstrap.run_bootstrap(ROOT, self.home, apply=True)
        self.assertEqual(result["seeded"]["codex_config"], "seeded")
        self.assertEqual(result["seeded"]["t3_settings"], "seeded")
        self.assertEqual(result["seeded"]["t3_keybindings"], "seeded")
        self.assertEqual(result["seeded"]["antigravity_cli_settings"], "seeded")
        self.assertEqual(result["seeded"]["agent_chrome_desktop"], "seeded")

        codex_cfg = (self.home / ".codex/config.toml").read_text(encoding="utf-8")
        self.assertIn(f'CURL_HOME = "{self.home}/.config/codex-curl"', codex_cfg)
        self.assertIn(f'BASH_ENV = "{self.home}/.config/codex-shell/bash-env.sh"', codex_cfg)
        self.assertNotIn("{{HOME}}", codex_cfg)

        t3_settings = json.loads((self.home / ".t3/userdata/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(
            t3_settings["providerInstances"]["antigravity"]["config"]["binaryPath"],
            f"{self.home}/.local/bin/agy",
        )
        for src in t3_settings.get("usageLimitSources", {}).values():
            self.assertEqual(src.get("managementKey", ""), "")

        ag_cli_settings = json.loads((self.home / ".gemini/antigravity-cli/settings.json").read_text(encoding="utf-8"))
        self.assertEqual(ag_cli_settings["editor"], "code --wait")
        self.assertEqual(ag_cli_settings["runningLightSpeed"], "off")
        self.assertEqual(ag_cli_settings["colorScheme"], "terminal")
        self.assertTrue(ag_cli_settings["notifications"])
        self.assertTrue(ag_cli_settings["allowNonWorkspaceAccess"])
        self.assertNotIn("trustedWorkspaces", ag_cli_settings)

        desktop = (self.home / ".local/share/applications/agent-chrome.desktop").read_text(encoding="utf-8")
        self.assertIn(f"Exec={self.home}/.local/bin/agent-chrome %U", desktop)
        self.assertNotIn("{{HOME}}", desktop)

        # Existing files must never be overwritten on repeated runs.
        (self.home / ".codex/config.toml").write_text("custom = true\n", encoding="utf-8")
        second = bootstrap.run_bootstrap(ROOT, self.home, apply=True)
        self.assertEqual(second["seeded"]["codex_config"], "skipped")
        self.assertEqual(second["seeded"]["t3_settings"], "skipped")
        self.assertEqual(second["seeded"]["t3_keybindings"], "skipped")
        self.assertEqual(second["seeded"]["antigravity_cli_settings"], "skipped")
        self.assertEqual(second["seeded"]["agent_chrome_desktop"], "skipped")
        self.assertEqual((self.home / ".codex/config.toml").read_text(encoding="utf-8"), "custom = true\n")

    def test_dynamic_t3_antigravity_linking_and_backup(self):
        gemini_skills = self.home / ".gemini/config/skills"
        gemini_skills.mkdir(parents=True)
        instance = self.home / ".t3/userdata/providers/antigravity/deadbeef1234"
        (instance / "config").mkdir(parents=True)
        (instance / "config/config.json").write_text('{"old": true}\n', encoding="utf-8")

        with self.assertRaisesRegex(bootstrap.BootstrapError, "Occupied T3 Antigravity target"):
            bootstrap.link_t3_antigravity(ROOT, self.home, apply=True, backup_existing=False)

        summary = bootstrap.link_t3_antigravity(ROOT, self.home, apply=True, backup_existing=True)
        self.assertEqual(summary, {"linked": 5, "unchanged": 0, "instances": 1})
        self.assertEqual((instance / "GEMINI.md").resolve(), (ROOT / "antigravity/GEMINI.md").resolve())
        self.assertEqual((instance / "config/config.json").resolve(), (ROOT / "antigravity/config.json").resolve())
        self.assertEqual((instance / "config/hooks.json").resolve(), (ROOT / "antigravity/t3-hooks.json").resolve())
        self.assertEqual((instance / "config/mcp_config.json").resolve(), (ROOT / "antigravity/mcp_config.json").resolve())
        self.assertEqual((instance / "config/skills").resolve(), gemini_skills.resolve())

        # Second run is a no-op.
        repeat = bootstrap.link_t3_antigravity(ROOT, self.home, apply=True, backup_existing=True)
        self.assertEqual(repeat, {"linked": 0, "unchanged": 5, "instances": 1})

    def test_t3_antigravity_skips_helper_and_textgen_profiles(self):
        root = self.home / ".t3/userdata/providers/antigravity"
        regular = root / "deadbeef1234"
        helper = root / "deadbeef1234-helper"
        default_textgen = root / bootstrap.t3_antigravity_profile_hash("antigravity_antigravitytextgen")
        custom_textgen = root / bootstrap.t3_antigravity_profile_hash("antigravity_fast")
        for profile in (regular, helper, default_textgen, custom_textgen):
            (profile / "config").mkdir(parents=True)
        (default_textgen / "config/config.json").write_text("{}\n", encoding="utf-8")

        settings_path = self.home / ".t3/userdata/settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "providerInstances": {
                        "antigravity_fast": {
                            "driver": "antigravity",
                            "displayName": "Antigravity TextGen Fast",
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        summary = bootstrap.link_t3_antigravity(ROOT, self.home, apply=True, backup_existing=False)
        self.assertEqual(summary, {"linked": 4, "unchanged": 0, "instances": 1})
        self.assertTrue((regular / "config/hooks.json").is_symlink())
        for skipped in (helper, default_textgen, custom_textgen):
            self.assertFalse((skipped / "config/hooks.json").exists())
            self.assertFalse((skipped / "config/mcp_config.json").exists())
            self.assertFalse((skipped / "GEMINI.md").exists())

    def test_cli_dry_run_exits_zero_on_clean_home(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--home", str(self.home)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
