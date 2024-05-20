import re
import tomllib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import os.path
import subprocess
from typing import Iterator
from urllib.request import urlopen

import git
from git import Repo

SERVER_METADATA_URL = "https://raw.githubusercontent.com/matrix-org/matrix.org/main/content/ecosystem/servers/servers.toml"


@dataclass
class ServerMetadata:
    # From the TOML file.
    name: str
    description: str
    author: str
    maturity: str
    language: str
    licence: str
    repository: str
    room: str | None = None


@dataclass
class AdditionalMetadata:
    # The branch which has the latest commit.
    branch: str
    # The file paths (relative to repo root) to check for version information.
    #
    # Leave empty if no versions were ever implemented.
    paths: list[str]
    # The earliest commit to consider. IF not given, the initial commit of the
    # repo is used.
    #
    # Useful for forks where the project contains many old commits.
    earliest_commit: str | None
    # The earliest tag to consider. If not given, the earliest tag in the repo
    # is used.
    #
    # Note that earlier tags might exist in the repo due to forks or other reasons.
    earliest_tag: str | None


@dataclass
class ProjectMetadata(ServerMetadata, AdditionalMetadata):
    pass


@dataclass
class CommitVersionInfo:
    commit: str
    date: datetime
    versions: set[str]


@dataclass
class VersionInfo:
    first_commit: str
    start_date: datetime
    last_commit: str | None = None
    end_date: datetime | None = None


# Projects to ignore.
INVALID_PROJECTS = {
    # Dendron is essentially a reverse proxy, not a homeserver.
    "dendron",
}


# Constants.
ADDITIONAL_METADATA = {
    "bullettime": AdditionalMetadata(
        "master",
        [],
        earliest_commit=None,
        earliest_tag=None,
    ),
    "conduit": AdditionalMetadata(
        "next",
        [
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        earliest_commit=None,
        earliest_tag=None,
    ),
    "conduwuit": AdditionalMetadata(
        branch="main",
        paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        earliest_commit="9c3b3daafcbc95647b5641a6edc975e2ffc04b04",
        earliest_tag=None,
    ),
    "construct": AdditionalMetadata(
        "master",
        ["ircd/json.cc", "modules/client/versions.cc"],
        earliest_commit=None,
        # Earlier tags from charybdis exist.
        earliest_tag="0.0.10020",
    ),
    "dendrite": AdditionalMetadata(
        "main",
        [
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        earliest_commit=None,
        earliest_tag=None,
    ),
    "jsynapse": AdditionalMetadata(
        "master", [], earliest_commit=None, earliest_tag=None
    ),
    "ligase": AdditionalMetadata(
        "develop",
        [
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "proxy/routing/routing.go",
        ],
        earliest_commit="bde8bc21a45a9dcffaaa812aa6a5a5341bca5f42",
        earliest_tag=None,
    ),
    "maelstrom": AdditionalMetadata(
        "master",
        ["src/server/handlers/admin.rs"],
        earliest_commit=None,
        earliest_tag=None,
    ),
    "matrex": AdditionalMetadata(
        "master",
        [
            "web/controllers/client_versions_controller.ex",
            "controllers/client/versions.ex",
        ],
        earliest_commit=None,
        earliest_tag=None,
    ),
    "mxhsd": AdditionalMetadata(
        "master",
        [
            "src/main/java/io/kamax/mxhsd/spring/client/controller/VersionController.java"
        ],
        earliest_commit=None,
        earliest_tag=None,
    ),
    "synapse": AdditionalMetadata(
        "develop",
        ["synapse/rest/client/versions.py"],
        earliest_commit=None,
        # Earlier tags exist from DINSIC.
        earliest_tag="v0.0.0",
    ),
    "transform": AdditionalMetadata(
        "master", ["config.json"], earliest_commit=None, earliest_tag=None
    ),
    "telodendria": AdditionalMetadata(
        "master",
        ["src/Routes/RouteMatrix.c", "src/Routes/RouteVersions.c"],
        earliest_commit=None,
        earliest_tag=None,
    ),
}

ADDITIONAL_PROJECTS = [
    ProjectMetadata(
        name="Gridify Server",
        description="Corporate-level Unified communication server with support for several protocols: Matrix Home and Identity server and Grid Data Server",
        author="Kamax Sarl",
        maturity="Obsolete",
        language="Java",
        licence="AGPL-3.0-or-later",
        repository="https://gitlab.com/kamax-lu/software/gridify/server",
        room="#gridify-server:kamax.io",
        branch="master",
        paths=[
            "src/main/java/io/kamax/grid/gridepo/http/handler/matrix/VersionsHandler.java",
            "src/main/java/io/kamax/grid/gridepo/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
            "src/main/java/io/kamax/gridify/server/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
        ],
        earliest_commit=None,
        earliest_tag=None,
    ),
    # Note that ejabberd doesn't implement the Client-Server API, thus it doesn't declare
    # itself compatible with any particular versions.
    ProjectMetadata(
        name="ejabberd",
        description="Robust, Ubiquitous and Massively Scalable Messaging Platform (XMPP, MQTT, SIP Server)",
        author="ProcessOne",
        maturity="alpha",
        language="Erlang/OTP",
        licence="GPL-2.0-only",
        repository="https://github.com/processone/ejabberd",
        room=None,
        branch="master",
        paths=[],
        earliest_commit=None,
        earliest_tag=None,
    ),
    # Is polyjuice server meant to be a full homeserver?
    ProjectMetadata(
        name="Polyjuice Server",
        description="Helper functions for creating a Matrix server",
        author="Hubert Chathi",
        maturity="alpha",
        language="Elixir",
        licence="Apache-2.0",
        repository="https://gitlab.com/polyjuice/polyjuice_server",
        room=None,
        branch="develop",
        paths=[],
        earliest_commit=None,
        earliest_tag=None,
    ),
]


def download_projects():
    """Download the servers.toml metadata file."""
    with open("servers.toml", "wb") as f:
        with urlopen(SERVER_METADATA_URL) as u:
            f.write(u.read())


def load_projects() -> Iterator[ProjectMetadata]:
    """Load the projects from the servers.toml file and augment with additional info."""
    with open("servers.toml", "rb") as f:
        data = tomllib.load(f)

    for server in data["servers"]:
        server_name = server["name"].lower()

        if server_name in INVALID_PROJECTS:
            print(f"Ignoring {server_name}.")
            continue

        if server_name not in ADDITIONAL_METADATA:
            print(f"No metadata for {server_name}, skipping.")
            continue

        yield ProjectMetadata(**server, **asdict(ADDITIONAL_METADATA[server_name]))

    yield from ADDITIONAL_PROJECTS


def json_encode(o: object) -> str | bool | int | float | None | list | dict:
    """Support encoding datetimes in ISO 8601 format."""
    if isinstance(o, datetime):
        return o.isoformat()


def get_versions_from_file(root: Path, paths: list[str]) -> set[str]:
    """
    Fetch the spec versions from one or more files.

    To get the valid version numbers and to ignore ones that are in comments we use
    a two-pass system:

    1. Use grep to find lines that contain potential version numbers.
    2. Strip comments "off" those lines, then search again to see if they
       have version numbers.
    """
    result = subprocess.run(
        [
            "grep",
            "--no-filename",
            "-E",
            # This is equivalent to a command line of: "(\\\\?['\"]) ?[vr]\d\..+?\1"
            r"[vr]\d[\d\.]+\d",
            *paths,
        ],
        capture_output=True,
        cwd=root,
    )

    versions = set()

    for line in result.stdout.decode("ascii").splitlines():
        # Strip whitespace.
        line = line.strip()

        # Strip comments.
        #
        # TODO This only handles line comments, not block comments.
        line = re.split(r"#|//", line)[0]

        # Search again for the versions.
        versions.update(re.findall(r"[vr]\d[\d\.]+\d", line))

    # Dendrite declares a v1.0, which never existed.
    versions.discard("v1.0")
    # Construct declares a r2.0.0, which never existed.
    versions.discard("r2.0.0")

    return versions


def get_repo(name: str, remote: str) -> tuple[Path, Repo]:
    """
    Given a project name and the remote git URL, return a tuple of file path and git repo.

    This will either clone the project (if it doesn't exist) or fetch from the
    remote to update the repository.
    """
    repo_dir = Path(".") / ".projects" / name.lower()
    if not os.path.isdir(repo_dir):
        repo = Repo.clone_from(remote, repo_dir)
    else:
        repo = Repo(repo_dir)
        repo.remote().fetch()

    return repo_dir, repo


def calculate_lag(
    versions: dict[str, datetime], spec_versions: dict[str, datetime]
) -> dict[str, int]:
    """Caclulate the lag between supported versions and spec versions."""
    return {v: (d - spec_versions[v]).days for v, d in versions.items()}


def calculate_versions_after_date(
    initial_date: datetime | None,
    versions: dict[str, datetime],
    spec_versions: dict[str, datetime],
) -> dict[str, datetime]:
    """Calculate the supported versions for spec versions after a given date.s"""
    if initial_date:
        return {
            version: version_date
            for version, version_date in versions.items()
            if spec_versions[version] >= initial_date
        }
    else:
        return {}


def get_tag_datetime(tag: git.TagReference) -> datetime:
    """
    Generate a datetime from a tag.

    This prefers the tagged date, but falls back to the commit date.
    """
    if tag.tag is None:
        return tag.commit.authored_datetime
    return datetime.fromtimestamp(
        tag.tag.tagged_date,
        tz=timezone(offset=timedelta(seconds=-tag.tag.tagger_tz_offset)),
    )


def main(
    project: ProjectMetadata, spec_versions: dict[str, datetime]
) -> dict[str, object]:
    """
    Generate the project's version information.

    1. Update the project's repository.
    2. Crawl the files to find the commits when the supported versions change.
    3. Resolve the commits to dates.
    4. Calculate the lag and set of supported versions.

    """
    project_dir, repo = get_repo(project.name.lower(), project.repository)

    repo.head.reference = project.branch
    repo.head.reset(index=True, working_tree=True)

    # List of commits with their version info.
    versions_at_commit = []

    # If no paths are given, then no versions were ever supported.
    if project.paths:
        # Calculate the set of versions each time these files were changed.
        for commit in repo.iter_commits(
            f"{project.earliest_commit}~..origin/{project.branch}"
            if project.earliest_commit
            else f"origin/{project.branch}",
            paths=project.paths,
            reverse=True,
        ):
            # Checkout this commit (why is this so hard?).
            repo.head.reference = commit
            repo.head.reset(index=True, working_tree=True)

            # Commits are ordered earliest to latest, only record if the
            # version info changed.
            cur_versions = get_versions_from_file(project_dir, project.paths)
            if (
                not versions_at_commit
                or versions_at_commit[-1].versions != cur_versions
            ):
                versions_at_commit.append(
                    CommitVersionInfo(
                        commit.hexsha, commit.authored_datetime, cur_versions
                    )
                )

    # Map of version to list of commits when support for that version changed.
    versions = {}
    for commit_info in versions_at_commit:
        for version in commit_info.versions:
            # If this version has not been found before or was previously removed,
            # add a new entry.
            if version not in versions:
                versions[version] = [VersionInfo(commit_info.commit, commit_info.date)]
            elif versions[version][-1].last_commit:
                versions[version].append(
                    VersionInfo(commit_info.commit, commit_info.date)
                )

        # If any versions are no longer found on this commit, but are still
        # considered as supported, mark as unsupported.
        for version, version_info in versions.items():
            if version not in commit_info.versions and not version_info[-1].last_commit:
                version_info[-1].last_commit = commit_info.commit
                version_info[-1].end_date = commit_info.date

    print(f"Loaded {project.name} versions: {versions}")

    # Resolve commits to date for when each version was first supported.
    versions_dates_all = {
        version: version_info[0].start_date
        for version, version_info in versions.items()
    }

    print(f"Loaded {project.name} dates: {versions_dates_all}")

    # Get the earliest release of this project.
    if project.earliest_commit:
        earliest_commit = repo.commit(project.earliest_commit)
    else:
        earliest_commit = next(repo.iter_commits(reverse=True))
    initial_commit_date = earliest_commit.authored_datetime

    # Remove any spec versions which existed before this project was started.
    version_dates_after_commit = calculate_versions_after_date(
        initial_commit_date, versions_dates_all, spec_versions
    )

    # Get the earliest release of this project.
    if project.earliest_tag:
        release_date = get_tag_datetime(repo.tags[project.earliest_tag])
    elif repo.tags:
        earliest_tag = min(repo.tags, key=lambda t: get_tag_datetime(t))
        release_date = get_tag_datetime(earliest_tag)
    else:
        release_date = None

    # Remove any spec versions which existed before this project was released.
    version_dates_after_release = calculate_versions_after_date(
        release_date, versions_dates_all, spec_versions
    )

    print()

    return {
        "initial_release_date": release_date,
        "version_dates": {
            v: [(info.start_date, info.end_date) for info in version_info]
            for v, version_info in versions.items()
        },
        "lag_all": calculate_lag(versions_dates_all, spec_versions),
        "lag_after_commit": calculate_lag(version_dates_after_commit, spec_versions),
        "lag_after_release": calculate_lag(version_dates_after_release, spec_versions),
        "maturity": project.maturity.lower(),
    }


if __name__ == "__main__":
    # Download the metadata if it doesn't exist.
    if not os.path.isfile("servers.toml"):
        download_projects()

    # First get the known versions according to the spec repo.
    _, spec_repo = get_repo(
        "matrix-spec", "https://github.com/matrix-org/matrix-spec.git"
    )

    # Map of version -> commit date.
    spec_versions = {
        t.name.split("/")[-1]: get_tag_datetime(t)
        for t in spec_repo.tags
        if t.name.startswith("v")
        or t.name.startswith("r")
        or t.name.startswith("client_server/r")
        or t.name.startswith("client-server/r")
    }

    # The final output data is an object:
    #
    # spec_versions:
    #   lag: days since previous spec version
    #   version_dates: a map of version number to release date
    #
    # homeserver_versions: a map of project -> object with keys:
    #   version_dates: map of version to list of tuples of supported/unsupported dates
    #   lag_all: map of version # to days to support it
    #   lag_after_release: map of version # to days to support it
    spec_dates = sorted(spec_versions.items(), key=lambda v: v[1])
    result = {
        "spec_versions": {
            "lag": dict(
                [(spec_dates[0][0], 0)]
                + [
                    (y[0], (y[1] - x[1]).days)
                    for x, y in zip(spec_dates[:-1], spec_dates[1:])
                ]
            ),
            "version_dates": spec_versions,
        },
        "homeserver_versions": {},
    }

    # For each project find the earliest known date the project supported it.
    for project in load_projects():
        result["homeserver_versions"][project.name.lower()] = main(
            project, spec_versions
        )

    with open("data.json", "w") as f:
        json.dump(result, f, default=json_encode, sort_keys=True, indent=4)
