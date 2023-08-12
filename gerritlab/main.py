import shutil
import sys
import os
import argparse
import collections
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
        return False

    def cancel_prev_pipelines(commit):
        """Cancels previous pipelinesa associated with the same Change-Id."""
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
            do_review = input("Unkown input. {}".format(do_review_prompt))
        if do_review == "n":
            return
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
    current_mrs = merge_request.get_all_merge_requests(remote, local_branch)
    current_mr_chain = merge_request.get_merge_request_chain(current_mrs)

    # Update the existing MRs from the end of the MR dependency chain.
    updated_commits = []
    updated_mrs = []
    for mr in reversed(current_mr_chain):
        for c in commits_data:
            if c.source_branch == mr.source_branch:
                # Delay the update if the updated target branch doesn't exist,
                # meaning a new MR will be created off of that target branch.
                updated_target_branch_exists = "{}/{}".format(
                    remote.name,
                    c.target_branch) in [ref.name for ref in repo.references]
                if not updated_target_branch_exists:
                    continue
                # Do nothing if the commit doesn't contain any new changes.
                if can_skip_ci(c.commit, c.source_branch):
                    continue
                # Update the target branch of this MR.
                title, desp = utils.get_msg_title_description(c.commit.message)
                mr.update(
                    source_branch=c.source_branch,
                    target_branch=c.target_branch, title=title,
                    description=desp)
                cancel_prev_pipelines(c.commit)
                # Update the remote branch.
                remote.push(
                    refspec="{}:refs/heads/{}".format(
                        c.commit.hexsha, c.source_branch), force=True)
                updated_commits.append(c)
                updated_mrs.append(mr)
                break

    # Create new MRs.
    commits_data = [c for c in commits_data if c not in updated_commits]
    new_mrs = []
    for c in commits_data:
        title, desp = utils.get_msg_title_description(c.commit.message)
        mr = merge_request.get_merge_request(remote, c.source_branch)
        if mr is not None:
            # Do nothing if the commit doesn't contain any new changes.
            if can_skip_ci(c.commit, c.source_branch):
                continue
            cancel_prev_pipelines(c.commit)
            # Update the remote branch.
            remote.push(
                refspec="{}:refs/heads/{}".format(
                    c.commit.hexsha, c.source_branch), force=True)
            # Update the MR if it already exits.
            mr.update(
                source_branch=c.source_branch,
                target_branch=c.target_branch, title=title,
                description=desp)
            updated_mrs.append(mr)
        else:
            # Push the commit to remote by creating a new branch.
            remote.push(
                refspec="{}:refs/heads/{}".format(
                    c.commit.hexsha, c.source_branch), force=True)
            # Create new MRs.
            mr = merge_request.MergeRequest(
                remote=remote, source_branch=c.source_branch,
                target_branch=c.target_branch, title=title, description=desp)
            mr.create()
            new_mrs.append(mr)

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

    # Merge the MRs if they become mergeable.
    if args.merge:
        merge_merge_requests(remote, local_branch)
        sys.exit(0)

    create_merge_requests(repo, remote, local_branch)
