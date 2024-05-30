import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import os.path
import subprocess

import git
from git import Repo

from projects import ProjectMetadata, load_projects


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
            [m for m in match if m] if isinstance(match, tuple) else match.split()
            for match in matches
        ]
        # Flatten the list of lists
        versions.update([m for ma in matches for m in ma])

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
    earliest_commit: str | None,
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
            f"{earliest_commit}~..origin/{project.branch}"
            if earliest_commit
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

    repo.head.reference = f"origin/{project.branch}"
    repo.head.reset(index=True, working_tree=True)

    # Map of spec version to list of commit metadata for when support for that version changed.
    versions = get_project_versions(
        project,
        project.earliest_commit,
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

    # If a different repo is used for room versions, check it out.
    if project.room_version_repo:
        room_version_repo = get_repo(
            project.room_version_repo.split("/")[-1], project.room_version_repo
        )
        earliest_room_version_commit = None
    else:
        room_version_repo = repo
        earliest_room_version_commit = project.earliest_commit

    # Map of room version to list of commit metadata for when support for that version changed.
    room_versions = get_project_versions(
        project,
        earliest_room_version_commit,
        room_version_repo,
        project.room_version_paths,
        project.room_version_pattern,
        to_ignore=[],
    )
    print(f"Loaded {project.name} room versions: {room_versions}")

    # Map of default room version to list of commit metadata for when support for that version changed.
    default_room_versions = get_project_versions(
        project,
        project.earliest_commit,
        repo,
        project.default_room_version_paths,
        project.default_room_version_pattern,
        # Dendrite declared room version 2 as a default, but that was invalid.
        to_ignore=["2"],
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

    # Map of room version -> commit date.
    room_versions = {}
    ROOM_VERSION_PATHS = [
        "specification/rooms/",
        "content/rooms/",
        ":(exclude)content/rooms/fragments",
    ]
    ROOM_VERSION_FILE_PATTERN = re.compile(r".+/v(\d+)\.(?:md|rst)$")
    for commit in spec_repo.iter_commits(paths=ROOM_VERSION_PATHS, reverse=True):
        # Find the added files in the diff from the previous commit which match
        # the expected paths.
        # room_version_paths = [
        #     d.b_path
        #     for d in commit.parents[0].diff(commit, paths=ROOM_VERSION_PATHS)
        #     if d.change_type == "A" and ROOM_VERSION_FILE_PATTERN.match(d.b_path)
        # ]
        for diff in commit.parents[0].diff(commit, paths=ROOM_VERSION_PATHS):
            match = ROOM_VERSION_FILE_PATTERN.match(diff.b_path)
            if diff.change_type == "A" and match:
                room_version = match[1]
                if room_version not in room_versions:
                    room_versions[room_version] = commit.authored_datetime

    # Map of default room versions -> commit date.
    DEFAULT_ROOM_VERSION_PATHS = [
        "specification/index.rst",
        "content/_index.md",
        "content/rooms/_index.md",
    ]
    default_room_versions = {}
    for commit in spec_repo.iter_commits(
        "origin/main", paths=DEFAULT_ROOM_VERSION_PATHS, reverse=True
    ):
        # Checkout this commit (why is this so hard?).
        spec_repo.head.reference = commit
        spec_repo.head.reset(index=True, working_tree=True)

        cur_versions = get_versions_from_file(
            spec_repo.working_dir,
            DEFAULT_ROOM_VERSION_PATHS,
            r"Servers MUST have Room Version (\d+)|Servers SHOULD use (?:\*\*)?room version (\d+)(?:\*\*)?",
            [
                # Dendrite incorrectly set room version 2 as the default for a period.
                "2"
            ],
        )
        assert len(cur_versions) <= 1, "Found more than one default room version"
        if cur_versions:
            default_room_version = next(iter(cur_versions))
            if default_room_version not in default_room_versions:
                default_room_versions[default_room_version] = commit.authored_datetime

    # The final output data is an object:
    #
    # spec_versions:
    #   lag: days since previous spec version
    #   version_dates: a map of version number to release date
    #
    # room_versions: a map of room version -> commit date
    #
    # default_room_versions: a map of default room version -> commit date
    #
    # homeserver_versions: a map of project -> object with keys:
    #   default_room_version_dates: map of default room version to list of tuples of supported/unsupported dates
    #   room_version_dates: map of room version to list of tuples of supported/unsupported dates
    #   spec_version_dates: map of spec version to list of tuples of supported/unsupported dates
    #   lag_all: map of version # to days to support it
    #   lag_after_commit: map of version # to days to support it
    #   lag_after_release: map of version # to days to support it
    #   maturity: string of stable/beta/alpha/obsolete
    #   initial_release_date: date of project's first release
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
        "room_versions": room_versions,
        "default_room_versions": default_room_versions,
        "homeserver_versions": {},
    }

    # For each project find the earliest known date the project supported it.
    for project in load_projects():
        result["homeserver_versions"][project.name.lower()] = main(
            project, spec_versions
        )

    with open("data.json", "w") as f:
        json.dump(result, f, default=json_encode, sort_keys=True, indent=4)
