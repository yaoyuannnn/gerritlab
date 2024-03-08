#!/usr/bin/env python

import sys
import os
import unittest
import uuid
from git.repo import Repo

repo = Repo(os.path.realpath(__file__), search_parent_directories=True)
repo_path = repo.working_tree_dir
sys.path.append(repo_path)
from gerritlab import main, merge_request, global_vars, utils  # noqa: E402


GITLAB_TEST_PROJECT_PATH = "unit_tests/gerritlab_tests"
REMOTE_NAME = "origin"
LOCAL_BRANCH = "master"
USER = "Yuan Yao"
EMAIL = "yaoyuannnn@gmail.com"


class MergeRequestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._test_project_dir = os.path.join(
            repo_path, GITLAB_TEST_PROJECT_PATH
        )
        cls._test_repo = Repo(cls._test_project_dir)
        cls._remote = cls._test_repo.remote(name=REMOTE_NAME)
        # Install the post-commit hook for the GitLab test repo.
        main.ensure_commitmsg_hook(cls._test_repo.git_dir)
        cls._test_repo.config_writer().set_value("user", "name", USER).release()
        cls._test_repo.config_writer().set_value(
            "user", "email", EMAIL
        ).release()
        global_vars.load_config(cls._remote.name, cls._test_repo)
        global_vars.ci_mode = True

        cls._target_branch = f"test-{uuid.uuid4()}"
        resp = global_vars.session.post(
            global_vars.branches_url,
            params={"branch": cls._target_branch, "ref": LOCAL_BRANCH},
        )
        resp.raise_for_status()
        cls._remote.fetch(prune=True)

    @classmethod
    def tearDownClass(cls):
        # Delete the test target branch
        resp = global_vars.session.delete(
            "{}/{}".format(global_vars.branches_url, cls._target_branch)
        )
        resp.raise_for_status()

    # This runs before every test method
    def setUp(self):
        self._test_repo.git.checkout(LOCAL_BRANCH)
        self._test_repo.git.reset(
            "{}/{}".format(REMOTE_NAME, global_vars.global_target_branch),
            hard=True,
        )
        self._mrs = []
        # Start with fresh timing information each test.
        main.timers = {}

    # This runs after every test method
    def tearDown(self):
        self._test_repo.git.reset(
            "{}/{}".format(REMOTE_NAME, global_vars.global_target_branch),
            hard=True,
        )
        # Remove all MRs created by the test.
        for mr in self._mrs:
            mr.delete(delete_source_branch=True)

    def _create_commit(self, new_file_name, commit_msg):
        new_file_path = os.path.join(
            self._test_repo.working_tree_dir, new_file_name
        )
        open(new_file_path, "wb").close()
        self._test_repo.index.add([new_file_path])
        self._test_repo.index.commit(commit_msg)
        return self._test_repo.head.commit

    def _amend_commits(self, commits):
        self._test_repo.head.reset(
            "HEAD~{}".format(len(commits)), index=True, working_tree=True
        )
        # Replay each commit, modifying the message first
        amended_commits = []
        for idx, c in enumerate(commits):
            new_file_path = os.path.join(
                self._test_repo.working_tree_dir, "{}.txt".format(idx)
            )
            open(new_file_path, "wb").close()
            self._test_repo.index.add([new_file_path])
            # We need to restore the Change ID in the new commit.
            change_id = utils.get_change_id(c.message)
            self._test_repo.git.commit(
                message="New message{}.\nChange-Id: {}".format(idx, change_id),
                no_verify=True,
            )
            amended_commits.append(self._test_repo.head.commit)
        return amended_commits

    def _validate(self, commits):
        def validate_mr(mr, commit, target_branch):
            self.assertTrue(mr is not None)
            self.assertEqual(mr.target_branch, target_branch)
            mr_commits = mr.get_commits()
            self.assertEqual(len(mr_commits), 1)
            self.assertEqual(mr_commits[0]["id"], commit.hexsha)
            return mr

        # Get the merge requests corresponding to the commits.
        for commit in commits:
            source_branch = utils.get_remote_branch_name(
                self._target_branch, utils.get_change_id(commit.message)
            )
            self._mrs.append(
                merge_request.get_merge_request(self._remote, source_branch)
            )

        for idx, (mr, commit) in enumerate(zip(self._mrs, commits)):
            validate_mr(
                mr,
                commit,
                (
                    self._target_branch
                    if idx == 0
                    else self._mrs[idx - 1].source_branch
                ),
            )
            # Approve the MR so that we can test main.merge_merge_requests()
            mr.approve()
            # main.merge_merge_requests() needs all MRs to be mergeable.
            mr._wait_until_mergeable()

    def test_create_single_mr(self):
        # Create an MR.
        commit = self._create_commit("new_file.txt", "Add a new file.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate([commit])
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 1
        )

    def test_create_multiple_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate(commits)
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 3
        )

    def test_update_single_mr(self):
        # Create an MR.
        commit = self._create_commit("new_file.txt", "Add a new file.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        # Update the MR.
        amended_commit = self._amend_commits([commit])[0]
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate([amended_commit])
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 1
        )

    def test_update_multiple_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        # Update the MRs.
        amended_commits = self._amend_commits(commits)
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate(amended_commits)
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 3
        )

    def test_update_some_mrs(self):
        # Create three MRs.
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        # Update the MRs.
        amended_commits = self._amend_commits(commits[-2:])
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate([commits[0]] + amended_commits)
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 3
        )

    def test_insert_new_mr(self):
        # Create three MRs.
        commit0 = self._create_commit("new_file0.txt", "Add a new file0.")
        commit1 = self._create_commit("new_file1.txt", "Add a new file1.")
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        # Insert a new MR after the first MR.
        self._test_repo.head.reset("HEAD~1", index=True, working_tree=True)
        inserted_commit = self._create_commit(
            "inserted.txt", "Add a inserted MR."
        )
        # Rebase commit1.
        new_file_path = os.path.join(
            self._test_repo.working_tree_dir, "new_file1.txt"
        )
        open(new_file_path, "wb").close()
        self._test_repo.index.add([new_file_path])
        # We need to restore the Change ID in the new commit.
        self._test_repo.git.commit(message=commit1.message, no_verify=True)
        rebased_commit1 = self._test_repo.head.commit
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate([commit0, inserted_commit, rebased_commit1])
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 3
        )

    def test_merge_mrs(self):
        # Create a chain of 3 MRs
        commits = []
        commits.append(self._create_commit("new_file0.txt", "Add a new file0."))
        commits.append(self._create_commit("new_file1.txt", "Add a new file1."))
        commits.append(self._create_commit("new_file2.txt", "Add a new file2."))
        main.create_merge_requests(
            self._test_repo, self._remote, self._target_branch
        )
        self._validate(commits)
        # Drop the new_file2.txt commit locally.
        self._test_repo.head.reset("HEAD~1", working_tree=True)
        # merge_merge_requests should only merge the two MRs corresponding
        # to the two remaining local commits.
        assert (
            main.merge_merge_requests(
                self._test_repo, self._remote, self._target_branch
            )
            == 2
        )


if __name__ == "__main__":
    unittest.main()
