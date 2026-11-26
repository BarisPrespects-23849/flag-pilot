"""A SYNTHETIC app repository with a local bare remote, for cleanup and retire tests."""

import subprocess
import sys
from pathlib import Path

FLAG = "demo_flag"

FILES = {
    ".gitignore": "__pycache__/\n",
    "pytest.ini": "[pytest]\npythonpath = .\nmarkers =\n    flag(name): synthetic\n",
    "demo/__init__.py": "",
    "demo/app.py": f'''def label(client, user):
    flag = client.get_experiment_flag("{FLAG}", identifier=user)
    client.track_event("purchase", identifier=user)
    if flag.enabled and flag.value == "buy_now":
        return "Buy now"
    return "Checkout"
''',
    "tests/test_app.py": '''import demo.app


def test_imports():
    assert demo.app.label
''',
    "tests/test_flag.py": f'''import pytest

pytestmark = pytest.mark.flag("{FLAG}")


def test_only_while_the_flag_exists():
    pass
''',
    "tool/names.py": f'FLAG = "{FLAG}"\n',
}

SETTINGS_CLEANUP = {
    "app_paths": ["demo"],
    "test_paths": ["tests"],
    "base_branch": "main",
    "test_command": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def commit_and_push(root: Path, message: str = "change") -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    git(root, "push", "-q", "origin", "main")


def make(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    remote, root = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid"),
                       ("commit.gpgsign", "false")):
        git(root, "config", key, value)
    git(root, "remote", "add", "origin", str(remote))
    write(root, files or FILES)
    commit_and_push(root, "initial")
    return root
