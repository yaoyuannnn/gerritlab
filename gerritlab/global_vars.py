"""This file includes global variables."""

import os
import configparser
import re
import requests
import urllib

from git.config import GitConfigParser
from git.repo import Repo

from gerritlab import git_credentials

project_url = None
mr_url = None
pipeline_url = None
pipelines_url = None
branches_url = None
headers = None
global_target_branch = "master"
remove_source_branch = True
ci_mode = False
session = None
host_url = None


def load_config(remote, repo: Repo):
    global project_url
    global mr_url
    global pipeline_url
    global pipelines_url
    global branches_url
    global headers
    global global_target_branch
    global remove_source_branch
    global session
    global host_url

    root_dir = repo.working_tree_dir
    git_config = repo.config_reader()

    gitreview = configparser.ConfigParser()
    # Note, this does not raise an exception if the file is not found.
    gitreview.read(os.path.join(root_dir, ".gitreview"))
    if remote in gitreview:
        gitreview_config = gitreview[remote]
    else:
        gitreview_config = {}

    (host_url, quoted_project_path) = _parse_remote_url(
        repo.remotes[remote].url
    )
    host_url = gitreview_config.get("host", host_url)

    private_token = _get_private_token(host_url, git_config, gitreview_config)

    # Optional configs.
    if "target_branch" in gitreview_config:
        global_target_branch = gitreview_config["target_branch"]
    else:
        global_target_branch = _get_upstream_branch(repo)
        if not global_target_branch:
            # FIXME: We should allow the target branch to be specified on the
            # command line like git-review does.
            raise SystemExit(
                f"""
Could not determine the upstream target branch to push changes to.

To fix this, do one of the following things:

* Set the upstream branch of the local branch using a command like:
  git branch --set-upstream-to={remote}/<upstream-branch-name>

  Example:
     git branch --set-upstream-to={remote}/main

OR

* Set the default target branch in a section for the remote in .gitreview:

  [{remote}]
  target_branch=<upstream-branch-name>

  Example:
    [{remote}]
    target_branch=main
"""
            )

    if "remove_source_branch" in gitreview_config:
        remove_source_branch = gitreview_config.getboolean(
            "remove_source_branch"
        )

    project_url = "{}/api/v4/projects/{}".format(host_url, quoted_project_path)
    mr_url = "{}/api/v4/projects/{}/merge_requests".format(
        host_url, quoted_project_path
    )
    pipeline_url = "{}/api/v4/projects/{}/pipeline".format(
        host_url, quoted_project_path
    )
    pipelines_url = "{}/api/v4/projects/{}/pipelines".format(
        host_url, quoted_project_path
    )
    branches_url = "{}/api/v4/projects/{}/repository/branches".format(
        host_url, quoted_project_path
    )
    session = requests.session()
    session.headers.update({"PRIVATE-TOKEN": private_token})


def _parse_remote_url(url: str):
    """
    Parses the supplied `url` (expected to be a git remote url).

    Returns a tuple containing:
    0: The base URL of the GitLab host (e.g., "https://gitlab.com")
    1: The url-quoted path to the repo (e.g. "someuser%2Fsomerepo")
    """

    m = re.match(r"git@(.*):(.*)", url)
    if m:
        url = "https://" + m[1]
        path = m[2]
    elif re.match(r"^(?:https?|ssh)://.*", url):
        p = urllib.parse.urlparse(url)
        url = f"{p.scheme}://{p.hostname}"
        path = p.path[1:]
    else:
        return None

    m = re.match(r"(.*)\.git$", path)
    if m:
        path = m[1]
    return (url, urllib.parse.quote(path, safe=""))


def _get_private_token(
    host: str,
    git_config: GitConfigParser,
    gitreview_config: configparser.SectionProxy,
):
    """
    Get the private token from one of several sources in the following order of
    preference:

    1. The GITLAB_PRIVATE_TOKEN environment variable.
    2. git config
    3. git credential storage
    4. (DEPRECATED) The .gitreview file

    Kind of a messy function, but it hides this complexity from the
    `load_config` function.
    """
    if "GITLAB_PRIVATE_TOKEN" in os.environ:
        return os.environ["GITLAB_PRIVATE_TOKEN"]

    # Try to get the private token from git config.
    try:
        return git_config.get_value("gerritlab", "private-token")
    except (configparser.NoSectionError, configparser.NoOptionError):
        pass

    # Try to get the private token from git credentials.
    private_token = git_credentials.instance(host).get_token()
    if private_token is not None:
        return private_token

    # DEPRECATED: Try to get the private token from .gitreview file.
    if "private_token" in gitreview_config:
        raise RuntimeError(
            "Using private_token from .gitreview file is deprecated."
        )

    raise SystemExit(f"Unable to find private token for {host}")


def _get_upstream_branch(repo: Repo) -> "str|None":
    local_branch_name = repo.head.reference.name
    with repo.config_reader() as conf:
        section = f'branch "{local_branch_name}"'
        try:
            remote_ref = conf.get(section, "merge")
        except (configparser.NoSectionError, configparser.NoOptionError):
            return None
        m = re.match(r"refs/heads/(.*)$", remote_ref)
        if not m:
            raise Exception(
                f"Unexpected remote tracking branch format: {remote_ref}"
            )
        return m[1]
