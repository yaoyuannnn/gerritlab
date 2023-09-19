#!/usr/bin/env python
import argparse
from git.repo import Repo
import subprocess
import os

repo = Repo(os.path.realpath(__file__), search_parent_directories=True)
repo_path = repo.working_tree_dir


def run_black_formatter(apply_diff):
    """
    Runs black on all *.py files for style checks.
    """
    command = "black"
    if not apply_diff:
        command += " --check --diff --color"
    command += " $(git ls-files '*.py')"
    subprocess.run(command, cwd=repo_path, shell=True, text=True, check=True)


def run_flake8_linter():
    """
    Runs the flake8 linter.
    """
    subprocess.run("flake8 .", cwd=repo_path, shell=True, text=True, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-diff",
        action="store_true",
        default=False,
        help="apply edits to files instead of displaying a diff",
    )
    args = parser.parse_args()
    run_black_formatter(args.apply_diff)
    run_flake8_linter()
