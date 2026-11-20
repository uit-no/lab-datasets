"""Settings, read from environment variables (and from a `.env` file in the working directory).

LABCAT_DATA                 path of the catalog data repo (default: ./data)
LABCAT_DATA_REMOTE          GitHub address of the data repo; if LABCAT_DATA is missing or empty
                            at startup, it is cloned from here
LABCAT_GIT_TOKEN            GitHub token for pulling and pushing the data repo (e.g. a
                            fine-grained token with read/write Contents access to that repo only);
                            if empty, git's own credentials are used
LABCAT_USER                 person id that all edits are attributed to when Slack login is off
                            (development; default: matthias)
LABCAT_SLACK_CLIENT_ID      Slack app credentials; when both are set, everyone must sign in
LABCAT_SLACK_CLIENT_SECRET  with Slack
LABCAT_SLACK_TEAM_ID        only members of this workspace may sign in (e.g. T01234567); if
                            empty, the workspace of the first sign-in is shown in the log
LABCAT_SECRET_KEY           signs the login cookie; set it so logins survive restarts
LABCAT_BASE_URL             public address, e.g. https://datasets.lab.uit.no (default: taken
                            from the request)
LABCAT_ADMINS               person ids with access to the admin page, comma-separated (e.g. matthias)
LABCAT_PULL_INTERVAL        seconds between automatic syncs with GitHub (default: 600; 0 = off)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


PRODUCTION_REQUIRED = (
    "LABCAT_DATA",
    "LABCAT_SLACK_CLIENT_ID",
    "LABCAT_SLACK_CLIENT_SECRET",
    "LABCAT_SLACK_TEAM_ID",
    "LABCAT_SECRET_KEY",
    "LABCAT_BASE_URL",
)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    user: str
    committer_name: str = "Lab catalog"
    committer_email: str = "catalog@lab.local"
    pull_interval: int = 600  # seconds; only used when the data repo has a remote; 0 = off
    slack_client_id: str | None = None
    slack_client_secret: str | None = None
    slack_team_id: str | None = None
    secret_key: str | None = None
    base_url: str | None = None
    admins: tuple[str, ...] = ()
    data_remote: str | None = None
    git_token: str | None = None

    @property
    def auth_enabled(self) -> bool:
        return bool(self.slack_client_id and self.slack_client_secret)


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines; blank lines and # comments are skipped, quotes are stripped."""
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip("'\"")
    return out


def _is_https_origin(value: str) -> bool:
    if not value.startswith("https://") or any(c.isspace() or ord(c) < 32 or c in "\\?#" for c in value):
        return False
    try:
        url = urlsplit(value)
        return bool(
            url.hostname and url.username is None and url.path in ("", "/")
            and (url.port is None or url.port > 0)
        )
    except ValueError:
        return False


def load_settings(*, production: bool = False) -> Settings:
    if production:
        env = dict(os.environ)
        missing = [key for key in PRODUCTION_REQUIRED if not env.get(key, "").strip()]
        if missing:
            raise SystemExit("Missing required production environment variables: " + ", ".join(missing))
        if not _is_https_origin(env["LABCAT_BASE_URL"]):
            raise SystemExit("LABCAT_BASE_URL must be an HTTPS origin, e.g. https://datasets.example.org")
    else:
        env = read_env_file(Path(".env")) | dict(os.environ)

    def get(key: str) -> str | None:
        return env.get(key) or None

    return Settings(
        data_dir=Path(get("LABCAT_DATA") or "data").resolve(),
        user=get("LABCAT_USER") or "matthias",
        slack_client_id=get("LABCAT_SLACK_CLIENT_ID"),
        slack_client_secret=get("LABCAT_SLACK_CLIENT_SECRET"),
        slack_team_id=get("LABCAT_SLACK_TEAM_ID"),
        secret_key=get("LABCAT_SECRET_KEY"),
        base_url=get("LABCAT_BASE_URL"),
        admins=tuple(x.strip() for x in (get("LABCAT_ADMINS") or "").split(",") if x.strip()),
        pull_interval=int(get("LABCAT_PULL_INTERVAL") or 600),
        data_remote=get("LABCAT_DATA_REMOTE"),
        git_token=get("LABCAT_GIT_TOKEN"),
    )
