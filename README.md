# Gerrit Style Code Review for GitLab Projects.

The branch-based approach that GitLab merge request uses can slow things down
when you really want to create dependent MRs so they can be reviewed in
parallel. With great amount of manual effort and carefulness,  you can actually
achieve that by setting an MR's target branch to the one it's dependent on and
making sure before merging any MRs, you change their target branch back to
`master`. This becomes pretty error-prone with more than 2 MRs, not to mention
that you must merge the MRs strictly following the dependency order (otherwise,
branches can be accidentally deleted where outstanding MRs still have
dependencies).

Does this somehow remind you of some good things about Gerrit? Yeah, in Gerrit,
nothing stops you from creating dependent reviews, since every commit creates a
new review. To bring this Gerrit-style code review to GitLab repos, this
project creates a simple script that helps you create dependent MRs.

To use this, make sure you put the `git-review` script in PATH and follow these
steps:

## Install Change-Id commit-msg hook.
You can install it by:

```console
$ curl -Lo .git/hooks/commit-msg http://review.example.com/tools/hooks/commit-msg
```

## Set up a .gitreview.

Before using the script, you need to create a .gitreview file in the root
directory of your project. It needs to contain info like GitLab project ID and
a private token that can be used to access the GitLab repo. An example
`.gitreview` looks like the following:

```ini
[origin]
host=https://gitlab.example.com
project_id=1234
private_token=[your-private-token]
```

## Creating MRs.

```console
$ git review origin
```
This will create an MR for each commit on the current branch that's ahead of
origin master. The following shows an example that creates 5 new MRs.

```console
$ git review origin

SUCCESS.

5 MRs to ssh://git@gitlab.example.com:12051/test/test.git:
* onnx: Add graph inputs/outputs to the query list when running ORT. (https://gitlab.example.com/test/test/-/merge_requests/3442)
    [new branch] onnx-support -> onnx-support-05c7 (master)
* onnx: Add an option to return tensor values of the OnnxContext.  (https://gitlab.example.com/test/test/-/merge_requests/3443)
    [new branch] onnx-support -> onnx-support-b929 (onnx-support-05c7)
* onnx: Add subgraph inputs to the tensor query list. (https://gitlab.example.com/test/test/-/merge_requests/3444)
    [new branch] onnx-support -> onnx-support-9253 (onnx-support-b929)
* onnx: Add input dtypes to the subgraph if necessary. (https://gitlab.example.com/test/test/-/merge_requests/3445)
    [new branch] onnx-support -> onnx-support-87cc (onnx-support-9253)
* onnx: Add the control flow Loop operator. (https://gitlab.example.com/test/test/-/merge_requests/3446)
    [new branch] onnx-support -> onnx-support-9b4b (onnx-support-87cc)
```

## Accepting MRs.

```console
$ git review -m
Submitting merge requests:
* onnx: Add the control flow Loop operator.
    [mergeable]: True

SUCCESS.

1 MRs submitted at ssh://git@gitlab.example.com:12051/test/test.git:
* onnx: Add the control flow Loop operator. (https://gitlab.example.com/test/test/-/merge_requests/3446)
    [new branch] onnx-support -> onnx-support-9b4b (master)
```
