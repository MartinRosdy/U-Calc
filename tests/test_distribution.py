import subprocess
import sys
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from importlib.metadata import version as installed_version
from pathlib import Path, PurePosixPath


class DistributionTests(unittest.TestCase):
    def test_coverage_contract_measures_only_production_package(self) -> None:
        root = Path(__file__).resolve().parents[1]
        configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(configuration["tool"]["coverage"]["run"]["source"], ["u_calc"])
        self.assertGreaterEqual(configuration["tool"]["coverage"]["report"]["fail_under"], 90)

    def test_active_environment_uses_current_project_version(self) -> None:
        root = Path(__file__).resolve().parents[1]
        expected = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["version"]
        self.assertEqual(installed_version("u-calc"), expected)

    def test_wheel_and_sdist_are_complete_release_artifacts(self) -> None:
        root = Path(__file__).resolve().parents[1]
        version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["version"]
        archive_root = f"u_calc-{version}"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--outdir",
                    str(output),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            sdist = output / f"u_calc-{version}.tar.gz"
            wheel = output / f"u_calc-{version}-py3-none-any.whl"
            self.assertTrue(sdist.is_file())
            self.assertTrue(wheel.is_file())

            required_source_files = {
                "Dockerfile",
                "README.md",
                "compose.yaml",
                "docker-entrypoint.sh",
                "main.py",
                "pyproject.toml",
                "requirements.txt",
                "requirements-lock.txt",
                ".env.example",
                ".github/workflows/ci.yml",
                "docs/BOTHOST_DEPLOY.md",
                "docs/CALCULATION_METHOD.md",
                "scripts/sync_requirements.py",
                "tests/startup_contract.py",
            }
            with tarfile.open(sdist, "r:gz") as archive:
                source_names = {
                    str(PurePosixPath(name).relative_to(archive_root))
                    for name in archive.getnames()
                    if name != archive_root
                }
            self.assertTrue(required_source_files <= source_names)
            self.assertFalse(
                any(
                    "__pycache__" in name
                    or name.endswith((".pyc", ".db", ".sqlite", ".log"))
                    or name.endswith("/.env")
                    for name in source_names
                )
            )

            with zipfile.ZipFile(wheel) as archive:
                wheel_names = set(archive.namelist())
                entry_points_name = next(
                    name for name in wheel_names if name.endswith(".dist-info/entry_points.txt")
                )
                entry_points = archive.read(entry_points_name).decode("utf-8")
            self.assertIn("u_calc/doctor.py", wheel_names)
            self.assertIn("u_calc/assets/fonts/NotoSans-Regular.ttf", wheel_names)
            self.assertIn("u-calc-bot = u_calc.bot:main", entry_points)
            self.assertIn("u-calc-backup = u_calc.backup:main", entry_points)
            self.assertIn("u-calc-demo = u_calc.demo:main", entry_points)
            self.assertIn("u-calc-doctor = u_calc.doctor:main", entry_points)
            self.assertIn("u-calc-restore = u_calc.backup:restore_main", entry_points)
            self.assertFalse(any(name.startswith("tests/") for name in wheel_names))


if __name__ == "__main__":
    unittest.main()
