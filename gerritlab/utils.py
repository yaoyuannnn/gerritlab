"""This includes utility functions."""

import re

change_id_re = r"Change-Id: (.+?)(\s|$)"


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


def msg_with_color(msg, color):
    """Wrap `msg` with the given `color`.

    Args:
        color: One `Bcolors`.
        msg: The message to print.

    Returns:
        A string representing `msg` with `color` applied.
    """
    if color not in Bcolors.__dict__.values():
        raise AttributeError("Must specify a valid color!")
    return "{}{}{}".format(color, msg, Bcolors.ENDC)


def print_with_color(msg, color):
    """Prints `msg` with the given `color`.

    Args:
        color: One `Bcolors`.
        msg: The message to print.
    """
    print(msg_with_color(msg, color))


def warn(msg):
    print(Bcolors.WARNING + "WARNING" + Bcolors.ENDC + ": {}".format(msg))


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
