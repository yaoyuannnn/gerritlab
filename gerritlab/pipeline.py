"""This file provides easy APIs to handle Gitlab pipelines."""

import requests

from gerritlab import utils, global_vars


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
            "{}?ref={}".format(global_var.pipeline_url, self._ref),
            headers=global_vars.headers)

    def retry(self):
        requests.post(
            "{}/{}/retry".format(global_vars.pipelines_url, self._id),
            headers=global_vars.headers)

    def cancel(self):
        requests.post(
            "{}/{}/cancel".format(global_vars.pipelines_url, self._id),
            headers=global_vars.headers)


def generate_pipeline_status_str(status):
    return "?status=" + "&status=".join(status)


def get_pipelines_by_sha(sha, status=None):
    """Returns a list of `Pipeline`s associated with the given `sha`."""
    status_str = generate_pipeline_status_str(status)
    r = requests.get(
        global_vars.pipelines_url + status_str, headers=global_vars.headers)
    pipelines = []
    for pipeline in r.json():
        if pipeline["sha"] == sha:
            pipelines.append(Pipeline(json_data=pipeline))
    return pipelines


def get_pipelines_by_change_id(change_id, repo, status=None):
    """Returns a list of `Pipeline`s associated with the given `change_id`."""
    status_str = generate_pipeline_status_str(status)
    r = requests.get(
        global_vars.pipelines_url + status_str, headers=global_vars.headers)
    pipelines = []
    for pipeline in r.json():
        try:
            remote_change_id = utils.get_change_id(
                repo.git.log(pipeline["sha"], n=1), silent=True)
        except:
            continue
        if remote_change_id is not None and remote_change_id == change_id:
            pipelines.append(Pipeline(json_data=pipeline))
    return pipelines
