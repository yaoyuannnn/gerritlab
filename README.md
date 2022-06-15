GerritLab: Gerrit-style Code Review for GitLab Projects.
========================================================

[![yaoyuannnn](https://circleci.com/gh/yaoyuannnn/gerritlab.svg?style=shield)](https://circleci.com/gh/yaoyuannnn/gerritlab)

The branch-based approach that GitLab merge request uses can slow things down
when you really want to create dependent MRs so they can be reviewed in
parallel. With great amount of manual effort and carefulness, you can actually
achieve that by setting an MR's target branch to the one it's dependent on and
making sure before merging any MRs, you change their target branch back to
`master` (or any default main branch in your project). This becomes pretty
error-prone with more than 2 MRs, not to mention that you must merge the MRs
strictly following the dependency order (otherwise, branches can be
accidentally deleted where outstanding MRs still have dependencies).

Does this somehow remind you of the good things about Gerrit? Yeah, in Gerrit,
nothing stops you from creating dependent reviews, since every commit creates a
new review. To bring this Gerrit-style code review to GitLab repos, this
project implements the same git command (i.e. git review) that greatly
simplifies the steps to create/update/merge MRs.

## Install git-review
Clone the repo and put the local directory to your PATH. Make sure it comes
before any existing `git-review` in PATH so when you do `git review`, the right
executable is picked up by Git.

## Install Change-Id commit-msg hook.
We need a commit-msg hook that will add a Change-Id to every commit. This
Change-Id will be used as the key to find if there's an existing MR in the
GitLab repo. The following installs the commit-msg hook to your project.

```console
$ cp commit-msg path-to-your-project/.git/hooks/commit-msg
```

## Set up a .gitreview.

Before using this tool, you need to create a .gitreview file in the root
directory of your project. It needs to contain info like GitLab project ID and
a private token that can be used to access the GitLab repo. Current optional
configuration flags include `target_branch` and `remove_source_branch`.
`target_branch` represents the target branch that you want the MRs to
eventually merge into. By default, `target_branch` is `master`.
`remove_source_branch` can be used to delete the source branch of an MR once
it's merged. By default, this is set to `True`.  The following shows an example
of `.gitreview`:

```ini
[origin]
host=https://gitlab.example.com
project_id=1234
private_token=[your-private-token]
target_branch=master
remove_source_branch=True
```


The `private_token` can alternatively also be stored in your Git config:

```console
$ git config --global gerritlab.private-token "[your-private-token]"
# OR
$ git config --local gerritlab.private-token "[your-private-token]"
```

## Create/Update MRs.

To create/update MRs, simply do:

```console
$ git review
```

This will create/update an MR for each commit on the current branch that's
ahead of `origin/master` (if `master` is the `target_branch`).  Note that if
you want to create/update MRs in a remote other than the default `origin`, do
`git review my-remote`.  If a commit finds an existing MR with the same
Change-Id in the GitLab repo, the MR will be updated with new commit. The
following shows an example that creates 3 new MRs.

```console
$ git review origin

SUCCESS

New MRs:
* https://gitlab.example.com/arch/myproject/-/merge_requests/3719 tests: Add commit a.
    master-2c77 -> master
* https://gitlab.example.com/arch/myproject/-/merge_requests/3720 tests: Add commit b.
    master-857b -> master-2c77
* https://gitlab.example.com/arch/myproject/-/merge_requests/3721 tests: Add commit c.
    master-79e5 -> master-857b
To ssh://git@gitlab.example.com:12051/arch/myproject.git
```

## Merge MRs.

For merging MRs, use the same git command with a `-m` or `--merge` flag to
merge any mergeable MRs created off of the current branch, which takes into
account the MR dependency chain.

```console
$ git review -m
Merging merge requests:
* https://gitlab.example.com/myproject/-/merge_requests/110 tests: Add commit a.
    [mergeable]: True
* https://gitlab.example.com/myproject/-/merge_requests/111 tests: Add commit b.
    [mergeable]: True
* https://gitlab.example.com/myproject/-/merge_requests/109 tests: Add commit c.
    [mergeable]: True

SUCCESS

New Merged MRs:
* https://gitlab-master.example.com/myproject/-/merge_requests/110 tests: Add commit a.
    master -> master-2c77 (master)
* https://gitlab-master.example.com/myproject/-/merge_requests/111 tests: Add commit b.
    master -> master-857b (master)
* https://gitlab-master.example.com/myproject/-/merge_requests/109 tests: Add commit c.
    master -> master-79e5 (master)
To ssh://git@gitlab.example.com:12051/myproject.git
