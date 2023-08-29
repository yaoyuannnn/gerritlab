"""This file provides easy APIs to handle Gitlab pipelines."""

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
    _ref: str
    _id: int
    _sha: str
    _status: PipelineStatus

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
        global_vars.session.post(
            "{}?ref={}".format(global_vars.pipeline_url, self._ref))

    def retry(self):
        global_vars.session.post(
            "{}/{}/retry".format(global_vars.pipelines_url, self._id))

    def cancel(self):
        global_vars.session.post(
            "{}/{}/cancel".format(global_vars.pipelines_url, self._id))


def generate_pipeline_status_str(status):
    return "?status=" + "&status=".join(status)


def get_pipelines(status):
    """
    Returns a list of `Pipeline`s associated with the project.

    Note: `status` must be a list of status strings.
    """
    status_str = generate_pipeline_status_str(status)
    r = global_vars.session.get(
        global_vars.pipelines_url + status_str)
    r.raise_for_status()
    return [Pipeline(json_data=pipeline) for pipeline in r.json()]


def get_pipelines_by_change_id(repo) -> dict:
    """
    Returns a dictionary of runnning `Pipeline`s associated with the project.

    The key of the dictionary is a Change-Id string and the value is a list of
    running `Pipeline`s associated with that Change-Id.
    """
    
    res = {}

    for pipeline in get_pipelines([PipelineStatus.RUNNING]):
        try:
            change_id = utils.get_change_id(
                repo.git.log(pipeline.sha, n=1), silent=True)
        except:
            continue
        if change_id:
            res.setdefault(change_id, []).append(pipeline)

    return res
