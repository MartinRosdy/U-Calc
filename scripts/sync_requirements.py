"""Keep Bothost requirements and production constraints aligned with pyproject."""

import argparse
import re
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s;]+)$")


def _project_dependencies() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = list(pyproject["project"]["dependencies"])
    for dependency in dependencies:
        if PIN.fullmatch(dependency) is None:
            raise RuntimeError(
                f"Production dependency must use an exact == pin: {dependency}"
            )
    return dependencies


def _requirements_content(dependencies: list[str]) -> str:
    return (
        "# Generated from project.dependencies in pyproject.toml.\n"
        "# Update with: python scripts/sync_requirements.py\n"
        + "\n".join(dependencies)
        + "\n"
    )


def _normalized_name(value: str) -> str:
    return canonicalize_name(value)


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PIN.fullmatch(stripped)
        if match is None:
            raise RuntimeError(f"Lock line must use an exact == pin: {stripped}")
        name = _normalized_name(match.group("name"))
        if name in pins:
            raise RuntimeError(f"Duplicate dependency in requirements-lock.txt: {name}")
        pins[name] = match.group("version")
    return pins


def check() -> None:
    dependencies = _project_dependencies()
    expected = _requirements_content(dependencies)
    actual = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    if actual != expected:
        raise RuntimeError(
            "requirements.txt is out of sync; run python scripts/sync_requirements.py"
        )

    lock = _lock_pins()
    for dependency in dependencies:
        match = PIN.fullmatch(dependency)
        assert match is not None
        name = _normalized_name(match.group("name"))
        version = match.group("version")
        if lock.get(name) != version:
            raise RuntimeError(
                f"requirements-lock.txt must contain {name}=={version}; "
                f"found {lock.get(name) or 'no pin'}"
            )


def check_installed() -> None:
    """Prove that the lock is the exact active runtime graph in this environment."""
    check()
    lock = _lock_pins()
    queue = []
    for dependency in _project_dependencies():
        match = PIN.fullmatch(dependency)
        assert match is not None
        queue.append(match.group("name"))

    visited: set[str] = set()
    while queue:
        name = _normalized_name(queue.pop())
        if name in visited:
            continue
        visited.add(name)
        locked_version = lock.get(name)
        if locked_version is None:
            raise RuntimeError(f"Runtime dependency is missing from lock: {name}")
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"Locked runtime dependency is not installed: {name}") from exc
        if distribution.version != locked_version:
            raise RuntimeError(
                f"Installed {name}=={distribution.version}, lock requires {locked_version}"
            )
        for raw_requirement in distribution.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
                continue
            child = _normalized_name(requirement.name)
            child_version = lock.get(child)
            if child_version is None:
                raise RuntimeError(
                    f"Transitive dependency {name} -> {child} is missing from lock"
                )
            if requirement.url is not None:
                raise RuntimeError(f"Direct URL dependency is not allowed in runtime lock: {child}")
            if requirement.specifier and not requirement.specifier.contains(
                child_version, prereleases=True
            ):
                raise RuntimeError(
                    f"Lock has {child}=={child_version}, but {name} requires "
                    f"{requirement.specifier}"
                )
            queue.append(child)

    inactive_or_extra = sorted(set(lock) - visited)
    if inactive_or_extra:
        raise RuntimeError(
            "requirements-lock.txt contains packages outside the active runtime graph: "
            + ", ".join(inactive_or_extra)
        )


def write() -> None:
    dependencies = _project_dependencies()
    (ROOT / "requirements.txt").write_text(
        _requirements_content(dependencies),
        encoding="utf-8",
        newline="\n",
    )
    check()


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate requirements.txt and direct pins in requirements-lock.txt",
    )
    mode.add_argument(
        "--check-installed",
        action="store_true",
        help="validate the complete installed runtime graph against the lock",
    )
    arguments = parser.parse_args()
    if arguments.check_installed:
        check_installed()
    elif arguments.check:
        check()
    else:
        write()


if __name__ == "__main__":
    main()
