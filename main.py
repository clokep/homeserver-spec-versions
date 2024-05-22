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
    # The file paths (relative to repo root) to check for spec version information.
    #
    # Leave empty if no spec versions were ever implemented.
    spec_version_paths: list[str]
    # Some homeservers store room version info in a different repo.
    #
    # Defaults to the project repo.
    room_version_repo: str | None
    # The file paths (relative to room version or project root) to check for room
    # version information.
    #
    # Leave empty if no room versions were ever implemented.
    room_version_paths: list[str]
    # The pattern to use to fetch room versions.
    #
    # This should have 0 or 1 single capturing group.
    room_version_pattern: str
    # The file paths (relative to repo root) to check for default
    # room version information.
    #
    # Leave empty if no room versions were ever implemented.
    default_room_version_paths: list[str]
    # The pattern to use to fetch the default room version.
    #
    # This should have 0 or 1 single capturing group.
    default_room_version_pattern: str
    # The earliest commit to consider.
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
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "conduit": AdditionalMetadata(
        "next",
        spec_version_paths=[
            "src/client_server.rs",
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        room_version_repo=None,
        room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/service/globals/mod.rs",
        ],
        room_version_pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)',
        default_room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/config/mod.rs",
        ],
        default_room_version_pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$',
        earliest_commit=None,
        earliest_tag=None,
    ),
    "conduwuit": AdditionalMetadata(
        branch="main",
        spec_version_paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        room_version_repo=None,
        room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/service/globals/mod.rs",
        ],
        room_version_pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)',
        default_room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/config/mod.rs",
        ],
        default_room_version_pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$',
        earliest_commit="9c3b3daafcbc95647b5641a6edc975e2ffc04b04",
        earliest_tag=None,
    ),
    "construct": AdditionalMetadata(
        "master",
        spec_version_paths=["ircd/json.cc", "modules/client/versions.cc"],
        room_version_repo=None,
        room_version_paths=["modules/client/capabilities.cc"],
        room_version_pattern=r'"(\d+)"',
        default_room_version_paths=[
            "modules/m_room_create.cc",
            "modules/client/createroom.cc",
            "matrix/room_create.cc",
        ],
        default_room_version_pattern=r'(?:"default",|"room_version", json::value {) +"(\d+)',
        earliest_commit=None,
        # Earlier tags from charybdis exist.
        earliest_tag="0.0.10020",
    ),
    "dendrite": AdditionalMetadata(
        "main",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        room_version_repo="https://github.com/matrix-org/gomatrixserverlib",
        room_version_paths=["eventversion.go"],
        room_version_pattern=r"RoomVersionV(\d+)",
        default_room_version_paths=[
            "roomserver/version/version.go",
            "setup/config/config_roomserver.go",
        ],
        default_room_version_pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "jsynapse": AdditionalMetadata(
        "master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "ligase": AdditionalMetadata(
        "develop",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "proxy/routing/routing.go",
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit="bde8bc21a45a9dcffaaa812aa6a5a5341bca5f42",
        earliest_tag=None,
    ),
    "maelstrom": AdditionalMetadata(
        "master",
        spec_version_paths=["src/server/handlers/admin.rs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "matrex": AdditionalMetadata(
        "master",
        spec_version_paths=[
            "web/controllers/client_versions_controller.ex",
            "controllers/client/versions.ex",
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "mxhsd": AdditionalMetadata(
        "master",
        spec_version_paths=[
            "src/main/java/io/kamax/mxhsd/spring/client/controller/VersionController.java"
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "synapse": AdditionalMetadata(
        "develop",
        spec_version_paths=["synapse/rest/client/versions.py"],
        room_version_repo=None,
        room_version_paths=["synapse/api/constants.py", "synapse/api/room_versions.py"],
        room_version_pattern=r"RoomVersions.V(\d+)",
        default_room_version_paths=[
            "synapse/api/constants.py",
            "synapse/api/room_versions.py",
            "synapse/config/server.py",
        ],
        # Either the constant or fetching the default_room_version from the config.
        default_room_version_pattern=r'(?:DEFAULT_ROOM_VERSION = RoomVersions.V|DEFAULT_ROOM_VERSION = "|"default_room_version", ")(\d+)',
        earliest_commit=None,
        # Earlier tags exist from DINSIC.
        earliest_tag="v0.0.0",
    ),
    "transform": AdditionalMetadata(
        "master",
        spec_version_paths=["config.json"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "telodendria": AdditionalMetadata(
        "master",
        spec_version_paths=["src/Routes/RouteMatrix.c", "src/Routes/RouteVersions.c"],
        room_version_repo=None,
        room_version_paths=["src/Routes/RouteCapabilities.c"],
        room_version_pattern=r'roomVersions, "(\d+)"',
        default_room_version_paths=["src/Routes/RouteCapabilities.c"],
        default_room_version_pattern=r'JsonValueString\("(\d+)"\), 2, "m.room_versions", "default"',
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
        spec_version_paths=[
            "src/main/java/io/kamax/grid/gridepo/http/handler/matrix/VersionsHandler.java",
            "src/main/java/io/kamax/grid/gridepo/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
            "src/main/java/io/kamax/gridify/server/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
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
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
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
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
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


def get_versions_from_file(
    root: str, paths: list[str], pattern: str, to_ignore: list[str]
) -> set[str]:
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
            pattern,
            *paths,
        ],
        capture_output=True,
        cwd=root,
    )

    versions = set()

    for line in result.stdout.decode("ascii").splitlines():
        # Strip comments.
        #
        # TODO This only handles line comments, not block comments.
        line = re.split(r"#|//", line)[0]

        # Search again for the versions.
        matches = re.findall(pattern, line)
        matches = [
            next(m for m in match if m) if isinstance(match, tuple) else match
            for match in matches
        ]
        versions.update(matches)

    # Ignore some versions that are "bad".
    for v in to_ignore:
        versions.discard(v)

    return versions


def get_repo(name: str, remote: str) -> Repo:
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

    return repo


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


def get_project_versions(
    project: ProjectMetadata,
    repo: Repo,
    paths: list[str],
    pattern: str,
    to_ignore: list[str],
) -> dict[str, list[VersionInfo]]:
    """
    Calculate the supported versions for a project and metadata about when support
    was added/removed.

    Returns a map of version to a list of metadata. The metadata contains the
    first supported date/commit and the last supported date/commit (if any).

    Each version may have more than one set of supported/removed versions.
    """

    # List of commits with their version info.
    versions_at_commit = []

    # If no paths are given, then no versions were ever supported.
    if paths:
        # Calculate the set of versions each time these files were changed.
        for commit in repo.iter_commits(
            f"{project.earliest_commit}~..origin/{project.branch}"
            if project.earliest_commit
            else f"origin/{project.branch}",
            paths=paths,
            reverse=True,
            # Follow the development branch through merges (i.e. use dates that
            # changes are merged instead of original commit date).
            first_parent=True,
        ):
            # Checkout this commit (why is this so hard?).
            repo.head.reference = commit
            repo.head.reset(index=True, working_tree=True)

            # Commits are ordered earliest to latest, only record if the
            # version info changed.
            cur_versions = get_versions_from_file(
                repo.working_dir, paths, pattern, to_ignore
            )
            if (
                not versions_at_commit
                or versions_at_commit[-1].versions != cur_versions
            ):
                versions_at_commit.append(
                    CommitVersionInfo(
                        commit.hexsha, commit.authored_datetime, cur_versions
                    )
                )

    # Map of version to list of commit metadata for when support for that version changed.
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

    return versions


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
    repo = get_repo(project.name.lower(), project.repository)

    repo.head.reference = project.branch
    repo.head.reset(index=True, working_tree=True)

    # Map of spec version to list of commit metadata for when support for that version changed.
    versions = get_project_versions(
        project,
        repo,
        project.spec_version_paths,
        r"[vr]\d[\d\.]+\d",
        to_ignore=[
            # Dendrite declares a v1.0, which never existed.
            "v1.0",
            # Construct declares a r2.0.0, which never existed.
            "r2.0.0",
        ],
    )
    print(f"Loaded {project.name} spec versions: {versions}")

    if project.room_version_repo:
        room_version_repo = get_repo(
            project.room_version_repo.split("/")[-1], project.room_version_repo
        )
    else:
        room_version_repo = repo

    # Map of room version to list of commit metadata for when support for that version changed.
    room_versions = get_project_versions(
        project,
        room_version_repo,
        project.room_version_paths,
        project.room_version_pattern,
        to_ignore=[],
    )
    print(f"Loaded {project.name} room versions: {room_versions}")

    # Map of default room version to list of commit metadata for when support for that version changed.
    default_room_versions = get_project_versions(
        project,
        repo,
        project.default_room_version_paths,
        project.default_room_version_pattern,
        to_ignore=[],
    )
    print(f"Loaded {project.name} default room versions: {default_room_versions}")
    # TODO Validate there's no overlap of default room versions?

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
        "spec_version_dates": {
            v: [(info.start_date, info.end_date) for info in version_info]
            for v, version_info in versions.items()
        },
        "room_version_dates": {
            v: [(info.start_date, info.end_date) for info in version_info]
            for v, version_info in room_versions.items()
        },
        "default_room_version_dates": {
            v: [(info.start_date, info.end_date) for info in version_info]
            for v, version_info in default_room_versions.items()
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
    spec_repo = get_repo("matrix-spec", "https://github.com/matrix-org/matrix-spec.git")

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
        # TODO Calculate this from the spec repo.
        "room_versions": [str(v) for v in range(1, 11 + 1)],
        "homeserver_versions": {},
    }

    # For each project find the earliest known date the project supported it.
    for project in load_projects():
        result["homeserver_versions"][project.name.lower()] = main(
            project, spec_versions
        )

    with open("data.json", "w") as f:
        json.dump(result, f, default=json_encode, sort_keys=True, indent=4)
