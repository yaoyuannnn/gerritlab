import os
import sys
import unittest
from git.repo import Repo

repo = Repo(os.path.realpath(__file__), search_parent_directories=True)
repo_path = repo.working_tree_dir
sys.path.append(repo_path)
from gerritlab import global_vars  # noqa: E402


class MiscTest(unittest.TestCase):
    def test_parse_remote_url(self):
        (url, quoted_path) = global_vars._parse_remote_url(
            "git@gitlab.com:user/myrepo.git"
        )
        assert url == "https://gitlab.com"
        assert quoted_path == "user%2Fmyrepo"
        (url, quoted_path) = global_vars._parse_remote_url(
            "git@gitlab.com:user/myrepo"
        )
        assert url == "https://gitlab.com"
        assert quoted_path == "user%2Fmyrepo"
        (url, quoted_path) = global_vars._parse_remote_url(
            "https://gitlab.com/user/myrepo.git"
        )
        assert url == "https://gitlab.com"
        assert quoted_path == "user%2Fmyrepo"
        (url, quoted_path) = global_vars._parse_remote_url(
            "https://gitlab.com/user/myrepo"
        )
        assert url == "https://gitlab.com"
        assert quoted_path == "user%2Fmyrepo"
