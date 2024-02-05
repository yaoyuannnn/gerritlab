import shutil
import time
import os
import argparse
from contextlib import contextmanager
from typing import Optional
import git
from git.repo import Repo
from git.remote import Remote

from gerritlab import (
    utils,
    git_credentials,
    global_vars,
    merge_request,
    pipeline,
)
from gerritlab.utils import Bcolors, msg_with_color, print_with_color, warn


def merge_merge_requests(repo, remote, final_branch) -> int:
    """
    Using local commits on the current branch, locate corresponding merge
    requests in GitLab and merge them in the proper order.

    Returns the number of MRs that were merged (for use by tests).
    """

    print(f"\nMerging merge requests destined for {final_branch}:")

    mrs = []
    commits_data = get_commits_data(repo, remote, final_branch)
    for commit in commits_data:
        mr = commit.mr
        if not mr:
            print(
                "There is no MR open for local commit "
                f"{commit.commit.hexsha[:8]} {commit.commit.summary}"
            )
            return 0
        mrs.append(mr)

    mr_chain = merge_request.get_merge_request_chain(mrs)
    for mr in mr_chain:
        # GitLab does not recheck mergeability status when lists of MRs
        # are requested (as merge_request.get_all_merge_requests() does),
        # so ensure we have up-to-date information merge status information
        # by refreshing each MR individually.
        mr.refresh()
        mr.print_info()
        print("    [merge status]: {}".format(mr.merge_status))

    mergeables = []
    for mr in mr_chain:
        if mr.mergeable:
            mergeables.append(mr)
        else:
            break
    if len(mergeables) == 0:
        warn(
            "No MRs can be merged into {} as top of the MR chain is not "
            "mergeable.".format(final_branch)
        )
        return 0

    # We must merge MRs from the oldest. And before merging an MR, we
    # must change its target_branch to the final target branch.
    for mr in mergeables:
        mr.update(target_branch=final_branch)
        # FIXME: Poll the merge req status and waiting until
        # merge_status is no longer "checking".
        mr.merge()

    print_with_color("\nSUCCESS\n", Bcolors.OKGREEN)
    print("New Merged MRs:")
    for mr in mergeables:
        mr.print_info(verbose=True)
    print("To {}".format(remote.url))
    return len(mergeables)


def cancel_prev_pipelines(repo, commits):
    """
    Cancels previous pipelines associated with the same Change-Ids as
    those of `commits`.
    """
    # Get the running pipelines.
    pipelines = pipeline.get_pipelines_by_change_id(repo)

    for commit in commits:
        change_id = utils.get_change_id(commit.message)
        for p in pipelines.get(change_id, []):
            # Don't cancel myself.
            if p.sha == commit.hexsha:
                continue
            # Cancel this previous pipeline.
            p.cancel()


class Commit:
    def __init__(
        self,
        commit: git.Commit,
        source_branch,
        target_branch,
        mr: Optional[merge_request.MergeRequest] = None,
    ):
        self.commit = commit
        self.source_branch = source_branch
        self.target_branch = target_branch
        self.mr = mr


# key is timer name, value is seconds counted
timers = {}


@contextmanager
def timing(timer_name):
    start = time.time()
    try:
        yield
    finally:
        elapsed = time.time() - start
        timers[timer_name] = timers.get(timer_name, 0) + elapsed


def generate_augmented_mr_description(commits_data, commit):
    if len(commits_data) <= 1:
        # No augmentation if only pushing a single commit
        return utils.get_msg_title_description(commit.commit.message)

    target_branch = commits_data[0].target_branch

    extra = ["Related MRs:"]
    for c in reversed(commits_data):
        text = f"* !{c.mr._iid}"
        if c == commit:
            text += " (This MR)"
        extra.append(text)

    extra.append(f"* _{target_branch}_")

    title, desc = utils.get_msg_title_description(commit.commit.message)
    return (title, desc + "\n---\n" + "\n".join(extra) + "\n")


def get_commits_data(
    repo: Repo, remote: Remote, final_branch: str
) -> "list[Commit]":
    # Get the local commits that are ahead of the remote/target_branch.
    remote.fetch()
    commits = list(
        repo.iter_commits("{}/{}..".format(remote.name, final_branch))
    )
    if len(commits) == 0:
        raise SystemExit("No local commits ahead of remote target branch.")

    commits.reverse()
    commits_data = []
    for idx, c in enumerate(commits):
        source_branch = utils.get_remote_branch_name(
            final_branch, utils.get_change_id(c.message)
        )
        if idx == 0:
            target_branch = final_branch
        else:
            target_branch = utils.get_remote_branch_name(
                final_branch, utils.get_change_id(commits[idx - 1].message)
            )
        commits_data.append(Commit(c, source_branch, target_branch))

    # Get existing MRs destined for final_branch.
    with timing("get_mrs"):
        current_mrs_by_source_branch = {
            mr.source_branch: mr
            for mr in merge_request.get_all_merge_requests(remote, final_branch)
        }

    # Link commits with existing MRs
    for c in commits_data:
        mr = current_mrs_by_source_branch.get(c.source_branch)
        if mr:
            c.mr = mr

    return commits_data


def create_merge_requests(repo: Repo, remote, final_branch):
    """Creates new merge requests on remote."""

    commits_data = get_commits_data(repo, remote, final_branch)
    print_with_color(
        f"Commits to be reviewed, destined for {remote.name}/{final_branch}:",
        Bcolors.OKCYAN,
    )
    for data in reversed(commits_data):
        c = data.commit
        title, _ = utils.get_msg_title_description(c.message)
        status = data.mr._reference if data.mr else "new"
        print("* {} {} [{}]".format(c.hexsha[:8], title, status))
    if not global_vars.ci_mode:
        do_review_prompt = "Proceed? ({}/n) ".format(
            msg_with_color("[y]", Bcolors.OKCYAN)
        )
        do_review = input("\n{}".format(do_review_prompt))
        while do_review not in ["", "y", "yes", "n", "no"]:
            do_review = input("Unknown input. {}".format(do_review_prompt))
        if do_review.startswith("n"):
            return

    # Workflow:
    # 1) Create or update MRs.
    # 2) Single push with all branch updates.
    # This order works best with GitLab.  If the order is swapped GitLab
    # can become confused (xref
    # https://gitlab.com/gitlab-org/gitlab-foss/-/issues/368).

    new_mrs = []
    updated_mrs = []
    commits_to_pipeline_cancel = []

    # Create missing MRs
    for c in commits_data:
        if not c.mr:
            title, desp = utils.get_msg_title_description(c.commit.message)
            mr = merge_request.MergeRequest(
                remote=remote,
                source_branch=c.source_branch,
                target_branch=c.target_branch,
                title=title,
                description=desp,
            )
            c.mr = mr
            with timing("create_mrs"):
                mr.create()
            new_mrs.append(mr)

    # At this point we have one MR for each commit.
    # title/desc/target_branch may be out-of-date for preexisting MRs.
    # Augment the MR descriptions to include a list of related MRs.
    for c in commits_data:
        title, desc = generate_augmented_mr_description(commits_data, c)
        mr = c.mr

        mr.set_target_branch(c.target_branch)
        mr.set_title(title)
        mr.set_desc(desc)
        with timing("update_mrs"):
            if (mr.save() or mr._sha != c.commit.hexsha) and mr not in new_mrs:
                updated_mrs.append(mr)
                commits_to_pipeline_cancel.append(c.commit)

    # Push commits to Change-Id-named branches
    refs_to_push = [
        "{}:refs/heads/{}".format(c.commit.hexsha, c.source_branch)
        for c in commits_data
    ]
    with timing("push"):
        remote.push(refspec=refs_to_push, force=True)

    with timing("Cancelling previous pipelines"):
        cancel_prev_pipelines(repo, commits_to_pipeline_cancel)

    with timing("stabilize"):
        for c in commits_data:
            c.mr.wait_until_stable(c)

    if len(updated_mrs) == 0 and len(new_mrs) == 0:
        print()
        warn("No updated/new MRs.\n")
    else:
        print_with_color("\nSUCCESS\n", Bcolors.OKGREEN)
    if len(updated_mrs) > 0:
        print("Updated MRs:")
        for mr in updated_mrs:
            mr.print_info(verbose=True)
        print()
    if len(new_mrs) > 0:
        print("New MRs:")
        for mr in new_mrs:
            mr.print_info(verbose=True)
        print()
    print("To {}".format(remote.url))
    if os.getenv("GERRITLAB_TIMING"):
        print("Timers:")
        for timer_name, seconds in timers.items():
            print(f"{timer_name}: {seconds} seconds")


def ensure_commitmsg_hook(git_dir):
    commitmsg_hook_file = os.path.join(git_dir, "hooks", "commit-msg")

    if not os.path.exists(commitmsg_hook_file):
        source = os.path.join(os.path.dirname(__file__), "commit-msg")
        shutil.copy(source, commitmsg_hook_file)


def main():
    parser = argparse.ArgumentParser(
        description="Commandline flags for using git-review."
    )
    parser.add_argument(
        "remote",
        type=str,
        nargs="?",
        default="origin",
        help="The remote to push the reviews.",
    )
    parser.add_argument(
        "final_branch",
        type=str,
        nargs="?",
        help="The final branch that commits are intended to be merged into.",
    )
    parser.add_argument(
        "--merge",
        "-m",
        action="store_true",
        default=False,
        help="Merge the MRs corresponding to local commits, "
        "if they are mergeable.",
    )
    parser.add_argument(
        "--setup",
        "-s",
        action="store_true",
        default=False,
        help="Just run the repo setup commands but don't submit anything.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Do not prompt for confirmation.",
    )
    args = parser.parse_args()

    repo = Repo(os.getcwd(), search_parent_directories=True)
    ensure_commitmsg_hook(repo.git_dir)

    global_vars.load_config(args.remote, repo)

    if args.setup:
        return

    remote = repo.remote(name=args.remote)
    final_branch = args.final_branch or global_vars.global_target_branch
    if not final_branch:
        raise SystemExit(
            "final_branch was not supplied on the command line "
            "and target_branch is not set in .gitreview"
        )

    if args.yes:
        global_vars.ci_mode = True

    # Merge the MRs if they become mergeable.
    if args.merge:
        merge_merge_requests(repo, remote, final_branch)
    else:
        create_merge_requests(repo, remote, final_branch)

    # Since we made it this far, we can assume that if the user is using a
    # git credential helper, they want to store the credentials.
    if git_credentials.INSTANCES:
        git_credentials.instance(global_vars.host_url).save()
