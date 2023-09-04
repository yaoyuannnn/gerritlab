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
project implements a "git lab" command that greatly
simplifies the steps to create/update/merge MRs.

## Install the git "lab" subcommand
Clone this repo and install the package.

```console
$ git clone https://github.com/yaoyuannnn/gerritlab.git
$ cd gerritlab
$ pip install .
```

## Set up a .gitreview.

Before using this tool, you need to create a `.gitreview` file in the root
directory of your project.

It must contain:

* `host`: The base URL of the GitLab server.
* `project_id`: The ID of your project on your GitLab host.

It may optionally contain:

* `target_branch`: the target branch that you want the MRs to eventually merge into. By default, `target_branch` is `master`.
* `remove_source_branch`: Boolean value, indicating whether the source branch of an MR should be deleted once it's merged. By default, `remove_source_branch` is `True`.

Example `.gitreview`:

```ini
[origin]
host=https://gitlab.example.com
project_id=1234
target_branch=master
remove_source_branch=True
```

## Set up a private token.

GerritLab requires a GitLab private token with api access.

You have the option to store it either in:

1. `git config`
2. [git credential helper](https://git-scm.com/book/en/v2/Git-Tools-Credential-Storage)

### Option 1: Store in git config

To store in your git config:

```console
$ git config --global gerritlab.private-token "[your-private-token]"
# OR
$ git config --local gerritlab.private-token "[your-private-token]"
```

### Option 2: Use a git credential store

A more secure option is to use a **git credential store**.

If you've configured a `credential.helper` in git, then GerritLab will prompt
you for a username and token and attempt to store it in your credential helper.

This is all that's needed for helpers supporting the `store` action (e.g.,
osxkeychain, libsecret).

But if you're using a credential store which does NOT support the `store`
action (e.g., pass-git-helper), then you'll need to manually store your GitLab
token where GerritLab expects to find it.

GerritLab expects to find credentials stored as the `host` from your `.gitreview`.

For example, if your host is `gitlab.com`, GerritLab will look for your GitLab
username and token in your credential helper under
`https://gitlab.com/`.

Git credential helpers are available for nearly every operating system and
password store.

For more details, see:
* [git-scm's list of credential helpers](https://git-scm.com/doc/credential-helpers)
* Microsoft's [Git Credential Manager](https://github.com/git-ecosystem/git-credential-manager)

⚠️ **Note**: The [git credential store](https://git-scm.com/docs/git-credential-store) is not recommended because it stores passwords in plaintext.

## Install Change-Id commit-msg hook.
We need a commit-msg hook that will add a Change-Id to every commit. This
Change-Id will be used as the key to find if there's an existing MR in the
GitLab repo.  The following installs the commit-msg hook to your project.

```console
$ git lab --setup
```

Commits created/amended after installation of the hook will
automatically have a Change-Id added.  Commits created prior to the
installation of the hook will need to amended so that they'll get the
Change-Id added on.

## Create/Update MRs.

To create/update MRs, simply do:

```console
$ git lab
```

This will create/update an MR for each commit on the current branch that's
ahead of `origin/master` (if `master` is the `target_branch`).  Note that if
you want to create/update MRs in a remote other than the default `origin`, do
`git lab my-remote`.  If a commit finds an existing MR with the same
Change-Id in the GitLab repo, the MR will be updated with new commit. The
following shows an example that creates 3 new MRs.

```console
$ git lab origin

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
$ git lab -m
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
```

## Development
### Install the package in development mode
```console
$ pip install -e .
```

This will make a `git lab` command available which points to your
development checkout (assuming you have pip's local bin directory in
your PATH).

### Run the tests
Integration tests require a submodule at `unit_tests/gerritlab_tests`, with a
Gitlab upstream and a *personal* access token configured (project access tokens
cannot delete MRs).

Tests can then be triggered using `./unit_tests/merge_request_test.py` or just
`pytest`.
