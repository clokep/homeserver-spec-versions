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
    # The earliest tag to consider.
    #
    # Note that earlier tags might exist in the repo due to forks or other reasons.
    earliest_tag: str | None


@dataclass
class ProjectMetadata(ServerMetadata, AdditionalMetadata):
    pass


# Projects to ignore.
INVALID_PROJECTS = {
    # Dendron is essentially a reverse proxy, not a homeserver.
    "dendron",
    # Bullettime has no real code.
    "bullettime",
}


# Constants.
ADDITIONAL_METADATA = {
    "synapse": AdditionalMetadata(
        "develop",
        ["synapse/rest/client/versions.py"],
        "v0.0.0",
    ),
    "dendrite": AdditionalMetadata(
        "main",
        [
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        "v0.1.0rc1",
    ),
    "conduit": AdditionalMetadata(
        "next",
        [
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        "v0.2.0",
    ),
    "construct": AdditionalMetadata(
        "master",
        ["ircd/json.cc", "modules/client/versions.cc"],
        "0.0.10020",
    ),
    "jsynapse": AdditionalMetadata("master", [], earliest_tag=None),
    "ligase": AdditionalMetadata(
        "develop",
        [
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "proxy/routing/routing.go",
        ],
        "4.8.12",
    ),
    "maelstrom": AdditionalMetadata(
        "master",
        ["src/server/handlers/admin.rs"],
        earliest_tag=None,
    ),
    "matrex": AdditionalMetadata(
        "master",
        [
            "web/controllers/client_versions_controller.ex",
            "controllers/client/versions.ex",
        ],
        earliest_tag=None,
    ),
    "mxhsd": AdditionalMetadata(
        "master",
        [
            "src/main/java/io/kamax/mxhsd/spring/client/controller/VersionController.java"
        ],
        earliest_tag=None,
    ),
    "transform": AdditionalMetadata("master", ["config.json"], earliest_tag=None),
    "telodendria": AdditionalMetadata(
        "master",
        ["src/Routes/RouteMatrix.c", "src/Routes/RouteVersions.c"],
        earliest_tag=None,
    ),
}

ADDITIONAL_PROJECTS = [
    ProjectMetadata(
        name="Conduwuit",
        description="",
        author="",
        maturity="Beta",
        language="Rust",
        licence="Apache-2.0",
        repository="https://github.com/girlbossceo/conduwuit",
        room="#conduwuit:puppygock.gay",
        branch="main",
        paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        earliest_tag="v0.3.0",
    )
]


def download_projects():
    """Download the servers.toml metadata file."""
    with open("servers.toml", "wb") as f:
        with urlopen(SERVER_METADATA_URL) as u:
            f.write(u.read())


def load_projects() -> Iterator[ProjectMetadata]:
    with open("servers.toml", "rb") as f:
        data = tomllib.load(f)

    for server in data["servers"]:
        server_name = server["name"].lower()

        if server_name in INVALID_PROJECTS:
            print(f"Ignoring {server_name}.")
            continue

        # jSynapse is missing the repository metadata.
        if server_name == "jsynapse":
            server["repository"] = "https://github.com/swarmcom/jSynapse"

        if server_name not in ADDITIONAL_METADATA:
            print(f"No metadata for {server_name}, skipping.")
            continue

        yield ProjectMetadata(**server, **asdict(ADDITIONAL_METADATA[server_name]))

    yield from ADDITIONAL_PROJECTS


def json_encode(o: object) -> str | bool | int | float | None | list | dict:
    if isinstance(o, datetime):
        return o.isoformat()


def get_versions_from_file(root: Path, paths: list[str]) -> set[str]:
    result = subprocess.run(
        [
            "grep",
            "--only-matching",
            "--no-filename",
            "-E",
            # This is equivalent to a command line of: "(\\\\?['\"]) ?[vr]\d\..+?\1"
            r"""(\\?['\\"]) ?[vr]\d\..+?\1""",
            *paths,
        ],
        capture_output=True,
        cwd=root,
    )

    versions = set()

    for line in result.stdout.decode("ascii").splitlines():
        # Remove the quotes and whitespace.
        line = line.strip("\\'\" ")

        # Construct used a space separated string at some point.
        versions.update(line.split())

    # Dendrite has a version in a comment which breaks things.
    versions.discard("v33333")
    # Dendrite declares a v1.0, which never existed.
    versions.discard("v1.0")
    # Construct declares a r2.0.0, which never existed.
    versions.discard("r2.0.0")

    return versions


def get_repo(name: str, remote: str) -> tuple[Path, Repo]:
    repo_dir = Path(".") / ".projects" / name.lower()
    if not os.path.isdir(repo_dir):
        repo = Repo.clone_from(remote, repo_dir)
    else:
        repo = Repo(repo_dir)
        # TODO Fetch

    return repo_dir, repo


def get_tag_datetime(tag: git.TagReference) -> datetime:
    if tag.tag is None:
        return tag.commit.authored_datetime
    return datetime.fromtimestamp(
        tag.tag.tagged_date,
        tz=timezone(offset=timedelta(seconds=-tag.tag.tagger_tz_offset)),
    )


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
    #   version_dates: map of version to release date
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
        project_dir, repo = get_repo(project.name.lower(), project.repository)

        repo.head.reference = project.branch
        repo.head.reset(index=True, working_tree=True)

        # Map of version to first commit with that version.
        versions = {}

        # If no paths are given, then no versions were ever supported.
        if project.paths:
            for commit in repo.iter_commits(project.branch, paths=project.paths):
                # Checkout this commit (why is this so hard?).
                repo.head.reference = commit
                repo.head.reset(index=True, working_tree=True)

                # Since commits are in order from newest to earliest, stomp over previous data.
                for version in get_versions_from_file(project_dir, project.paths):
                    versions[version] = commit.hexsha

        print(f"Loaded {project.name} versions: {versions}")

        # Resolve commits to date and the first tag with that commit.
        versions_dates_all = {}
        for version, commit_hash in versions.items():
            commit = repo.commit(commit_hash)
            versions_dates_all[version] = commit.authored_datetime

        print(f"Loaded {project.name} dates: {versions_dates_all}")

        # Get the earliest release of this project.
        if project.earliest_tag:
            release_date = get_tag_datetime(repo.tags[project.earliest_tag])

            # Remove any spec versions which existed before this project was released.
            version_dates_after_release = {
                version: version_date
                for version, version_date in versions_dates_all.items()
                if spec_versions[version] >= release_date
            }

            print(f"Loaded {project.name} dates: {version_dates_after_release}")
        else:
            release_date = None
            version_dates_after_release = {}

        print()

        result["homeserver_versions"][project.name.lower()] = {
            "initial_release_date": release_date,
            "version_dates": versions_dates_all,
            "lag_all": {
                v: (d - spec_versions[v]).days for v, d in versions_dates_all.items()
            },
            "lag_after_release": {
                v: (d - spec_versions[v]).days
                for v, d in version_dates_after_release.items()
            },
        }

    with open("data.json", "w") as f:
        json.dump(result, f, default=json_encode, sort_keys=True, indent=4)
