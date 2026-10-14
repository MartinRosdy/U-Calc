import os
import re
import subprocess
import unittest
from pathlib import Path


class DockerEntrypointTests(unittest.TestCase):
    def test_python_base_image_is_pinned_to_a_multi_arch_digest(self) -> None:
        dockerfile = (
            Path(__file__).resolve().parents[1] / "Dockerfile"
        ).read_text(encoding="utf-8")
        first_line = dockerfile.splitlines()[0]
        self.assertRegex(
            first_line,
            re.compile(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64} AS builder$"),
        )
        self.assertEqual(
            first_line,
            "FROM python:3.12-slim@sha256:"
            "a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 "
            "AS builder",
        )

    def test_runtime_stage_contains_installed_prefix_without_build_sources(self) -> None:
        dockerfile = (
            Path(__file__).resolve().parents[1] / "Dockerfile"
        ).read_text(encoding="utf-8")
        expected_base = (
            "python:3.12-slim@sha256:"
            "a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"
        )
        self.assertEqual(dockerfile.count(f"FROM {expected_base}"), 2)
        self.assertIn(f"FROM {expected_base} AS runtime", dockerfile)
        runtime = dockerfile.split(" AS runtime", maxsplit=1)[1]
        self.assertIn("COPY --from=builder /install /usr/local", runtime)
        self.assertNotIn("pip install", runtime)
        self.assertNotIn("COPY src", runtime)
        self.assertNotIn("COPY pyproject.toml", runtime)

    def test_private_umask_is_set_before_data_path_handling(self) -> None:
        entrypoint = (
            Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
        ).read_text(encoding="utf-8")
        self.assertLess(entrypoint.index("umask 077"), entrypoint.index("database_path="))

    def test_privilege_drop_uses_pinned_base_utility_without_apt_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (root / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertNotIn("apt-get", dockerfile)
        self.assertNotIn("gosu", dockerfile)
        self.assertNotIn("gosu", entrypoint)
        self.assertIn(
            "setpriv --reuid=ucalc --regid=ucalc --init-groups --no-new-privs",
            entrypoint,
        )

    def test_rejects_database_paths_outside_persistent_data_root(self) -> None:
        root = Path(__file__).resolve().parents[1]
        entrypoint = root / "docker-entrypoint.sh"
        for database_path in (
            "/etc/u_calc.db",
            "/app/data",
            "/app/data/../outside/u_calc.db",
            "/app/data-not-the-volume/u_calc.db",
        ):
            with self.subTest(database_path=database_path):
                environment = os.environ.copy()
                environment["DATABASE_PATH"] = database_path
                completed = subprocess.run(
                    ["sh", str(entrypoint), "true"],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertIn("inside /app/data", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
