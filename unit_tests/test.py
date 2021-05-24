#!/usr/bin/env python

import sys
import os
import unittest
from git import Repo
import shutil
import tempfile

repo = Repo(os.path.realpath(__file__), search_parent_directories=True)
repo_path = repo.git.rev_parse("--show-toplevel")
sys.path.append(repo_path)
import gitlab_gerrit_review as review
import merge_request
import global_vars
import utils

TEST_PROJECT_URL = "git@gitlab.com:yaoyuannnn/gitlab-gerrit-review-tests.git"


class MergeRequestTest(unittest.TestCase):

    def setUp(self):
        current_dir = os.path.dirname(os.path.realpath(__file__))
        self._test_project_dir = tempfile.mkdtemp()
        Repo.clone_from(TEST_PROJECT_URL, self._test_project_dir)
        self._test_repo = Repo(self._test_project_dir)
        self._remote = self._test_repo.remote(name="origin")
        shutil.copy(
            os.path.join(current_dir, ".gitreview"), self._test_project_dir)
        shutil.copy(
            os.path.join(repo_path, "commit-msg"),
            os.path.join(self._test_project_dir, ".git/hooks/commit-msg"))
        self._test_repo.config_writer().set_value("user", "name",
                                                  "Yuan Yao").release()
        self._test_repo.config_writer().set_value(
            "user", "email", "yaoyuannnn@gmail.com").release()
        global_vars.load_config(self._remote.name, self._test_repo)
        self._local_branch = self._test_repo.active_branch.name

    def tearDown(self):
        shutil.rmtree(self._test_project_dir)

    def _create_commit(self, new_file_name, commit_msg):
        new_file_path = os.path.join(
            self._test_repo.working_tree_dir, new_file_name)
        open(new_file_path, "wb").close()
        self._test_repo.index.add([new_file_path])
        self._test_repo.index.commit(commit_msg)
        return self._test_repo.head.commit

    def _validate_mr(self, commit, target_branch):
        source_branch = utils.get_remote_branch_name(
            self._local_branch, utils.get_change_id(commit.message))
        mr = merge_request.get_merge_request(self._remote, source_branch)
        self.assertTrue(mr != None)
        self.assertEqual(mr.target_branch, target_branch)
        mr_commits = mr.get_commits()
        self.assertEqual(len(mr_commits), 1)
        self.assertEqual(mr_commits[0]["id"], commit.hexsha)
        return mr

    def test_create_single_mr(self):
        # Create an MR.
        commit = self._create_commit("new_file.txt", "Add a new file.")
        review.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        mr = self._validate_mr(commit, global_vars.global_target_branch)
        mr.delete(delete_source_branch=True)

    def test_create_multiple_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        review.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        mrs = []
        # Validate the MRs.
        for i in range(3):
            commit = commits[i]
            if i == 0:
                mr = self._validate_mr(commit, global_vars.global_target_branch)
            else:
                mr = self._validate_mr(commit, mrs[-1].source_branch)
            mrs.append(mr)
        # Delete the MRs.
        for mr in mrs:
            mr.delete(delete_source_branch=True)

    def test_update_mrs(self):
        pass


if __name__ == "__main__":
    unittest.main()
