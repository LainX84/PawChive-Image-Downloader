"""Build a standalone release of PawChive Image Downloader for this computer.

    python -m pip install -r requirements-build.txt
    python tools/build.py

The result is written to dist/:
  Windows  PawChive-Image-Downloader-<version>-windows-x64.zip
  Linux    PawChive-Image-Downloader-<version>-linux-x64.tar.gz
  macOS    PawChive-Image-Downloader-<version>-macos-arm64.dmg / -macos-x64.dmg (plus a .zip)

The same script is used by the GitHub release workflow.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pawchive_downloader.version import APP_NAME, __version__  # noqa: E402

SLUG = "PawChive-Image-Downloader"


def platform_tag() -> str:
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    return f"{system}-{arch}"


def run(*command: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=ROOT)


def build() -> Path:
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    run(sys.executable, "-m", "PyInstaller", "packaging/pawchive.spec", "--noconfirm", "--clean")
    dist = ROOT / "dist"
    return dist / (f"{APP_NAME}.app" if sys.platform == "darwin" else APP_NAME)


def self_test(bundle: Path) -> None:
    if sys.platform == "darwin":
        executable = bundle / "Contents" / "MacOS" / "PawChiveDownloader"
    else:
        executable = bundle / ("PawChiveDownloader.exe" if sys.platform == "win32" else "PawChiveDownloader")
    result = subprocess.run([str(executable), "--self-test"], timeout=180)
    if result.returncode != 0:
        raise SystemExit(f"self-test of the packaged application failed (exit code {result.returncode})")
    print("Packaged application self-test passed.")


def package(bundle: Path) -> list[Path]:
    dist = ROOT / "dist"
    base = f"{SLUG}-{__version__}-{platform_tag()}"
    outputs: list[Path] = []
    if sys.platform == "win32":
        archive = shutil.make_archive(str(dist / base), "zip", root_dir=dist, base_dir=bundle.name)
        outputs.append(Path(archive))
    elif sys.platform == "darwin":
        zip_path = dist / f"{base}.zip"
        run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(zip_path))
        outputs.append(zip_path)
        staging = dist / "dmg"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        run("cp", "-R", str(bundle), str(staging))
        (staging / "Applications").symlink_to("/Applications")
        dmg = dist / f"{base}.dmg"
        dmg.unlink(missing_ok=True)
        run("hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging), "-ov", "-format", "UDZO", str(dmg))
        outputs.append(dmg)
    else:
        tar_path = dist / f"{base}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            tar.add(bundle, arcname=f"{SLUG}-{__version__}")
        outputs.append(tar_path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-test", action="store_true", help="do not run the packaged application's self-test")
    args = parser.parse_args()
    bundle = build()
    if not args.skip_test:
        self_test(bundle)
    for path in package(bundle):
        print(f"Created {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
