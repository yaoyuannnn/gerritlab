"""
git_credentials
===============

Handle gathering and saving git credentials from git credential helpers.
"""

import subprocess

from typing import Dict, Optional, Union
from urllib.parse import urlsplit

INSTANCES: Dict[str, 'GitCredentialStore'] = {}


def instance(host: str) -> 'GitCredentialStore':
    """
    Builds single GitCredentialStore per host

    :host: is the full URL of the gitlab instance
    """
    return INSTANCES.setdefault(host, GitCredentialStore(host))


class GitCredentialStore:
    """
    A class to interact with git credential store.

    :host: is the full URL of the gitlab instance
    """
    def __init__(self, host: str) -> None:
        # TODO: use host + repo path to support per-repo tokens
        url = urlsplit(host)
        self._host = url.netloc
        self._scheme = url.scheme
        self._token: Optional[str] = None
        self._git_credentials: Dict[str, str] = {}
        self._git_credentials_fetched: bool = False

    def get_token(self) -> Union[str, None]:
        """
        Convenience method to get the token from the credential store.
        """
        return self.get("password")

    def get(self, key: str, default=None) -> Union[str, None]:
        """
        Return key from internal git credentials cache, or default if not found.
        """
        if not self._git_credentials_fetched:
            self._populate_git_credentials(self._call_git_credential_fill())
            self._git_credentials_fetched = True

        return self._git_credentials.get(key, default)

    def _populate_git_credentials(self, git_credentials_output: str) -> None:
        """
        Populate the internal git credentials cache
        """
        for line in git_credentials_output.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                self._git_credentials[key] = value

    def _call_git_credential_fill(self) -> str:
        """
        Look up credentials for the host using git credential fill.
        """
        try:
            git_credentials = subprocess.run(
                ["git", "credential", "fill"],
                input=f"protocol={self._scheme}\nhost={self._host}\n\n",
                text=True,
                stdout=subprocess.PIPE
            )
        except KeyboardInterrupt:
            return ""

        if git_credentials.returncode != 0:
            return ""

        # Store the credentials for later use
        self.git_credential_output = git_credentials.stdout

        return self.git_credential_output

    def save(self) -> None:
        """
        Save the token to the git credential store.
        """
        self._call_git_credential_approve(self.git_credential_output)

    @staticmethod
    def _call_git_credential_approve(git_credential_fill_out: str) -> int:
        """
        Attempt to save the credentials using git credential store.

        Some credential-helpers (pass-git-helper) do not support saving. The
        pattern seems to be to exit 0 without printing anything in that case.

        Some credential-helpers print a helpful message to stderr.

        Let's pass through the output to the user, but not treat as an error.
        """
        return subprocess.run(
            ["git", "credential", "approve"],
            input=git_credential_fill_out,
            text=True
        ).returncode
