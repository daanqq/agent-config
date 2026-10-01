import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install.py"
SPEC = importlib.util.spec_from_file_location("installer", SCRIPT)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        self.home = self.base / "home"
        self.repo.mkdir()
        self.home.mkdir()
        self.manifest = self.repo / "links.json"
        self.source = self.repo / "pi/agent/settings.json"
        self.source.parent.mkdir(parents=True)
        self.source.write_text('{"theme": "dark"}')
        self.target = self.home / ".pi/agent/settings.json"
        self.mappings = [{"source": "pi/agent/settings.json", "target": ".pi/agent/settings.json"}]
        self.write_manifest()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def write_manifest(self):
        self.manifest.write_text(json.dumps({"version": 1, "links": self.mappings}))

    def install(self, **kwargs):
        return installer.install(self.repo, self.home, self.manifest, **kwargs)

    def occupy(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("original")

    def test_dry_run_writes_nothing(self):
        self.assertIsNone(self.install())
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(self.source.read_text(), '{"theme": "dark"}')

    def test_occupied_path_is_unchanged_without_backup(self):
        self.occupy()
        original = installer.identity(self.target)
        with self.assertRaises(installer.InstallError):
            self.install(apply=True)
        self.assertEqual(installer.identity(self.target), original)
        self.assertEqual(self.target.read_text(), "original")
        self.assertFalse((self.home / ".local").exists())

    def test_backup_file_directory_and_restore(self):
        self.occupy()
        skill = self.repo / "common/skills/example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("new skill")
        target_skill = self.home / ".claude/skills/example"
        target_skill.mkdir(parents=True)
        (target_skill / "untracked.txt").write_text("keep me")
        self.mappings.append({"source": "common/skills/example", "target": ".claude/skills/example"})
        self.write_manifest()
        original = installer.identity(self.target)
        run = self.install(apply=True, backup_existing=True)
        self.assertEqual(stat.S_IMODE(run.stat().st_mode), 0o700)
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(target_skill.is_symlink())
        self.assertEqual((run / "0").read_text(), "original")
        self.assertEqual((run / "1/untracked.txt").read_text(), "keep me")
        journal = json.loads((run / "journal.json").read_text())
        self.assertTrue(all(entry["progress"] == "installed" for entry in journal["links"]))
        installer.restore(self.home, run)
        self.assertTrue(self.target.is_symlink())
        installer.restore(self.home, run, apply=True)
        self.assertEqual(installer.identity(self.target), original)
        self.assertEqual(self.target.read_text(), "original")
        self.assertFalse(target_skill.is_symlink())
        self.assertEqual((target_skill / "untracked.txt").read_text(), "keep me")
        installer.restore(self.home, run, apply=True)

    def test_repeated_install_and_restore_new_link(self):
        run = self.install(apply=True)
        link_id = installer.identity(self.target)
        self.assertIsNone(self.install(apply=True))
        self.assertEqual(installer.identity(self.target), link_id)
        self.assertEqual(len(list(run.parent.iterdir())), 1)
        installer.restore(self.home, run, apply=True)
        self.assertFalse(installer.exists(self.target))
        self.assertFalse((self.home / ".pi").exists())

    def extension_packages(self):
        packages = []
        for suffix in ("", "firecrawl-search"):
            relative = Path("pi/agent/extensions") / suffix
            source = self.repo / relative
            target = self.home / ".pi/agent/extensions" / suffix
            source.mkdir(parents=True, exist_ok=True)
            (source / "package.json").write_text('{"private": true}')
            (source / "index.ts").write_text('export default function () {}')
            for name in ("package.json", "index.ts"):
                self.mappings.append({"source": str(relative / name),
                                      "target": str(target.relative_to(self.home) / name)})
            packages.append((source / "node_modules", target / "node_modules"))
        self.write_manifest()
        return packages

    def test_dependency_links_before_npm_install_are_repeatable_and_restorable(self):
        packages = self.extension_packages()
        self.install()
        self.assertEqual(list(self.home.iterdir()), [])
        symlink_to = Path.symlink_to

        def check_directory_link(path, destination, target_is_directory=False):
            if path.name == "node_modules":
                self.assertTrue(target_is_directory)
            return symlink_to(path, destination, target_is_directory=target_is_directory)

        with patch.object(Path, "symlink_to", check_directory_link):
            run = self.install(apply=True)
        for source, target in packages:
            self.assertTrue(target.is_symlink())
            self.assertFalse(target.exists())
            self.assertEqual(target.resolve(), source)
        self.assertIsNone(self.install(apply=True))
        for source, target in packages:
            source.mkdir()
            (source / "installed.txt").write_text("installed later")
            self.assertEqual((target / "installed.txt").read_text(), "installed later")
        self.assertIsNone(self.install(apply=True))
        installer.restore(self.home, run, apply=True)
        for source, target in packages:
            self.assertFalse(installer.exists(target))
            self.assertEqual((source / "installed.txt").read_text(), "installed later")

    def test_existing_dependency_directories_are_backed_up_and_restored(self):
        packages = self.extension_packages()
        for source, target in packages:
            source.mkdir()
            target.mkdir(parents=True)
            (target / "local.txt").write_text("keep original dependencies")
        with self.assertRaisesRegex(installer.InstallError, "Occupied target"):
            self.install(apply=True)
        self.assertFalse(self.target.exists())
        run = self.install(apply=True, backup_existing=True)
        for source, target in packages:
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), source)
        installer.restore(self.home, run, apply=True)
        for _, target in packages:
            self.assertFalse(target.is_symlink())
            self.assertEqual((target / "local.txt").read_text(), "keep original dependencies")

    def test_escaping_dependency_directory_is_rejected(self):
        packages = self.extension_packages()
        outside = self.base / "outside"
        outside.mkdir()
        packages[0][0].symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(installer.InstallError, "Invalid dependency directory"):
            self.install(apply=True, backup_existing=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_dependency_source_must_be_a_directory(self):
        packages = self.extension_packages()
        packages[0][0].write_text("not a directory")
        with self.assertRaisesRegex(installer.InstallError, "Invalid dependency directory"):
            self.install(apply=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_explicit_node_modules_source_is_still_forbidden(self):
        source = self.repo / "node_modules"
        source.mkdir()
        self.mappings.append({"source": "node_modules", "target": "dependencies"})
        self.write_manifest()
        with self.assertRaisesRegex(installer.InstallError, "forbidden"):
            self.install(apply=True)
        self.assertEqual(list(self.home.iterdir()), [])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for module resolution")
    def test_dependencies_resolve_from_home_extension_paths(self):
        packages = self.extension_packages()
        for index, (source, _) in enumerate(packages):
            package = source / f"probe-{index}"
            package.mkdir(parents=True)
            (package / "index.js").write_text(f'module.exports = "package-{index}";')
        self.install(apply=True)
        for index, (_, target) in enumerate(packages):
            result = subprocess.run([
                "node", "-e",
                "const {createRequire} = require('node:module'); "
                "console.log(createRequire(process.argv[1])(process.argv[2]));",
                str(target.parent / "index.ts"), f"probe-{index}",
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"package-{index}")

    def test_missing_source_preflight(self):
        self.mappings.append({"source": "missing", "target": ".claude/settings.json"})
        self.write_manifest()
        with self.assertRaises(installer.InstallError):
            self.install(apply=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_late_conflict_preflight(self):
        (self.home / "occupied").write_text("keep")
        self.mappings.append({"source": "pi/agent/settings.json", "target": "occupied"})
        self.write_manifest()
        with self.assertRaises(installer.InstallError):
            self.install(apply=True)
        self.assertFalse((self.home / ".pi").exists())
        self.assertEqual((self.home / "occupied").read_text(), "keep")

    def test_escaping_manifest_paths(self):
        for field in ("source", "target"):
            for value in ("/tmp/escape", "../escape", "a/../../escape", "", "."):
                with self.subTest(field=field, value=value):
                    mapping = {"source": "pi/agent/settings.json", "target": ".pi/agent/settings.json"}
                    mapping[field] = value
                    self.mappings = [mapping]
                    self.write_manifest()
                    with self.assertRaises(installer.InstallError):
                        self.install(apply=True, backup_existing=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_escaping_source_symlink(self):
        outside = self.base / "outside"
        outside.write_text("do not read")
        (self.repo / "escape").symlink_to(outside)
        self.mappings = [{"source": "escape", "target": "leaf"}]
        self.write_manifest()
        with self.assertRaises(installer.InstallError):
            self.install(apply=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_escaping_target_ancestor(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / ".pi").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installer.InstallError):
            self.install(apply=True, backup_existing=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_duplicates_overlaps_and_aliased_targets(self):
        (self.home / "inside").mkdir()
        (self.home / "alias").symlink_to(self.home / "inside", target_is_directory=True)
        for targets in (("leaf", "leaf"), ("parent", "parent/child"), ("inside/file", "alias/file")):
            with self.subTest(targets=targets):
                self.mappings = [{"source": "pi/agent/settings.json", "target": target} for target in targets]
                self.write_manifest()
                with self.assertRaises(installer.InstallError):
                    self.install(apply=True)
        self.assertFalse((self.home / ".local").exists())

    def test_forbidden_source_and_directory_contents(self):
        for name in ("auth.json", "sessions", ".env.local", "private.pem", "credentials.json", "token.json"):
            with self.subTest(name=name):
                directory = self.repo / "skill"
                directory.mkdir(exist_ok=True)
                bad = directory / name
                bad.write_text("sensitive")
                self.mappings = [{"source": "skill", "target": "skill"}]
                self.write_manifest()
                with self.assertRaises(installer.InstallError):
                    self.install(apply=True)
                bad.unlink()
        self.assertEqual(list(self.home.iterdir()), [])

    def test_token_efficiency_source_is_not_a_credential(self):
        source = self.repo / "pi/agent/token-efficiency.ts"
        source.write_text("export const enabled = true;\n")
        self.mappings = [{"source": "pi/agent/token-efficiency.ts", "target": ".pi/agent/token-efficiency.ts"}]
        self.write_manifest()
        self.install(apply=True)
        self.assertTrue((self.home / ".pi/agent/token-efficiency.ts").is_symlink())

    def test_failure_rolls_back_only_run_changes(self):
        self.occupy()
        original = installer.identity(self.target)
        other = self.home / "existing-link"
        other.symlink_to(self.source)
        self.mappings.extend([
            {"source": "pi/agent/settings.json", "target": "existing-link"},
            {"source": "pi/agent/settings.json", "target": "new/second"},
        ])
        self.write_manifest()
        symlink_to = Path.symlink_to

        def fail_second(path, *args, **kwargs):
            if path.name == "second":
                raise OSError("simulated failure")
            return symlink_to(path, *args, **kwargs)

        with patch.object(Path, "symlink_to", fail_second):
            with self.assertRaisesRegex(installer.InstallError, "rolled back"):
                self.install(apply=True, backup_existing=True)
        self.assertEqual(installer.identity(self.target), original)
        self.assertEqual(self.target.read_text(), "original")
        self.assertTrue(other.is_symlink())
        self.assertFalse((self.home / "new").exists())

    def test_journal_precedes_backup_move(self):
        self.occupy()
        rename = Path.rename

        def checked_rename(path, destination):
            if path == self.target:
                journal = json.loads((Path(destination).parent / "journal.json").read_text())
                self.assertEqual(journal["links"][0]["progress"], "planned")
                self.assertEqual(journal["links"][0]["backup"], str(destination))
            return rename(path, destination)

        with patch.object(Path, "rename", checked_rename):
            self.install(apply=True, backup_existing=True)

    def test_changed_link_blocks_entire_restore(self):
        self.occupy()
        self.mappings.append({"source": "pi/agent/settings.json", "target": "second"})
        self.write_manifest()
        run = self.install(apply=True, backup_existing=True)
        second = self.home / "second"
        second.unlink()
        second.write_text("user changed this")
        with self.assertRaisesRegex(installer.InstallError, "changed"):
            installer.restore(self.home, run, apply=True)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual((run / "0").read_text(), "original")
        self.assertEqual(second.read_text(), "user changed this")

    def test_backup_symlink_original_is_preserved(self):
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to("missing-original")
        run = self.install(apply=True, backup_existing=True)
        installer.restore(self.home, run, apply=True)
        self.assertEqual(os.readlink(self.target), "missing-original")

    def test_replaced_link_with_same_destination_refuses_restore(self):
        run = self.install(apply=True)
        self.target.unlink()
        self.target.symlink_to(self.source)
        with self.assertRaisesRegex(installer.InstallError, "replaced"):
            installer.restore(self.home, run, apply=True)
        self.assertTrue(self.target.is_symlink())

    def test_restore_failure_can_resume_without_losing_original(self):
        self.occupy()
        run = self.install(apply=True, backup_existing=True)
        rename = Path.rename

        def fail_backup_move(path, destination):
            if path == run / "0":
                raise OSError("simulated restore failure")
            return rename(path, destination)

        with patch.object(Path, "rename", fail_backup_move):
            with self.assertRaisesRegex(installer.InstallError, "Restore incomplete.*run:"):
                installer.restore(self.home, run, apply=True)
        self.assertEqual((run / "0").read_text(), "original")
        self.assertFalse(installer.exists(self.target))
        installer.restore(self.home, run, apply=True)
        self.assertEqual(self.target.read_text(), "original")

    def test_malformed_manifest_does_not_mutate_home(self):
        for manifest in ([], {"version": True, "links": []},
                         {"version": 2, "links": []}, {"version": 1, "links": [None]}):
            with self.subTest(manifest=manifest):
                self.manifest.write_text(json.dumps(manifest))
                with self.assertRaises(installer.InstallError):
                    self.install(apply=True)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_state_escape_and_reserved_target(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / ".local").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installer.InstallError):
            self.install(apply=True)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(outside.iterdir()), [])
        self.mappings = [{"source": "pi/agent/settings.json", "target": ".local"}]
        self.write_manifest()
        with self.assertRaises(installer.InstallError):
            self.install(apply=True, backup_existing=True)

    def test_inside_home_ancestor_cannot_modify_repository(self):
        nested_repo = self.home / "agent-config"
        nested_repo.mkdir()
        (nested_repo / "source").write_text("original")
        (self.home / "alias").symlink_to(nested_repo, target_is_directory=True)
        self.manifest.write_text(json.dumps({"version": 1, "links": [
            {"source": "source", "target": "alias/source"},
        ]}))
        with self.assertRaises(installer.InstallError):
            installer.install(nested_repo, self.home, self.manifest, apply=True, backup_existing=True)
        self.assertEqual((nested_repo / "source").read_text(), "original")
        self.assertFalse((self.home / ".local").exists())

    def test_uncertain_original_backup_refuses_restore(self):
        self.occupy()
        run = self.install(apply=True, backup_existing=True)
        (run / "0").rename(run / "original-moved-by-user")
        with self.assertRaisesRegex(installer.InstallError, "uncertain"):
            installer.restore(self.home, run, apply=True)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual((run / "original-moved-by-user").read_text(), "original")

    def test_malformed_parent_journal_prevents_any_restore(self):
        self.occupy()
        run = self.install(apply=True, backup_existing=True)
        path = run / "journal.json"
        journal = json.loads(path.read_text())
        journal["parents"].append({"path": str(self.base / "outside"), "identity": [1, 2, 3]})
        path.write_text(json.dumps(journal))
        with self.assertRaises(installer.InstallError):
            installer.restore(self.home, run, apply=True)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual((run / "0").read_text(), "original")

    def test_failure_does_not_remove_a_concurrently_created_leaf(self):
        symlink_to = Path.symlink_to

        def fail_with_other_link(path, *args, **kwargs):
            symlink_to(path, *args, **kwargs)
            raise OSError("another process occupied this path")

        with patch.object(Path, "symlink_to", fail_with_other_link):
            with self.assertRaisesRegex(installer.InstallError, "rollback incomplete.*run:"):
                self.install(apply=True)
        self.assertTrue(self.target.is_symlink())

    def test_cli_default_is_dry_run_and_restore_requires_apply(self):
        command = [sys.executable, str(SCRIPT), "--home", str(self.home),
                   "--manifest", str(self.manifest)]
        # CLI sources are relative to the script's repository, not the manifest.
        self.mappings = [{"source": "AGENTS.md", "target": "config"}]
        self.write_manifest()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        result = subprocess.run(command + ["--apply"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next((self.home / installer.STATE).iterdir())
        restore_command = [sys.executable, str(SCRIPT), "--home", str(self.home), "--restore", str(run)]
        result = subprocess.run(restore_command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / "config").is_symlink())
        result = subprocess.run(restore_command + ["--apply"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(installer.exists(self.home / "config"))


if __name__ == "__main__":
    unittest.main()
