from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "demo_monorepo"


def copy_fixture(dest: Path) -> Path:
    root = dest / "demo"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def git_init_with_main(repo: Path) -> None:
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo, stdout=subprocess.DEVNULL)
    subprocess.check_call(["git", "config", "user.email", "loadpath@test"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "Loadpath Tests"], cwd=repo)
    subprocess.check_call(["git", "add", "-A"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "baseline"], cwd=repo, stdout=subprocess.DEVNULL)


def git_commit_all(repo: Path, message: str) -> None:
    subprocess.check_call(["git", "add", "-A"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", message], cwd=repo, stdout=subprocess.DEVNULL)


def change_serializer_total(repo: Path) -> None:
    path = repo / "backend/billing/serializers.py"
    text = path.read_text()
    path.write_text(
        text.replace(
            'fields = ["id", "customer_id", "total", "status"]',
            'fields = ["id", "customer_id", "total", "status"]\n        extra_kwargs = {"total": {"required": True}}',
        )
    )


def prepare_review_repo(dest: Path) -> Path:
    repo = copy_fixture(dest)
    git_init_with_main(repo)
    change_serializer_total(repo)
    git_commit_all(repo, "tighten Invoice.total contract")
    return repo
