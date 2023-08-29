import shutil
import sys
import time
import os
import argparse
from contextlib import contextmanager
from git.repo import Repo

from gerritlab import utils, global_vars, merge_request, pipeline
from gerritlab.utils import Bcolors, msg_with_color, print_with_color, warn
from gerritlab.pipeline import PipelineStatus


def merge_merge_requests(remote, local_branch):
    """Merges merge requests."""

    print("\nMerging merge requests:")

    # Get MRs created off of the given branch.
    mrs = merge_request.get_all_merge_requests(remote, local_branch)
    if len(mrs) == 0:
        print("No MRs found for this branch: {}".format(local_branch))
        return

    if global_vars.global_target_branch not in [mr.target_branch for mr in mrs]:
        warn(
            "Not a single MR interested in merging into {}?".format(
                global_vars.global_target_branch))
        return

    mr_chain = merge_request.get_merge_request_chain(mrs)
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

    # We must merge MRs from the oldest. And before merging an MR, we
    # must change its target_branch to the main branch.
    for mr in mergeables:
        mr.update(target_branch=global_vars.global_target_branch)
        #FIXME: Poll the merge req status and waiting until
        # merge_status is no longer "checking".
        mr.merge()

    print_with_color("\nSUCCESS\n", Bcolors.OKGREEN)
    print("New Merged MRs:")
    for mr in mergeables:
        mr.print_info(verbose=True)
    print("To {}".format(remote.url))

class Commit:
    def __init__(self, commit, source_branch, target_branch):
        self.commit = commit
        self.source_branch = source_branch
        self.target_branch = target_branch

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
    
def create_merge_requests(repo, remote, local_branch):
    """Creates new merge requests on remote."""

    def cancel_prev_pipelines(commit):
        """Cancels previous pipelines associated with the same Change-Id."""
        # Get the running pipelines.
        change_id = utils.get_change_id(commit.message)
        for p in pipeline.get_pipelines_by_change_id(
                change_id=change_id, repo=repo,
                status=[PipelineStatus.RUNNING]):
            # Don't cancel myself.
            if p.sha == commit.hexsha:
                continue
            # Cancel this previous pipeline.
            p.cancel()

    # Sync up remote branches.
    with timing("fetch"):
        remote.fetch(prune=True)

    # Get the local commits that are ahead of the remote/target_branch.
    commits = list(
        repo.iter_commits(
            "{}/{}..{}".format(
                remote.name, global_vars.global_target_branch, local_branch)))
    if len(commits) == 0:
        warn("No local commits ahead of remote target branch.")
        sys.exit(0)
    print_with_color("Commits to be reviewed:", Bcolors.OKCYAN)
    for c in commits:
        title, _ = utils.get_msg_title_description(c.message)
        print("* {} {}".format(c.hexsha[:8], title))
    if not global_vars.ci_mode:
        do_review_prompt = (
            "Proceed? ({}/n) ".format(msg_with_color("[y]", Bcolors.OKCYAN)))
        do_review = input("\n{}".format(do_review_prompt))
        while do_review not in ['', "y", "n"]:
            do_review = input("Unknown input. {}".format(do_review_prompt))
        if do_review == "n":
            return
    commits.reverse()
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

    # Workflow:
    # 1) Create or update MRs.
    # 2) Single push with all branch updates.
    # This order works best with GitLab.  If the order is swapped GitLab
    # can become confused (xref https://gitlab.com/gitlab-org/gitlab-foss/-/issues/368).

    # Get existing MRs created off of the given branch.
    with timing("get_mrs"):
        current_mrs_by_source_branch = {
            mr.source_branch: mr for mr in merge_request.get_all_merge_requests(
                remote, local_branch)
        }

    new_mrs = []
    updated_mrs = []
    
    for c in commits_data:
        title, desp = utils.get_msg_title_description(c.commit.message)
        
        mr = current_mrs_by_source_branch.get(c.source_branch)
        if mr:
            # Update the MR if needed
            if mr.needs_update(c):
                with timing("update_mrs"):
                    mr.update(
                        source_branch=c.source_branch,
                        target_branch=c.target_branch, title=title,
                        description=desp)
                with timing("Cancelling previous pipelines"):
                    cancel_prev_pipelines(c.commit)
                updated_mrs.append(mr)
        else:
            mr = merge_request.MergeRequest(
                remote=remote, source_branch=c.source_branch,
                target_branch=c.target_branch, title=title, description=desp)
            with timing("create_mrs"):
                mr.create()
            new_mrs.append(mr)
    
    refs_to_push = ["{}:refs/heads/{}".format(
        c.commit.hexsha, c.source_branch) for c in commits_data]
    with timing("push"):
        remote.push(refspec=refs_to_push, force=True)        

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
    parser.add_argument(
        "--setup", "-s", action="store_true", default=False,
        help="Just run the repo setup commands but don't submit anything.")
    parser.add_argument(
        "--yes", action="store_true", default=False,
        help="Do not prompt for confirmation.")
    args = parser.parse_args()

    repo = Repo(os.getcwd(), search_parent_directories=True)
    ensure_commitmsg_hook(repo.git_dir)
    
    global_vars.load_config(args.remote, repo)

    if args.setup:
        return

    remote = repo.remote(name=args.remote)
    local_branch = args.local_branch
    if args.local_branch is None:
        if repo.head.is_detached:
            raise Exception(
                "HEAD is detached. Are you in the process of a rebase?")
        local_branch = repo.active_branch.name

    if args.yes:
        global_vars.ci_mode = True

    # Merge the MRs if they become mergeable.
    if args.merge:
        merge_merge_requests(remote, local_branch)
        sys.exit(0)

    create_merge_requests(repo, remote, local_branch)
