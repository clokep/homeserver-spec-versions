import json
import sys
from dataclasses import asdict, astuple, dataclass
from datetime import datetime

from data import ManualProjectData, ProjectData, VersionInfo
from finders import get_pattern_from_file
from projects import (
    MANUAL_PROJECTS,
    PatternFinder,
    ProjectMetadata,
    SubRepoFinder,
    load_projects,
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
    project: ProjectMetadata,
    spec_versions: dict[str, datetime],
    prev_last_commit: str | None,
    prev_project_data_hash: str | None,
) -> ProjectData | None:
    """
    Generate the project's version information.

    1. Update the project's repository.
    2. Crawl the files to find the commits when the supported versions change.
    3. Resolve the commits to dates.
    4. Calculate the lag and set of supported versions.

    """
    repo = Repository.create(project.repository)

    last_commit = repo.get_last_commit(project).hexsha
    project_data_hash = project.get_project_hash()
    if prev_last_commit == last_commit and prev_project_data_hash == project_data_hash:
        print("Skipping, project data unchanged and no new commits")
        return None

    # Map of spec version to list of commit metadata for when support for that version changed.
    versions, versions_by_tag = get_project_versions(
        project, repo, finders=project.spec_version_finders
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

    initial_commit_date, last_commit_date, forked_date = repo.get_project_datetimes(
        project
    )

    release_date = None
    earliest_tag = repo.get_earliest_tag(project)
    if earliest_tag:
        print(f"Found earliest tag: {earliest_tag}")
        release_date = repo.get_tag_datetime(earliest_tag)

    return get_project_data_for_manual(
        ManualProjectData(
            initial_release_date=release_date,
            initial_commit_date=initial_commit_date,
            forked_date=forked_date,
            forked_from=project.forked_from,
            last_commit_date=last_commit_date,
            maturity=project.maturity.lower(),
            spec_version_dates_by_commit=versions,
            spec_version_dates_by_tag=versions_by_tag,
            room_version_dates_by_commit=room_versions,
            room_version_dates_by_tag=room_versions_by_tag,
            default_room_version_dates_by_commit=(default_room_versions),
            default_room_version_dates_by_tag=(default_room_versions_by_tag),
        ),
        spec_versions,
        last_commit,
        project_data_hash,
    )


def _get_versions_after(
    initial_commit_date: datetime,
    initial_release_date: datetime | None,
    all_version_dates: dict[str, list[VersionInfo]],
    spec_versions: dict[str, datetime],
) -> tuple[dict[str, datetime], dict[str, datetime], dict[str, datetime]]:
    """Calculate the supported spec versions which happened after the project's initial commit/release."""

    # Resolve to date for when each version was first supported.
    version_dates = {
        version: version_info[0].start_date
        for version, version_info in all_version_dates.items()
    }

    # Remove any versions which existed before this project was started.
    version_dates_after_commit = calculate_versions_after_date(
        initial_commit_date, version_dates, spec_versions
    )

    # Remove any versions which existed before this project was released.
    version_dates_after_release_by_tag = calculate_versions_after_date(
        initial_release_date, version_dates, spec_versions
    )

    return version_dates, version_dates_after_commit, version_dates_after_release_by_tag


def get_project_data_for_manual(
    project_data: ManualProjectData,
    spec_versions: dict[str, datetime],
    last_commit: str | None = None,
    project_data_hash: str | None = None,
) -> ProjectData:
    """Calculate latency/lags & prep for dumping to JSON."""
    (
        spec_version_dates_by_commit,
        spec_version_dates_after_commit,
        spec_version_dates_after_release,
    ) = _get_versions_after(
        project_data.initial_commit_date,
        project_data.initial_release_date,
        project_data.spec_version_dates_by_commit,
        spec_versions,
    )

    (
        spec_version_dates_by_tag,
        spec_version_dates_after_commit_by_tag,
        spec_version_dates_after_release_by_tag,
    ) = _get_versions_after(
        project_data.initial_commit_date,
        project_data.initial_release_date,
        project_data.spec_version_dates_by_tag,
        spec_versions,
    )

    return ProjectData(
        initial_release_date=project_data.initial_release_date,
        initial_commit_date=project_data.initial_commit_date,
        forked_date=project_data.forked_date,
        forked_from=project_data.forked_from,
        last_commit_date=project_data.last_commit_date,
        last_commit=last_commit,
        project_data_hash=project_data_hash,
        maturity=project_data.maturity,
        spec_version_dates_by_commit=version_info_to_dates(
            project_data.spec_version_dates_by_commit
        ),
        spec_version_dates_by_tag=version_info_to_dates(
            project_data.spec_version_dates_by_tag
        ),
        room_version_dates_by_commit=version_info_to_dates(
            project_data.room_version_dates_by_commit
        ),
        room_version_dates_by_tag=version_info_to_dates(
            project_data.room_version_dates_by_tag
        ),
        default_room_version_dates_by_commit=version_info_to_dates(
            project_data.default_room_version_dates_by_commit
        ),
        default_room_version_dates_by_tag=version_info_to_dates(
            project_data.default_room_version_dates_by_tag
        ),
        lag_all_by_commit=calculate_lag(spec_version_dates_by_commit, spec_versions),
        lag_all_by_tag=calculate_lag(spec_version_dates_by_tag, spec_versions),
        lag_after_commit_by_commit=calculate_lag(
            spec_version_dates_after_commit, spec_versions
        ),
        lag_after_commit_by_tag=calculate_lag(
            spec_version_dates_after_commit_by_tag, spec_versions
        ),
        lag_after_release_by_commit=calculate_lag(
            spec_version_dates_after_release, spec_versions
        ),
        lag_after_release_by_tag=calculate_lag(
            spec_version_dates_after_release_by_tag, spec_versions
        ),
    )


def main(projects: set[str]):
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

    # Load the current project data.
    with open("data.json", "r") as f:
        result = json.load(f)

    if not projects or "spec" in projects:
        # Get information about the spec itself.
        spec_versions, room_versions, default_room_versions = get_spec_dates()
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
    else:
        # Load the previously fetch spec versions.
        spec_versions = {
            version: datetime.fromisoformat(date)
            for version, date in result["spec_versions"]["version_dates"].items()
        }

    if "homeserver_versions" not in result:
        result["homeserver_versions"] = {}

    # For each project find the earliest known date the project supported it.
    for project in load_projects():
        # Skip projects which were not included.
        if projects and project.name.lower() not in projects:
            continue

        print(f"Starting {project.name}")

        if not project.process_updates:
            # Some projects no longer have a repository setup, use the old version.
            print("Repository unavailable, skipping.")
        else:
            prev_project_dates = result["homeserver_versions"].get(project.name.lower())
            if prev_project_dates:
                prev_last_commit = prev_project_dates.get("last_commit")
                prev_project_data_hash = prev_project_dates.get("project_data_hash")
            else:
                prev_last_commit = None
                prev_project_data_hash = None

            project_dates = get_project_dates(
                project, spec_versions, prev_last_commit, prev_project_data_hash
            )
            if project_dates is not None:
                result["homeserver_versions"][project.name.lower()] = asdict(
                    project_dates
                )

        print()

    for project_name, project_generator in MANUAL_PROJECTS.items():
        # Skip projects which were not included.
        if projects and project_name.lower() not in projects:
            continue

        print(f"Starting {project_name}")
        project_data = project_generator()

        result["homeserver_versions"][project_name.lower()] = asdict(
            get_project_data_for_manual(project_data, spec_versions)
        )

        print()

    with open("data.json", "w") as f:
        json.dump(result, f, default=json_encode, sort_keys=True, indent=4)


if __name__ == "__main__":
    main(set(s.lower() for s in sys.argv[1:]))
