# Gerrit Style Code Review for GitLab Projects.

The branch-based approach that GitLab merge request uses can slow things down
when you really want to create dependent MRs so they can be reviewed in
parallel. With great amount of manual effort and carefulness,  you can actually
achieve that by setting an MR's target branch to the one it's dependent on and
making sure before merging any MRs, you change their target branch back to
`master` (or any default main branch in your project). This becomes pretty
error-prone with more than 2 MRs, not to mention that you must merge the MRs
strictly following the dependency order (otherwise, branches can be
accidentally deleted where outstanding MRs still have dependencies).

Does this somehow remind you of the good things about Gerrit? Yeah, in Gerrit,
nothing stops you from creating dependent reviews, since every commit creates a
new review. To bring this Gerrit-style code review to GitLab repos, this
project creates a simple script that helps you grealy simplify the steps to
create/merge dependent MRs.

## Install git-review
Clone the repo and put the directoy to your PATH. Make sure it comes before any
existing `git-review` in PATH.

## Install Change-Id commit-msg hook.
We need a commit-msg hook that will add a Change-Id to every commit.  You can
install it by:

```console
$ cp commit-msg path-to-your-project/.git/hooks/commit-msg
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
main_branch=master
remove_source_branch=True
```

## Create MRs.

To create MRs, simply do:

```console
$ git review origin
```

This will create an MR for each commit on the current branch that's ahead of
origin/master. If a commit finds an existing MR with the same Change-Id in the
GitLab repo, the MR will be updated. The following shows an example that
creates 3 new MRs.

```console
$ git review origin

SUCCESS

New MRs:
* https://gitlab.example.com/arch/myproject/-/merge_requests/3719 tests: Add commit a.
    master -> master-2c77 (master)
* https://gitlab.example.com/arch/myproject/-/merge_requests/3720 tests: Add commit b.
    master -> master-857b (master-2c77)
* https://gitlab.example.com/arch/myproject/-/merge_requests/3721 tests: Add commit c.
    master -> master-79e5 (master-857b)
To ssh://git@gitlab.example.com:12051/arch/myproject.git
```

## Merge MRs.

For merging MRs, you use the same command with a `-m` flag to merge any
mergeable MRs created off of the current branch, which takes into account the
MR dependency chain.

```console
$ git review -m
Submitting merge requests:
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
