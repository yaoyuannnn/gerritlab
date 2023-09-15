"""This file includes global variables."""

import os
import configparser
import requests

from git.config import GitConfigParser

from gerritlab import git_credentials

mr_url = None
pipeline_url = None
pipelines_url = None
headers = None
global_target_branch = "master"
remove_source_branch = False
username = None
email = None
ci_mode = False
session = None
host = None


def load_config(remote, repo):
    global username
    global email
    global mr_url
    global pipeline_url
    global pipelines_url
    global headers
    global global_target_branch
    global remove_source_branch
    global session
    global host

    root_dir = repo.git.rev_parse("--show-toplevel")
    git_config = repo.config_reader()

    username = git_config.get_value("user", "name")
    email = git_config.get_value("user", "email")

    gitreview = configparser.ConfigParser()
    gitreview.read(os.path.join(root_dir, ".gitreview"))
    gitreview_config = gitreview[remote]

    host = gitreview_config["host"]
    project_id = gitreview_config["project_id"]

    private_token = _get_private_token(host, git_config, gitreview_config)

    # Optional configs.
    if "target_branch" in gitreview_config:
        global_target_branch = gitreview_config["target_branch"]
    if "remove_source_branch" in gitreview_config:
        remove_source_branch = gitreview_config.getboolean(
            "remove_source_branch"
        )
    mr_url = "{}/api/v4/projects/{}/merge_requests".format(host, project_id)
    pipeline_url = "{}/api/v4/projects/{}/pipeline".format(host, project_id)
    pipelines_url = "{}/api/v4/projects/{}/pipelines".format(host, project_id)
    session = requests.session()
    session.headers.update({"PRIVATE-TOKEN": private_token})


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
