import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = (Path(__file__).resolve().parents[1]
          / "common/skills/herdr-build/scripts/resolve-zig.py")


class HerdrBuildToolchainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="zig-resolver-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.checkout = self.root / "checkout"
        self.manifest = self.checkout / "vendor/libghostty-vt/build.zig.zon"
        self.manifest.parent.mkdir(parents=True)
        self.require("0.16.0")
        self.env = {**os.environ, "HOME": str(self.home), "PATH": str(self.bin)}
        self.env.pop("ZIG", None)

    def require(self, version):
        self.manifest.write_text(f'.{{\n    .minimum_zig_version = "{version}",\n}}\n')

    def zig(self, path, version):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = version ] || exit 91\nprintf "%s\\n" "{version}"\n')
        path.chmod(0o755)
        return path

    def resolve(self):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.checkout)],
                              env=self.env, capture_output=True, text=True)

    def test_explicit_compatible_zig_is_selected(self):
        binary = self.zig(self.root / "explicit zig", "0.16.0")
        self.env["ZIG"] = str(binary)
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(binary))

    def test_incompatible_explicit_zig_is_not_silently_replaced(self):
        self.env["ZIG"] = str(self.zig(self.root / "explicit", "0.15.2"))
        self.zig(self.bin / "zig", "0.16.0")
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit $ZIG", result.stderr)
        self.assertIn("required 0.16.0", result.stderr)
        self.assertIn("found 0.15.2", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_explicit_zig_is_not_replaced(self):
        self.env["ZIG"] = str(self.root / "missing")
        self.zig(self.bin / "zig", "0.16.0")
        self.assertNotEqual(self.resolve().returncode, 0)

    def test_wrong_path_version_uses_matching_local_installation(self):
        self.zig(self.bin / "zig", "0.15.2")
        local = self.zig(self.home / ".local/zig-0.16.0/zig", "0.16.0")
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(local))

    def test_missing_zig_fails_without_installing(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required 0.16.0", result.stderr)
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")))

    def test_changed_checkout_requirement_changes_local_selection(self):
        self.require("0.17.1")
        self.zig(self.home / ".local/zig-0.16.0/zig", "0.16.0")
        local = self.zig(self.home / ".local/zig-0.17.1/zig", "0.17.1")
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(local))

    def test_patch_compatibility_matches_libghostty_not_arbitrary_newer_versions(self):
        for version, success in [("0.16.1", True), ("0.17.0", False),
                                 ("1.16.0", False), ("0.16.0-dev.1", False)]:
            with self.subTest(version=version):
                self.zig(self.bin / "zig", version)
                result = self.resolve()
                self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_unreadable_or_invalid_requirement_fails(self):
        for content in ('', '.minimum_zig_version = "dev",',
                        '.minimum_zig_version = "0.16.0",\n.minimum_zig_version = "0.17.0",'):
            with self.subTest(content=content):
                self.manifest.write_text(content)
                self.assertNotEqual(self.resolve().returncode, 0)
        self.manifest.unlink()
        self.assertNotEqual(self.resolve().returncode, 0)

    def test_failed_version_command_is_a_resolution_error(self):
        binary = self.bin / "zig"
        binary.write_text('#!/bin/sh\nexit 23\n')
        binary.chmod(0o755)
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Zig resolution failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
