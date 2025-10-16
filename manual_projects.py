from datetime import datetime, timezone

from data import ManualProjectData, VersionInfo

# See https://element.io/blog/synapse-pro-slashes-costs-for-running-nation-scale-matrix-deployments/
# <meta property="article:published_time" content="2024-12-10T08:27:21.000Z">
release_date = datetime(2024, 12, 10, 8, 27, 21, tzinfo=timezone.utc)

# See https://docs.element.io/latest/element-server-suite-pro/release-notes/
latest_release_date = datetime(2025, 10, 8, tzinfo=timezone.utc)

# The early release notes are not good, but the initial version was likely based on Synapse v1.121.0
# which was released on 2024-12-11. This already supported spec versions up to v1.11 and room versions
# up to 11.
initial_tag_version = [VersionInfo("0.1.0", release_date, None, None)]

versions_by_tag = {
    "r0.0.1": initial_tag_version,
    "r0.1.0": initial_tag_version,
    "r0.2.0": initial_tag_version,
    "r0.3.0": initial_tag_version,
    "r0.4.0": initial_tag_version,
    "r0.5.0": initial_tag_version,
    "r0.6.0": initial_tag_version,
    "r0.6.1": initial_tag_version,
    "v1.1": initial_tag_version,
    "v1.2": initial_tag_version,
    "v1.3": initial_tag_version,
    "v1.4": initial_tag_version,
    "v1.5": initial_tag_version,
    "v1.6": initial_tag_version,
    "v1.7": initial_tag_version,
    "v1.8": initial_tag_version,
    "v1.9": initial_tag_version,
    "v1.10": initial_tag_version,
    "v1.11": initial_tag_version,
    # See https://docs.element.io/latest/element-server-suite-pro/release-notes/#ess-pro-2580-2025-08-06
    "v1.12": [
        VersionInfo("25.8.0", datetime(2025, 8, 6, tzinfo=timezone.utc), None, None)
    ],
}

room_versions_by_tag = {
    "1": initial_tag_version,
    "2": initial_tag_version,
    "3": initial_tag_version,
    "4": initial_tag_version,
    "5": initial_tag_version,
    "6": initial_tag_version,
    "7": initial_tag_version,
    "8": initial_tag_version,
    "9": initial_tag_version,
    "10": initial_tag_version,
    "11": initial_tag_version,
    # See https://docs.element.io/latest/element-server-suite-pro/release-notes/#ess-pro-2581-2025-08-12
    "12": [
        VersionInfo("25.8.1", datetime(2025, 8, 12, tzinfo=timezone.utc), None, None)
    ],
}

default_room_versions_by_tag = {
    "10": initial_tag_version,
}

SYNAPSE_PRO = ManualProjectData(
    # See https://element.io/blog/synapse-pro-slashes-costs-for-running-nation-scale-matrix-deployments/
    # <meta property="article:published_time" content="2024-12-10T08:27:21.000Z">
    initial_release_date=release_date,
    initial_commit_date=release_date,  # This can't be None, even though we don't know this info.
    forked_date=release_date,  # Forked sometime before this date.
    forked_from="synapse",
    last_commit_date=latest_release_date,
    maturity="stable",
    spec_version_dates_by_commit={},
    spec_version_dates_by_tag=versions_by_tag,
    room_version_dates_by_commit={},
    room_version_dates_by_tag=room_versions_by_tag,
    default_room_version_dates_by_commit={},
    default_room_version_dates_by_tag=default_room_versions_by_tag,
)
