"""Keep Bothost-compatible requirements.txt aligned with pyproject.toml."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    content = (
        "# Generated from project.dependencies in pyproject.toml.\n"
        "# Update with: python scripts/sync_requirements.py\n" + "\n".join(dependencies) + "\n"
    )
    (ROOT / "requirements.txt").write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
