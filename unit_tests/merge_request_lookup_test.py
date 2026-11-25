#!/usr/bin/env python

import os
import sys
import unittest
from unittest import mock

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from gerritlab import global_vars, main, merge_request  # noqa: E402

MR_URL = "https://gitlab.example.com/api/v4/projects/1/merge_requests"
FIRST_CHANGE_ID = "I" + "a" * 40
SECOND_CHANGE_ID = "I" + "b" * 40
FIRST_SOURCE_BRANCH = "main-" + FIRST_CHANGE_ID
SECOND_SOURCE_BRANCH = "main-" + SECOND_CHANGE_ID


def _mr_json(source_branch, iid):
    return {
        "source_branch": source_branch,
        "target_branch": "main",
        "iid": iid,
        "web_url": f"https://gitlab.example.com/mr/{iid}",
        "title": "Title",
        "description": "",
    }


class GetMergeRequestTest(unittest.TestCase):
    def _get_mr(self, response_json):
        session = mock.Mock()
        session.get.return_value.json.return_value = response_json
        with mock.patch.object(global_vars, "session", session):
            with mock.patch.object(global_vars, "mr_url", MR_URL):
                mr = merge_request.get_merge_request(
                    mock.Mock(), FIRST_SOURCE_BRANCH
                )
        return mr, session

    def test_searches_mrs_of_all_users(self):
        _, session = self._get_mr([])
        session.get.assert_called_once_with(
            MR_URL,
            params={
                "state": "opened",
                "scope": "all",
                "source_branch": FIRST_SOURCE_BRANCH,
            },
        )

    def test_returns_matching_mr(self):
        mr, _ = self._get_mr([_mr_json(FIRST_SOURCE_BRANCH, 834)])
        self.assertEqual(mr.source_branch, FIRST_SOURCE_BRANCH)
        self.assertEqual(mr._iid, 834)

    def test_ignores_other_source_branches(self):
        mr, _ = self._get_mr([_mr_json(SECOND_SOURCE_BRANCH, 835)])
        self.assertIsNone(mr)


class GetCommitsDataTest(unittest.TestCase):
    def test_links_each_commit_with_its_mr(self):
        first_commit = mock.Mock(
            message=f"First\n\nChange-Id: {FIRST_CHANGE_ID}"
        )
        second_commit = mock.Mock(
            message=f"Second\n\nChange-Id: {SECOND_CHANGE_ID}"
        )
        repo = mock.Mock()
        # iter_commits() returns the newest commit first.
        repo.iter_commits.return_value = [second_commit, first_commit]
        remote = mock.Mock()
        remote.name = "origin"
        mr_of_other_user = merge_request.MergeRequest(
            remote=remote, json_data=_mr_json(FIRST_SOURCE_BRANCH, 834)
        )
        mrs_by_source_branch = {FIRST_SOURCE_BRANCH: mr_of_other_user}

        def get_merge_request(remote, source_branch):
            return mrs_by_source_branch.get(source_branch)

        with mock.patch.object(
            merge_request, "get_merge_request", side_effect=get_merge_request
        ) as lookup:
            commits_data = main.get_commits_data(repo, remote, "main")

        self.assertEqual(
            lookup.call_args_list,
            [
                mock.call(remote, FIRST_SOURCE_BRANCH),
                mock.call(remote, SECOND_SOURCE_BRANCH),
            ],
        )
        self.assertIs(commits_data[0].mr, mr_of_other_user)
        self.assertEqual(commits_data[1].target_branch, FIRST_SOURCE_BRANCH)
        self.assertIsNone(commits_data[1].mr)
