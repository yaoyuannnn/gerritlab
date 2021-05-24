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
        review.load_config(self._remote.name, self._test_repo)
        self._local_branch = self._test_repo.active_branch.name

    def tearDown(self):
        shutil.rmtree(self._test_project_dir)

    def test_create_single_mr(self):
        new_file_path = os.path.join(
            self._test_repo.working_tree_dir, "new_file.txt")
        open(new_file_path, "wb").close()
        self._test_repo.index.add([new_file_path])
        self._test_repo.index.commit("Add a new file.")
        # Create an MR.
        review.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        commit = self._test_repo.head.commit
        source_branch = review.get_remote_branch_name(
            self._local_branch, review.get_change_id(commit.message))
        mr = review.get_merge_request(source_branch)
        self.assertTrue(mr != None)
        # Delete the MR and its source branch.
        mr.delete()
        self._remote.push(refspec=(":{}".format(source_branch)))

    def test_create_multiple_mrs(self):
        new_file0_path = os.path.join(
            self._test_repo.working_tree_dir, "new_file0.txt")
        new_file1_path = os.path.join(
            self._test_repo.working_tree_dir, "new_file1.txt")
        open(new_file0_path, "wb").close()
        open(new_file1_path, "wb").close()
        self._test_repo.index.add([new_file0_path])
        self._test_repo.index.commit("Add a new file0.")
        self._test_repo.index.add([new_file1_path])
        self._test_repo.index.commit("Add a new file1.")
        # Create two MRs.
        review.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        for i in range(2):
            commit = self._test_repo.commit("HEAD~{}".format(i))
            source_branch = review.get_remote_branch_name(
                self._local_branch, review.get_change_id(commit.message))
            mr = review.get_merge_request(source_branch)
            self.assertTrue(mr != None)
            # Delete the MR/source branche.
            mr.delete()
            self._remote.push(refspec=(":{}".format(source_branch)))

    def test_update_mrs(self):
        pass


if __name__ == "__main__":
    unittest.main()
