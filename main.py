from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import os.path
import subprocess

import git
from git import Repo


@dataclass
class Project:
    name: str
    git_location: str
    branch: str
    paths: list[str]
    earliest_tag: str


# Constants.
PROJECTS = (
    Project(
        "Synapse",
        "https://github.com/element-hq/synapse.git",
        "develop",
        ["synapse/rest/client/versions.py"],
        "v0.0.0",
    ),
    Project(
        "Dendrite",
        "https://github.com/matrix-org/dendrite.git",
        "main",
        ["src/github.com/matrix-org/dendrite/clientapi/routing/routing.go", "clientapi/routing/routing.go"],
        "v0.1.0rc1",
    ),
    Project(
        "Conduit",
        "https://gitlab.com/famedly/conduit.git",
        "next",
        ["src/main.rs", "src/client_server/unversioned.rs", "src/api/client_server/unversioned.rs"],
        "v0.2.0",
    ),
    Project(
        "Construct",
        "https://github.com/matrix-construct/construct.git",
        "master",
        ["ircd/json.cc", "modules/client/versions.cc"],
        "0.0.10020",
    ),
)


def json_encode(o: object) -> str | bool | int | float | None | list | dict:
    if isinstance(o, datetime):
        return o.isoformat()


def get_versions_from_file(root: Path, paths: list[str]) -> set[str]:
    result = subprocess.run(
        ["grep", "--only-matching", "--no-filename", "-E", "(['\\\"]) ?[vr]\\d.+?\\1", *paths],
        capture_output=True,
        cwd=root,
    )

    versions = set()

    for line in result.stdout.decode("ascii").splitlines():
        # Remove the quotes.
        line = line[1:-1].strip()

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
            "lag":
                dict([(spec_dates[0][0], 0)] + [(y[0], (y[1] - x[1]).days) for x, y in zip(spec_dates[:-1], spec_dates[1:])]),
            "version_dates": spec_versions,
        },
        "homeserver_versions": {},
    }

    # For each project find the earliest known date the project supported it.
    for project in PROJECTS:
        project_dir, repo = get_repo(project.name.lower(), project.git_location)

        repo.head.reference = project.branch
        repo.head.reset(index=True, working_tree=True)

        # Map of version to first commit with that version.
        versions = {}

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
        release_date = get_tag_datetime(repo.tags[project.earliest_tag])

        # Remove any spec versions which existed before this project was released.
        version_dates_after_release = {
            version: version_date
            for version, version_date in versions_dates_all.items()
            if spec_versions[version] >= release_date
        }

        print(f"Loaded {project.name} dates: {version_dates_after_release}")

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
