"""Resolve an installed Zig compatible with this checkout's libghostty-vt."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def installed_version(binary):
    result = subprocess.run([binary, "version"], check=True, capture_output=True,
                            text=True, timeout=5)
    version = result.stdout.strip()
    if not VERSION.fullmatch(version):
        raise ValueError(f"Unsupported Zig version from {binary}: {version!r}")
    return version


def compatible(actual, required):
    current = tuple(map(int, actual.split(".")))
    minimum = tuple(map(int, required.split(".")))
    # libghostty-vt/src/build/zig.zig requires the same major/minor and >= patch.
    return current[:2] == minimum[:2] and current[2] >= minimum[2]


def resolve_zig(checkout):
    manifest = checkout / "vendor/libghostty-vt/build.zig.zon"
    versions = re.findall(r'^\s*\.minimum_zig_version\s*=\s*"([^"\n]+)"\s*,',
                          manifest.read_text(encoding="utf-8"), re.MULTILINE)
    if len(versions) != 1 or not VERSION.fullmatch(versions[0]):
        raise ValueError(f"Cannot read one stable minimum_zig_version from {manifest}")
    required = versions[0]
    explicit = os.environ.get("ZIG")
    candidates = [os.path.expanduser(explicit)] if explicit else [
        shutil.which("zig"), str(Path.home() / ".local" / f"zig-{required}" / "zig"),
    ]
    failures = []
    for candidate in candidates:
        if not candidate:
            continue
        binary = shutil.which(candidate)
        if not binary:
            failures.append(f"{candidate}: not executable or not found")
            continue
        try:
            actual = installed_version(binary)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures.append(f"{candidate}: {error}")
            continue
        if compatible(actual, required):
            return str(Path(binary).resolve())
        failures.append(f"{candidate}: found {actual}")
    selection = "explicit $ZIG" if explicit else "PATH and local installation"
    detail = "; ".join(failures) or "no candidates found"
    raise ValueError(f"No compatible Zig from {selection}; required {required} "
                     f"(same major/minor, minimum patch). {detail}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    args = parser.parse_args()
    try:
        print(resolve_zig(args.checkout))
    except (OSError, ValueError) as error:
        print(f"Zig resolution failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
