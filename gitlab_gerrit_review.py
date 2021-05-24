import sys
import os
import argparse
import collections
import json
from git import Repo
import requests
import time

import utils
from utils import Bcolors, warn
import global_vars
import pipeline


def get_merge_request(remote, branch):
    """Return a `MergeRequest` given branch name."""
    r = requests.get(
        "{}?state=opened".format(global_vars.mr_url),
        headers=global_vars.headers)
    for mr in r.json():
        if mr["source_branch"] == branch:
            return MergeRequest(remote=remote, json_data=mr)
    return None


def get_all_merge_requests(remote, branch):
    """Return all `MergeRequest`s created off of `branch`."""
    r = requests.get(
        "{}?state=opened".format(global_vars.mr_url),
        headers=global_vars.headers)
    mrs = []
    for json_data in r.json():
        if json_data["source_branch"].startswith(
                branch) and json_data["author"]["name"] == global_vars.username:
            mrs.append(MergeRequest(remote=remote, json_data=json_data))
    return mrs


def get_merge_request_chain(mrs):
    """Returns the MR dependency chain."""
    if len(mrs) == 0:
        return []
    source_branches = set([mr.source_branch for mr in mrs])
    roots = []
    for mr in mrs:
        if mr.target_branch not in source_branches:
            roots.append(mr)
    mrs_dict = {mr.target_branch: mr for mr in mrs}

    def get_merge_request_chain_inner(mrs, root):
        mr_chain = [root]
        if root.source_branch not in mrs:
            return mr_chain
        else:
            next_mr = mrs[root.source_branch]
            mr_chain.extend(get_merge_request_chain_inner(mrs, next_mr))
            return mr_chain

    mr_chain = []
    for root in roots:
        mr_chain.extend(get_merge_request_chain_inner(mrs_dict, root))
    return mr_chain


class MergeRequest:

    def __init__(
            self, remote, source_branch=None, target_branch=None, title=None,
            description=None, json_data=None):
        self._remote = remote
        self._source_branch = source_branch
        self._target_branch = target_branch
        self._title = title
        self._description = description
        self._iid = None
        self._web_url = None
        self._mergeable = False

        if json_data is not None:
            for attr in json_data:
                setattr(self, "_{}".format(attr), json_data[attr])

        self._local_branch = self._source_branch.rsplit("-", 1)[0]

    @property
    def mergeable(self):
        return self._mergeable

    @property
    def source_branch(self):
        return self._source_branch

    @property
    def target_branch(self):
        return self._target_branch

    def print_info(self, verbose=False):
        print("* {} {}".format(self._web_url, self._title))
        if verbose:
            print(
                "    {} -> {}".format(self._source_branch, self._target_branch))

    def create(self):
        data = {
            "source_branch": self._source_branch,
            "target_branch": self._target_branch,
            "title": self._title,
            "description": self._description,
            "remove_source_branch": global_vars.remove_source_branch,
        }
        r = requests.post(
            global_vars.mr_url, headers=global_vars.headers, data=data)
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
        data = r.json()
        self._iid = data["iid"]
        self._web_url = data["web_url"]

    def update(
            self, source_branch=None, target_branch=None, title=None,
            description=None):
        if source_branch is not None:
            self._source_branch = source_branch
        if target_branch is not None:
            self._target_branch = target_branch
        if title is not None:
            self._title = title
        if description is not None:
            self._description = description
        data = {
            "source_branch": self._source_branch,
            "target_branch": self._target_branch,
            "title": self._title,
            "description": self._description,
        }
        r = requests.put(
            "{}/{}".format(global_vars.mr_url, self._iid),
            headers=global_vars.headers, data=data)
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
        data = r.json()
        self._iid = data["iid"]
        self._web_url = data["web_url"]

    def submit(self):
        if self._iid is None:
            raise ValueError("Must set iid before submittng an MR!")
        url = "{}/{}/merge".format(global_vars.mr_url, self._iid)
        while True:
            r = requests.put(url, headers=global_vars.headers)
            if r.status_code == requests.codes.ok:
                break
            else:
                time.sleep(2)

    def delete(self, delete_source_branch=False):
        if self._iid is None:
            raise ValueError("Must set iid before deleting an MR!")
        r = requests.delete(
            "{}/{}".format(global_vars.mr_url, self._iid),
            headers=global_vars.headers)
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
        if delete_source_branch:
            self._remote.push(refspec=(":{}".format(self._source_branch)))


def submit_merge_requests(remote, local_branch):
    """Submits merge requests."""

    print("\nSubmitting merge requests:")

    # Get MRs created off of the given branch.
    mrs = get_all_merge_requests(remote, local_branch)
    if len(mrs) == 0:
        print("No MRs found for this branch: {}".format(local_branch))
        return

    if global_vars.global_target_branch not in [mr.target_branch for mr in mrs]:
        warn(
            "Not a single MR interested in merging into {}?".format(
                global_vars.global_target_branch))
        return

    mr_chain = get_merge_request_chain(mrs)
    for mr in mr_chain:
        mr.print_info()
        print("    [mergeable]: {}".format(mr.mergeable))

    mergeables = []
    for mr in mr_chain:
        if mr.mergeable:
            mergeables.append(mr)
        else:
            break
    if len(mergeables) == 0:
        warn(
            "No MRs can be merged into {} as top of the MR chain is not "
            "mergeable.".format(global_vars.global_target_branch))
        return

    # We must submit MRs from the oldest. And before submitting an MR, we
    # must change its target_branch to the main branch.
    for mr in mergeables:
        mr.update(target_branch=global_vars.global_target_branch)
        #FIXME: Poll the merge req status and waiting until
        # merge_status is no longer "checking".
        mr.submit()

    print()
    print(Bcolors.OKGREEN + "SUCCESS" + Bcolors.ENDC)
    print()
    print("New Merged MRs:")
    for mr in mergeables:
        mr.print_info(verbose=True)
    print("To {}".format(remote.url))


def create_merge_requests(repo, remote, local_branch):
    """Creates new merge requests on remote."""

    def can_skip_ci(commit, remote_branch):
        """Finds out if this commit can skip the CI pipeline."""
        # Chek if the commit actually changes anything compared to the remote
        # that requries a new CI pipeline.
        if "{}/{}".format(remote.name,
                          remote_branch) in [r.name for r in remote.refs]:
            diff = list(
                repo.iter_commits(
                    "{}/{}..{}".format(
                        remote.name, remote_branch, commit.hexsha)))
            if not any(diff):
                return True

            remote_commit = list(
                repo.iter_commits(
                    rev="{}/{}".format(remote.name, remote_branch)))[0]
            if utils.get_change_id(
                    remote_commit.message) != utils.get_change_id(
                        commit.message):
                raise Exception(
                    "The local commit has a different Change-Id from the "
                    "one on the same branch in remote!")
            if not any(commit.diff(remote_commit)):
                # The commit's code doesn't have any diff against the remote
                # commit, meaning that other stuff such as the commit message
                # has been modified.
                return True
        return False

    def cancel_prev_pipelines(commit):
        """Cancels previous pipelinesa associated with the same Change-Id."""
        # Get the running pipelines.
        change_id = utils.get_change_id(commit.message)
        for pipeline in pipeline.get_pipelines_by_change_id(
                change_id=change_id, repo=repo,
                status=[PipelineStatus.RUNNING, PipelineStatus.PENDING]):
            # Don't cancel myself.
            if pipeline.sha == commit.hexsha:
                continue
            # Cancel this previous pipeline.
            pipeline.cancel()

    # Sync up remote branches.
    remote.fetch(prune=True)

    # Get the local commits that are ahead of the remote/target_branch.
    commits = list(
        repo.iter_commits(
            "{}/{}..{}".format(
                remote.name, global_vars.global_target_branch, local_branch)))
    commits.reverse()
    Commit = collections.namedtuple(
        "Commit", ["commit", "source_branch", "target_branch"])
    commits_data = []
    for idx, c in enumerate(commits):
        source_branch = utils.get_remote_branch_name(
            local_branch, utils.get_change_id(c.message))
        if idx == 0:
            target_branch = global_vars.global_target_branch
        else:
            target_branch = utils.get_remote_branch_name(
                local_branch, utils.get_change_id(commits[idx - 1].message))
        commits_data.append(Commit(c, source_branch, target_branch))

    # Before we update the existing the MRs or create new MRs, there are a few
    # important notes:
    #
    # 1) If an MR's source branch becomes a subset of its target branch, that
    #    is, commits in the source branch are all included in the target branch,
    #    the MR will be auto-merged as it becomes meaningless.
    # 2) Because of 1, we must be careful when updating the existing MRs. For
    #    example, there are 3 existing MRs mr0, mr1 and mr2, with their
    #    dependencies as master <= mr0 <= mr1 <= mr2. If we locally rebase the
    #    commits to be master <= mr2 <= mr0 <= mr1, pushing the new commits to
    #    each MR's source branch will end up auto-merging mr2, as mr'2 target
    #    branch mr1 now contains its commit. To avoid this, we must update an
    #    MR's target branch before pushing the new commit. Also, we must update
    #    MRs from the end of the existing MR dependency chain. In this example,
    #    we must update mr2's target branch first and then push the new commit.
    #    The same goes for mr0 and mr1.
    #
    # The following code updates/creates MRs with the above notes in mind.

    # Get existing MRs created off of the given branch.
    current_mrs = get_all_merge_requests(remote, local_branch)
    current_mr_chain = get_merge_request_chain(current_mrs)

    # Update the existing MRs from the end of the MR dependency chain.
    if len(current_mr_chain) > 0:
        print("\nUpdated MRs:")
    updated_commits = []
    for mr in reversed(current_mr_chain):
        for c in commits_data:
            if c.source_branch == mr.source_branch:
                # Update the target branch of this MR.
                title, desp = utils.get_msg_title_description(c.commit.message)
                mr.update(
                    source_branch=c.source_branch,
                    target_branch=c.target_branch, title=title,
                    description=desp)
                mr.print_info(verbose=True)
                # Push commits to this branch (i.e. source branch of the MR).
                cancel_prev_pipelines(c.commit)
                remote.push(
                    refspec="{}:refs/heads/{}".format(
                        c.commit.hexsha, c.source_branch), force=True)
                updated_commits.append(c)
                break

    # Create new MRs.
    commits_data = [c for c in commits_data if c not in updated_commits]
    if len(commits_data) > 0:
        print("\nNew MRs:")
    for c in commits_data:
        # Push the commit to remote by creating a new branch.
        remote.push(
            refspec="{}:refs/heads/{}".format(c.commit.hexsha, c.source_branch),
            force=True)
        title, desp = utils.get_msg_title_description(c.commit.message)
        mr = MergeRequest(
            remote=remote, source_branch=c.source_branch,
            target_branch=c.target_branch, title=title, description=desp)
        mr.create()
        mr.print_info(verbose=True)
    print()

    print("{}\n".format(Bcolors.OKGREEN + "SUCCESS" + Bcolors.ENDC))
    print("To {}".format(remote.url))


def main():
    parser = argparse.ArgumentParser(
        description="Commandline flags for using git-review.")
    parser.add_argument(
        "remote", type=str, nargs="?", default="origin",
        help="The remote to push the reviews.")
    parser.add_argument(
        "local_branch", type=str, nargs="?",
        help="The local branch to be reviewed.")
    parser.add_argument(
        "--merge", "-m", action="store_true", default=False,
        help="Merge the MRs if they are approved.")
    args = parser.parse_args()

    repo = Repo(os.getcwd(), search_parent_directories=True)
    load_config(args.remote, repo)
    remote = repo.remote(name=args.remote)
    local_branch = args.local_branch
    if args.local_branch is None:
        if repo.head.is_detached:
            raise Exception(
                "HEAD is detached. Are you in the process of a rebase?")
        local_branch = repo.active_branch.name

    # Submit the MRs if they become mergeable.
    if args.merge:
        submit_merge_requests(remote, local_branch)
        sys.exit(0)

    create_merge_requests(repo, remote, local_branch)
