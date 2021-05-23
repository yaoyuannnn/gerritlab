import sys
import os
import re
import argparse
import configparser
import collections
import json
from git import Repo
import requests
import time

mr_url = None
pipeline_url = None
pipelines_url = None
headers = None
global_target_branch = "master"
remove_source_branch = False
change_id_re = r"Change-Id: (.+?)(\s|$)"
dry_run = False
username = None
email = None


class Bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class PipelineStatus:
    CREATED = "created"
    WAITING_FOR_RESOURCE = "waiting_for_resource"
    PREPARING = "preparing"
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELED = "canceled"
    SKIPPED = "skipped"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


def warn(msg):
    print(Bcolors.WARNING + "warning" + Bcolors.ENDC + ": {}".format(msg))


def load_gitreview_config(remote, root_dir):
    global mr_url
    global pipeline_url
    global pipelines_url
    global headers
    global global_target_branch
    global remove_source_branch
    config = configparser.ConfigParser()
    config.read(os.path.join(root_dir, ".gitreview"))
    configs = config[remote]
    host = configs["host"]
    project_id = configs["project_id"]
    private_token = configs["private_token"]
    # Optional configs.
    if "target_branch" in configs:
        global_target_branch = configs["target_branch"]
    if "remove_source_branch" in configs:
        remove_source_branch = configs.getboolean("remove_source_branch")
    mr_url = "{}/api/v4/projects/{}/merge_requests".format(host, project_id)
    pipeline_url = "{}/api/v4/projects/{}/pipeline".format(host, project_id)
    pipelines_url = "{}/api/v4/projects/{}/pipelines".format(host, project_id)
    headers = {"PRIVATE-TOKEN": private_token}


def get_msg_title_description(msg):
    title, desc = tuple(msg.split("\n", 1))
    desc = re.sub(change_id_re, "", desc)
    return title, desc


def get_change_id(msg, silent=False):
    m = re.search(change_id_re, msg)
    if m:
        return m.group(1)
    elif not silent:
        raise ValueError("Didn't find the Change-Id in the commit message!")
    else:
        return None


def get_remote_branch_name(local_branch, change_id):
    return "{}-{}".format(local_branch, change_id[1:5])


def is_remote_stale(commits, remote_commits):
    """Checks if remote becomes stale due to local changes."""
    shas = set([c.hexsha for c in commits])
    remote_shas = set([c.hexsha for c in remote_commits])
    return shas != remote_shas


def get_merge_request(branch):
    """Return a `MergeRequest` given branch name."""
    r = requests.get("{}?state=opened".format(mr_url), headers=headers)
    for mr in r.json():
        if mr["source_branch"] == branch:
            return MergeRequest(json_data=mr)
    return None


def get_all_merge_requests(branch):
    """Return all `MergeRequest`s created off of `branch`."""
    r = requests.get("{}?state=opened".format(mr_url), headers=headers)
    mrs = []
    for json_data in r.json():
        if json_data["source_branch"].startswith(
                branch) and json_data["author"]["name"] == username:
            mrs.append(MergeRequest(json_data=json_data))
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


def generate_pipeline_status_str(status):
    status_str = ""
    for i, s in enumerate(status):
        if i == 0:
            status_str += "?"
        else:
            status_str += "&"
        status_str += "status=" + s
    return status_str


def get_pipelines_by_sha(sha, status=None):
    """Returns a list of `Pipeline`s associated with the given `sha`."""
    status_str = generate_pipeline_status_str(status)
    r = requests.get(pipelines_url + status_str, headers=headers)
    pipelines = []
    for pipeline in r.json():
        if pipeline["sha"] == sha:
            pipelines.append(Pipeline(json_data=pipeline))
    return pipelines


def get_pipelines_by_change_id(change_id, repo, status=None):
    """Returns a list of `Pipeline`s associated with the given `change_id`."""
    status_str = generate_pipeline_status_str(status)
    r = requests.get(pipelines_url + status_str, headers=headers)
    pipelines = []
    for pipeline in r.json():
        try:
            remote_change_id = get_change_id(
                repo.git.log(pipeline["sha"], n=1), silent=True)
        except:
            continue
        if remote_change_id is not None and remote_change_id == change_id:
            pipelines.append(Pipeline(json_data=pipeline))
    return pipelines


class Pipeline:

    def __init__(self, json_data):
        for attr in json_data:
            setattr(self, "_{}".format(attr), json_data[attr])

    @property
    def sha(self):
        return self._sha

    @property
    def status(self):
        return self._status

    def create(self, ref):
        requests.post(
            "{}?ref={}".format(pipeline_url, self._ref), headers=headers)

    def retry(self):
        requests.post(
            "{}/{}/retry".format(pipelines_url, self._id), headers=headers)

    def cancel(self):
        requests.post(
            "{}/{}/cancel".format(pipelines_url, self._id), headers=headers)


class MergeRequest:

    def __init__(
            self, source_branch=None, target_branch=None, title=None,
            description=None, json_data=None):
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
            "remove_source_branch": remove_source_branch,
        }
        r = requests.post(mr_url, headers=headers, data=data)
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
            "{}/{}".format(mr_url, self._iid), headers=headers, data=data)
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
        data = r.json()
        self._iid = data["iid"]
        self._web_url = data["web_url"]

    def submit(self):
        if self._iid is None:
            raise ValueError("Must set iid before submittng an MR!")
        url = "{}/{}/merge".format(mr_url, self._iid)
        while True:
            r = requests.put(url, headers=headers)
            if r.status_code == requests.codes.ok:
                break
            else:
                time.sleep(2)

    def delete(self):
        if self._iid is None:
            raise ValueError("Must set iid before deleting an MR!")
        r = requests.delete("{}/{}".format(mr_url, self._iid), headers=headers)
        if r.status_code != requests.codes.ok:
            r.raise_for_status()


def submit_merge_requests(remote, local_branch):
    """Submits merge requests."""

    print("\nSubmitting merge requests:")

    # Get MRs created off of the given branch.
    mrs = get_all_merge_requests(local_branch)
    if len(mrs) == 0:
        print("No MRs found for this branch: {}".format(local_branch))
        return

    if global_target_branch not in [mr.target_branch for mr in mrs]:
        warn(
            "Not a single MR interested in merging into {}?".format(
                global_target_branch))
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
            "mergeable.".format(global_target_branch))
        return

    if not dry_run:
        # We must submit MRs from the oldest. And before submitting an MR, we
        # must change its target_branch to the main branch.
        for mr in mergeables:
            mr.update(target_branch=global_target_branch)
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
            if get_change_id(remote_commit.message) != get_change_id(
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
        change_id = get_change_id(commit.message)
        for pipeline in get_pipelines_by_change_id(
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
            "{}/{}..{}".format(remote.name, global_target_branch,
                               local_branch)))
    commits.reverse()
    Commit = collections.namedtuple(
        "Commit", ["commit", "source_branch", "target_branch"])
    commits_data = set()
    for idx, c in enumerate(commits):
        source_branch = get_remote_branch_name(
            local_branch, get_change_id(c.message))
        target_branch = global_target_branch if idx == 0 else get_remote_branch_name(
            local_branch, get_change_id(commits[idx - 1].message))
        commits_data.add(Commit(c, source_branch, target_branch))

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
    current_mrs = get_all_merge_requests(local_branch)
    current_mr_chain = get_merge_request_chain(current_mrs)

    # Update the existing MRs from the end of the MR dependency chain.
    if len(current_mr_chain) > 0:
        print("\nUpdated MRs:")
    updated_commits = set()
    for mr in reversed(current_mr_chain):
        for c in commits_data:
            if c.source_branch == mr.source_branch:
                # Update the target branch of this MR.
                title, desp = get_msg_title_description(c.commit.message)
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
                updated_commits.add(c)
                break

    # Create new MRs.
    commits_data -= updated_commits
    if len(commits_data) > 0:
        print("\nNew MRs:")
    for c in commits_data:
        # Push the commit to remote by creating a new branch.
        remote.push(
            refspec="{}:refs/heads/{}".format(c.commit.hexsha, c.source_branch),
            force=True)
        title, desp = get_msg_title_description(c.commit.message)
        mr = MergeRequest(
            source_branch=c.source_branch, target_branch=c.target_branch,
            title=title, description=desp)
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
    parser.add_argument(
        "--dry-run", "-d", action="store_true", default=False,
        help="Dry run the command.")
    args = parser.parse_args()

    repo = Repo(os.getcwd(), search_parent_directories=True)
    global username
    global email
    username = repo.config_reader().get_value("user", "name")
    email = repo.config_reader().get_value("user", "email")
    load_gitreview_config(args.remote, repo.git.rev_parse("--show-toplevel"))
    remote = repo.remote(name=args.remote)
    local_branch = args.local_branch
    if args.local_branch is None:
        if repo.head.is_detached:
            raise Exception(
                "HEAD is detached. Are you in the process of a rebase?")
        local_branch = repo.active_branch.name

    global dry_run
    dry_run = args.dry_run
    if dry_run:
        warn("Dry run mode.")

    # Submit the MRs if they become mergeable.
    if args.merge:
        submit_merge_requests(remote, local_branch)
        sys.exit(0)

    create_merge_requests(repo, remote, local_branch)
