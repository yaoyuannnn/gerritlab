#!/usr/bin/env python

import os
import pytest
import sys
import textwrap

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from gerritlab import git_credentials

@pytest.fixture
def git_credential_store():
    git_credential_store = git_credentials.instance("https://gitlab.com")
    git_credential_store._git_credentials_fetched = True
    yield git_credential_store


def test_git_instances(git_credential_store):
    assert git_credentials.instance("https://gitlab.com") is git_credential_store


def test_git_credential_store(git_credential_store):
    fill_output = """
        protocol=https
        host=gitlab.com
        password=hunter2
        foo=bar
    """
    git_credential_store._populate_git_credentials(textwrap.dedent(fill_output))
    assert git_credential_store.get("password") == "hunter2"
    assert git_credential_store.get_token() == "hunter2"
