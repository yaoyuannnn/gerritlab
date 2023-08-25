#!/usr/bin/env python

import sys
import os
import unittest
from git.repo import Repo
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
    # GitLab seems to need a little bit of time before the commits of the
    # MRs get updated, after new commits are pushed to the branches. This is
    # the time (in seconds) we'll wait before we validate the MRs.
    WAIT_TIME_BEFORE_VALIDATE = 10

    def setUp(self):
        self._test_project_dir = os.path.join(
            repo_path, GITLAB_TEST_PROJECT_PATH)
        self._test_repo = Repo(self._test_project_dir)
        self._remote = self._test_repo.remote(name=REMOTE_NAME)
        # Install the post-commit hook for the GitLab test repo.
        main.ensure_commitmsg_hook(self._test_repo.git_dir)
        self._test_repo.config_writer().set_value("user", "name",
                                                  USER).release()
        self._test_repo.config_writer().set_value("user", "email",
                                                  EMAIL).release()
        global_vars.load_config(self._remote.name, self._test_repo)
        self._local_branch = LOCAL_BRANCH
        self._test_repo.git.checkout(self._local_branch)
        global_vars.ci_mode = True
        self._wait_before_validate = True
        self._mrs = []

    def tearDown(self):
        self._remote.fetch(prune=True)
        self._test_repo.git.reset(
            "{}/{}".format(REMOTE_NAME, global_vars.global_target_branch),
            hard=True)
        # Remove all MRs created by the test.
        for mr in self._mrs:
            mr.delete(delete_source_branch=True)

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

    def _validate(self, commits):

        def validate_mr(mr, commit, target_branch):
            self.assertTrue(mr != None)
            self.assertEqual(mr.target_branch, target_branch)
            mr_commits = mr.get_commits()
            if len(mr_commits) != 1:
                # GitLab can run into this bug (shown below in the example) when
                # we change an MR's target branch.
                #
                # Example:
                #   main:  commit_a -> commit_b
                #     |                   |
                #     v                    \
                #   branch0 (MR0):          `-> commit_c
                #     |                            |
                #     V                             \
                #   branch1 (MR1):                   `-> commit_d
                #
                # In the example, MR1 is stacked on MR0, and MR0 and MR1 should
                # only show commit_c and commit_d, respectively. A GitLab glitch
                # can result in commit_c and commit_d both show up in MR1.
                # Waiting doesn't seem to fix this. Here we reload MR1 to make
                # commit_c disappear. Related GitLab issue:
                # https://gitlab.com/gitlab-org/gitlab-foss/-/issues/19026#note_36401573
                mr.reload()
                mr_commits = mr.get_commits()
            self.assertEqual(len(mr_commits), 1)
            self.assertEqual(mr_commits[0]["id"], commit.hexsha)
            return mr

        # Get the merge requests corresponding to the commits.
        for commit in commits:
            source_branch = utils.get_remote_branch_name(
                self._local_branch, utils.get_change_id(commit.message))
            self._mrs.append(
                merge_request.get_merge_request(self._remote, source_branch))

        # Wait some time before the validation, in order for GitLab to update
        # the MRs after seeing new commits.
        if self._wait_before_validate:
            time.sleep(MergeRequestTest.WAIT_TIME_BEFORE_VALIDATE)
            self._wait_before_validate = False

        for idx, (mr, commit) in enumerate(zip(self._mrs, commits)):
            validate_mr(
                mr, commit, global_vars.global_target_branch if idx == 0 else
                self._mrs[idx - 1].source_branch)

    def test_create_single_mr(self):
        # Create an MR.
        commit = self._create_commit("new_file.txt", "Add a new file.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        self._validate([commit])

    def test_create_multiple_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        self._validate(commits)

    def test_update_single_mr(self):
        # Create an MR.
        commit = self._create_commit("new_file.txt", "Add a new file.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        # Update the MR.
        amended_commit = self._amend_commits([commit])[0]
        main.create_merge_requests(
            self._test_repo, self._remote, self._local_branch)
        self._validate([amended_commit])

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
        self._validate(amended_commits)

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
        self._validate([commits[0]] + amended_commits)

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
        self._validate([commit0, inserted_commit, rebased_commit1])


if __name__ == "__main__":
    unittest.main()
