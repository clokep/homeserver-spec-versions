import re
from datetime import datetime

from finders import get_pattern_from_file
from repository import GitRepository


def get_spec_dates() -> tuple[
    dict[str, datetime], dict[str, datetime], dict[str, datetime]
]:
    # First get the known versions according to the spec repo.
    spec_repo = GitRepository.create("https://github.com/matrix-org/matrix-spec.git")

    # Map of version -> commit date.
    spec_versions = {
        t.name.split("/")[-1]: spec_repo.get_tag_datetime(t)
        for t in spec_repo._repo.tags
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
    for commit in spec_repo._repo.iter_commits(paths=ROOM_VERSION_PATHS, reverse=True):
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
                    room_versions[room_version] = commit.committed_datetime

    # Map of default room versions -> commit date.
    DEFAULT_ROOM_VERSION_PATHS = [
        "specification/index.rst",
        "content/_index.md",
        "content/rooms/_index.md",
    ]
    default_room_versions = {}
    for commit in spec_repo._repo.iter_commits(
        "origin/main", paths=DEFAULT_ROOM_VERSION_PATHS, reverse=True
    ):
        spec_repo.checkout(commit)

        cur_versions = get_pattern_from_file(
            spec_repo.working_dir,
            DEFAULT_ROOM_VERSION_PATHS,
            r"Servers MUST have Room Version (\d+)|Servers SHOULD use (?:\*\*)?room version (\d+)(?:\*\*)?",
            None,
            [],
        )
        assert len(cur_versions) <= 1, "Found more than one default room version"
        if cur_versions:
            default_room_version = next(iter(cur_versions))
            if default_room_version not in default_room_versions:
                default_room_versions[default_room_version] = commit.committed_datetime

    return spec_versions, room_versions, default_room_versions
