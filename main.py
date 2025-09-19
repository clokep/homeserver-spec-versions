from dataclasses import dataclass, asdict, astuple
from datetime import datetime
import json

from finders import get_pattern_from_file
from projects import (
    ProjectMetadata,
    load_projects,
    ProjectData,
    MANUAL_PROJECTS,
    PatternFinder,
    SubRepoFinder,
)
from repository import Repository
from spec import get_spec_dates


@dataclass
class CommitVersionInfo:
    """Versions at a particular commit or tag."""

    # Commit or tag.
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


def resolve_versions_at_commit(
    versions_at_commit: list[CommitVersionInfo],
) -> dict[str, list[VersionInfo]]:
    """
    Convert a list of changing versions by commit/tag into a dictionary of version
    mapped to the commits/tags that changed it.
    """

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


def get_project_versions(
    project: ProjectMetadata,
    repo: Repository,
    finders: list[PatternFinder | SubRepoFinder] | None,
) -> tuple[dict[str, list[VersionInfo]], dict[str, list[VersionInfo]]]:
    """
    Calculate the supported versions for a project and metadata about when support
    was added/removed.

    Returns a map of version to a list of metadata. The metadata contains the
    first supported date/commit and the last supported date/commit (if any).

    Each version may have more than one set of supported/removed versions.
    """

    if not finders:
        return {}, {}

    # List of commits with their version info.
    versions_at_commit = []
    versions_at_tag = []

    commits = repo.get_modified_commits(project, finders)

    for commit in commits:
        repo.checkout(commit)

        cur_versions = set()
        for finder in finders:
            if isinstance(finder, PatternFinder):
                finder_versions = get_pattern_from_file(
                    repo.working_dir,
                    finder.paths,
                    finder.pattern,
                    finder.parser,
                    finder.to_ignore,
                )
            elif isinstance(finder, SubRepoFinder):
                finder_versions = repo.get_pattern_from_subrepo(finder)

            else:
                raise ValueError(f"Unsupported finder: {finder.__class__.__name__}")

            cur_versions.update(finder_versions)

        # Commits are ordered earliest to latest, only record if the
        # version info changed.
        hexsha, committed_datetime = repo.get_commit_info(commit)
        if not versions_at_commit or versions_at_commit[-1].versions != cur_versions:
            versions_at_commit.append(
                CommitVersionInfo(hexsha, committed_datetime, cur_versions)
            )

        # Resolve the commit to the *next* tag.
        tag = repo.get_tag_from_commit(hexsha)
        # If no tags were found than this wasn't released yet.
        if tag:
            if not versions_at_tag or versions_at_tag[-1].versions != cur_versions:
                versions_at_tag.append(
                    CommitVersionInfo(tag, repo.get_tag_datetime(tag), cur_versions)
                )

    # Map of each version to a list of commit metadata for when support for that version changed.
    versions = resolve_versions_at_commit(versions_at_commit)
    tags = resolve_versions_at_commit(versions_at_tag)

    return versions, tags


def version_info_to_dates(
    versions: dict[str, list[VersionInfo]],
) -> dict[str, list[tuple[str, datetime, str | None, datetime | None]]]:
    """Convert a map of version to list of version infos to version to list of tuples of dates."""
    return {
        v: [astuple(info) for info in version_info]
        for v, version_info in versions.items()
    }


def get_project_dates(
    project: ProjectMetadata, spec_versions: dict[str, datetime]
) -> ProjectData:
    """
    Generate the project's version information.

    1. Update the project's repository.
    2. Crawl the files to find the commits when the supported versions change.
    3. Resolve the commits to dates.
    4. Calculate the lag and set of supported versions.

    """
    repo = Repository.create(project.name.lower(), project.repository)

    # Map of spec version to list of commit metadata for when support for that version changed.
    versions, versions_by_tag = get_project_versions(
        project,
        repo,
        finders=[
            PatternFinder(
                paths=project.spec_version_paths,
                pattern=r"[vr]\d[\d\.]+\d",
                to_ignore=[
                    # Dendrite declares a v1.0, which never existed.
                    "v1.0",
                    # Construct declares a r2.0.0, which never existed.
                    "r2.0.0",
                ],
            )
        ]
        if project.spec_version_paths
        else None,
    )
    print(f"Loaded {project.name} spec versions: {list(versions.keys())}")

    # Map of room version to list of commit metadata for when support for that version changed.
    room_versions, room_versions_by_tag = get_project_versions(
        project,
        repo,
        project.room_version_finders,
    )
    print(f"Loaded {project.name} room versions: {list(room_versions.keys())}")

    # Map of default room version to list of commit metadata for when support for that version changed.
    default_room_versions, default_room_versions_by_tag = get_project_versions(
        project,
        repo,
        project.default_room_version_finders,
    )
    print(
        f"Loaded {project.name} default room versions: {list(default_room_versions.keys())}"
    )
    # TODO Validate there's no overlap of default room versions?

    # Resolve commits to date for when each version was first supported.
    versions_dates_all = {
        version: version_info[0].start_date
        for version, version_info in versions.items()
    }

    # Resolve the commit to the *next* tag.
    versions_dates_all_by_tag = {}
    for version, version_info in versions.items():
        tag = repo.get_tag_from_commit(version_info[0].first_commit)
        # If no tags were found than this wasn't released yet.
        if tag:
            versions_dates_all_by_tag[version] = repo.get_tag_datetime(tag)

    print(f"Loaded {project.name} dates: {list(versions_dates_all.keys())}")

    initial_commit_date, last_commit_date, forked_date = repo.get_project_datetimes(
        project
    )

    release_date = None
    earliest_tag = repo.get_earliest_tag(project)
    if earliest_tag:
        print(f"Found earliest tag: {earliest_tag}")
        release_date = repo.get_tag_datetime(earliest_tag)

    # Remove any spec versions which existed before this project was started.
    version_dates_after_commit = calculate_versions_after_date(
        initial_commit_date, versions_dates_all, spec_versions
    )
    version_dates_after_commit_by_tag = calculate_versions_after_date(
        initial_commit_date, versions_dates_all_by_tag, spec_versions
    )

    # Remove any spec versions which existed before this project was released.
    version_dates_after_release = calculate_versions_after_date(
        release_date, versions_dates_all, spec_versions
    )
    version_dates_after_release_by_tag = calculate_versions_after_date(
        release_date, versions_dates_all_by_tag, spec_versions
    )

    print()

    return ProjectData(
        initial_release_date=release_date,
        initial_commit_date=initial_commit_date,
        forked_date=forked_date,
        forked_from=project.forked_from,
        last_commit_date=last_commit_date,
        spec_version_dates_by_commit=version_info_to_dates(versions),
        spec_version_dates_by_tag=version_info_to_dates(versions_by_tag),
        room_version_dates_by_commit=version_info_to_dates(room_versions),
        room_version_dates_by_tag=version_info_to_dates(room_versions_by_tag),
        default_room_version_dates_by_commit=version_info_to_dates(
            default_room_versions
        ),
        default_room_version_dates_by_tag=version_info_to_dates(
            default_room_versions_by_tag
        ),
        lag_all_by_commit=calculate_lag(versions_dates_all, spec_versions),
        lag_all_by_tag=calculate_lag(versions_dates_all_by_tag, spec_versions),
        lag_after_commit_by_commit=calculate_lag(
            version_dates_after_commit, spec_versions
        ),
        lag_after_commit_by_tag=calculate_lag(
            version_dates_after_commit_by_tag, spec_versions
        ),
        lag_after_release_by_commit=calculate_lag(
            version_dates_after_release, spec_versions
        ),
        lag_after_release_by_tag=calculate_lag(
            version_dates_after_release_by_tag, spec_versions
        ),
        maturity=project.maturity.lower(),
    )


def main():
    # Get information about the spec itself.
    spec_versions, room_versions, default_room_versions = get_spec_dates()

    # Load the current project data.
    with open("data.json", "r") as f:
        result = json.load(f)

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
    result.update(
        **{
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
        }
    )

    if "homeserver_versions" not in result:
        result["homeserver_versions"] = {}

    # For each project find the earliest known date the project supported it.
    for project in load_projects():
        print(f"Starting {project.name}")

        if project.process_updates:
            result["homeserver_versions"][project.name.lower()] = asdict(
                get_project_dates(project, spec_versions)
            )
        else:
            # Some projects no longer have a repository setup, use the old version.
            print()

    for project, project_data in MANUAL_PROJECTS.items():
        result["homeserver_versions"][project.lower()] = asdict(project_data)

    with open("data.json", "w") as f:
        json.dump(result, f, default=json_encode, sort_keys=True, indent=4)


if __name__ == "__main__":
    main()
