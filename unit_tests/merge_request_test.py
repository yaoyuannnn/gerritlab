#!/usr/bin/env python

import sys
import os
import unittest
from git import Repo
import shutil
import tempfile
import time

repo = Repo(os.path.realpath(__file__), search_parent_directories=True)
repo_path = repo.git.rev_parse("--show-toplevel")
sys.path.append(repo_path)
from gerritlab import main, merge_request, global_vars, utils

GITLAB_TEST_PROJECT_PATH = "unit_tests/gerritlab_tests"
REMOTE_NAME = "origin"
LOCAL_BRANCH = "master"
USER = "Yuan Yao"
EMAIL = "yaoyuannnn@gmail.com"

class MergeRequestTest(unittest.TestCase):

    def setUp(self):
        self._test_project_dir = os.path.join(
            repo_path, GITLAB_TEST_PROJECT_PATH)
        self._test_repo = Repo(self._test_project_dir)
        self._remote = self._test_repo.remote(name=REMOTE_NAME)
        # Install the post-commit hook for the GitLab test repo.
        shutil.copy(
            os.path.join(repo_path, "commit-msg"),
            os.path.join(
                repo_path, ".git/modules/{}/hooks/commit-msg".format(
                    GITLAB_TEST_PROJECT_PATH)))
        self._test_repo.config_writer().set_value("user", "name",
                                                  USER).release()
        self._test_repo.config_writer().set_value("user", "email",
                                                  EMAIL).release()
        global_vars.load_config(self._remote.name, self._test_repo)
        self._local_branch = LOCAL_BRANCH
        self._test_repo.git.checkout(self._local_branch)

    def tearDown(self):
        self._remote.fetch(prune=True)
        self._test_repo.git.reset(
            "{}/{}".format(REMOTE_NAME, global_vars.global_target_branch),
            hard=True)

    def _create_commit(self, new_file_name, commit_msg):
        new_file_path = os.path.join(
            self._test_repo.working_tree_dir, new_file_name)
        open(new_file_path, "wb").close()
        self._test_repo.index.add([new_file_path])
        self._test_repo.index.commit(commit_msg)
        return self._test_repo.head.commit

    def _amend_commits(self, commits):
        self._test_repo.head.reset(
            "HEAD~{}".format(len(commits)), index=True, working_tree=True)
        # Replay each commit, modifying the message first
        amended_commits = []
        for idx, c in enumerate(commits):
            new_file_path = os.path.join(
                self._test_repo.working_tree_dir, "{}.txt".format(idx))
            open(new_file_path, "wb").close()
            self._test_repo.index.add([new_file_path])
            # We need to restore the Change ID in the new commit.
            change_id = utils.get_change_id(c.message)
            self._test_repo.git.commit(
                message="New message{}.\nChange-Id: {}".format(idx, change_id),
                no_verify=True)
            amended_commits.append(self._test_repo.head.commit)
        return amended_commits

    def _validate_mr(self, commit, target_branch):
        # GitLab seems to need a little bit of time before the commits of the
        # MRs get updated, after new commits are pushed to the branches.
        time.sleep(1)
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
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        mr = self._validate_mr(commit, global_vars.global_target_branch)
        mr.delete(delete_source_branch=True)

    def test_create_multiple_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        mrs = []
        # Validate the MRs.
        for idx, c in enumerate(commits):
            if idx == 0:
                mr = self._validate_mr(c, global_vars.global_target_branch)
            else:
                mr = self._validate_mr(c, mrs[-1].source_branch)
            mrs.append(mr)
        # Delete the MRs.
        for mr in mrs:
            mr.delete(delete_source_branch=True)

    def test_update_single_mr(self):
        # Create an MR.
        commit = self._create_commit("new_file.txt", "Add a new file.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Update the MR.
        amended_commit = self._amend_commits([commit])[0]
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Validate the updated MR.
        mr = self._validate_mr(amended_commit, global_vars.global_target_branch)
        mr.delete(delete_source_branch=True)

    def test_update_multiple_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Update the MRs.
        amended_commits = self._amend_commits(commits)
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Validate the updated MRs.
        mrs = []
        for idx, c in enumerate(amended_commits):
            if idx == 0:
                mr = self._validate_mr(c, global_vars.global_target_branch)
            else:
                mr = self._validate_mr(c, mrs[-1].source_branch)
            mrs.append(mr)
        # Delete the MRs.
        for mr in mrs:
            mr.delete(delete_source_branch=True)

    def test_update_some_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Update the MRs.
        amended_commits = self._amend_commits(commits[-2:])
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Validate the MRs.
        mrs = []
        for idx, c in enumerate([commits[0]] + amended_commits):
            if idx == 0:
                mr = self._validate_mr(c, global_vars.global_target_branch)
            else:
                mr = self._validate_mr(c, mrs[-1].source_branch)
            mrs.append(mr)
        # Delete the MRs.
        for mr in mrs:
            mr.delete(delete_source_branch=True)

    def test_insert_new_mr(self):
        # Create three MRs.
        commit0 = self._create_commit("new_file0.txt", "Add a new file0.")
        commit1 = self._create_commit("new_file1.txt", "Add a new file1.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Insert a new MR after the first MR.
        self._test_repo.head.reset("HEAD~1", index=True, working_tree=True)
        inserted_commit = self._create_commit(
            "inserted.txt", "Add a inserted MR.")
        # Rebase commit1.
        new_file_path = os.path.join(
            self._test_repo.working_tree_dir, "new_file1.txt")
        open(new_file_path, "wb").close()
        self._test_repo.index.add([new_file_path])
        # We need to restore the Change ID in the new commit.
        self._test_repo.git.commit(message=commit1.message, no_verify=True)
        rebased_commit1 = self._test_repo.head.commit
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Validate the MRs.
        mrs = []
        for idx, c in enumerate([commit0, inserted_commit, rebased_commit1]):
            if idx == 0:
                mr = self._validate_mr(c, global_vars.global_target_branch)
            else:
                mr = self._validate_mr(c, mrs[-1].source_branch)
            mrs.append(mr)
        # Delete the MRs.
        for mr in mrs:
            mr.delete(delete_source_branch=True)


if __name__ == "__main__":
    unittest.main()
