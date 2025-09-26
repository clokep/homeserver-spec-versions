from dataclasses import dataclass
from datetime import datetime


@dataclass
class VersionInfo:
    first_commit: str
    start_date: datetime
    last_commit: str | None = None
    end_date: datetime | None = None


@dataclass
class ManualProjectData:
    """Data provided for projects without repositories."""

    initial_release_date: datetime | None
    initial_commit_date: datetime
    forked_date: datetime | None
    forked_from: str | None
    last_commit_date: datetime
    maturity: str
    spec_version_dates_by_commit: dict[str, list[VersionInfo]]
    spec_version_dates_by_tag: dict[str, list[VersionInfo]]
    room_version_dates_by_commit: dict[str, list[VersionInfo]]
    room_version_dates_by_tag: dict[str, list[VersionInfo]]
    default_room_version_dates_by_commit: dict[str, list[VersionInfo]]
    default_room_version_dates_by_tag: dict[str, list[VersionInfo]]


@dataclass
class ProjectData:
    """The project info that's dumped into the JSON file."""

    initial_release_date: datetime | None
    initial_commit_date: datetime
    forked_date: datetime | None
    forked_from: str | None
    last_commit_date: datetime
    maturity: str
    spec_version_dates_by_commit: dict[
        str, list[tuple[str, datetime, str | None, datetime | None]]
    ]
    spec_version_dates_by_tag: dict[
        str, list[tuple[str, datetime, str | None, datetime | None]]
    ]
    room_version_dates_by_commit: dict[
        str, list[tuple[str, datetime, str | None, datetime | None]]
    ]
    room_version_dates_by_tag: dict[
        str, list[tuple[str, datetime, str | None, datetime | None]]
    ]
    default_room_version_dates_by_commit: dict[
        str, list[tuple[str, datetime, str | None, datetime | None]]
    ]
    default_room_version_dates_by_tag: dict[
        str, list[tuple[str, datetime, str | None, datetime | None]]
    ]
    lag_all_by_commit: dict[str, int]
    lag_all_by_tag: dict[str, int]
    lag_after_commit_by_commit: dict[str, int]
    lag_after_commit_by_tag: dict[str, int]
    lag_after_release_by_commit: dict[str, int]
    lag_after_release_by_tag: dict[str, int]
