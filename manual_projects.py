import dataclasses
import re
from datetime import datetime, timezone
from itertools import pairwise
from urllib.request import urlopen

from bs4 import BeautifulSoup, Tag

from data import ManualProjectData, Maturity, VersionInfo
from finders import SpecVersionFinder

RELEASE_NOTES_URL = (
    "https://docs.element.io/latest/element-server-suite-pro/release-notes/"
)

SPEC_VERSION_PATTERN = re.compile(SpecVersionFinder.pattern)
ROOM_VERSION_PATTERN = re.compile(r"room version (\d+)")
DEFAULT_ROOM_VERSION_PATTERN = re.compile(r'default room version to "?(\d+)"?')


# See https://element.io/blog/synapse-pro-slashes-costs-for-running-nation-scale-matrix-deployments/
# <meta property="article:published_time" content="2024-12-10T08:27:21.000Z">
initial_release_date = datetime(2024, 12, 10, 8, 27, 21, tzinfo=timezone.utc)

# The early release notes are not good, but the initial version was likely based on Synapse v1.121.0
# which was released on 2024-12-11. This already supported spec versions up to v1.11 and room versions
# up to 11.
initial_tag_version = VersionInfo("0.1.0", initial_release_date, None, None)

initial_spec_versions = [
    "r0.0.1",
    "r0.1.0",
    "r0.2.0",
    "r0.3.0",
    "r0.4.0",
    "r0.5.0",
    "r0.6.0",
    "r0.6.1",
    "v1.1",
    "v1.2",
    "v1.3",
    "v1.4",
    "v1.5",
    "v1.6",
    "v1.7",
    "v1.8",
    "v1.9",
    "v1.10",
    "v1.11",
]

initial_room_versions = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]


def find_versions(tag: Tag, string: str, pattern: re.Pattern[str]) -> set[str]:
    # Find text nodes that contain the string.
    items = tag.find_all(string=re.compile(string))

    # Find newly added spec versions.
    return set(pattern.findall(str(items)))


def generate_synapse_pro() -> ManualProjectData:
    """Parse relevant information from the release notes."""
    with urlopen(RELEASE_NOTES_URL) as f:
        soup = BeautifulSoup(f, "html.parser")

    versions_by_tag = {v: [initial_tag_version] for v in initial_spec_versions}
    room_versions_by_tag = {v: [initial_tag_version] for v in initial_room_versions}
    default_room_versions_by_tag = {"10": [initial_tag_version]}

    # Find all releases.
    latest_release_date = None
    for release_tag in soup.find_all("h2"):
        _, release_name, release_date_str = release_tag.text.rsplit(maxsplit=2)
        release_date_str = release_date_str.strip("(").strip(")") + "T00:00:00Z"
        release_date = datetime.fromisoformat(release_date_str)

        if latest_release_date is None:
            latest_release_date = release_date

        # Find all siblings to the next h2 and consider that the current release notes.
        next_tag = release_tag.next_sibling
        while next_tag and (not isinstance(next_tag, Tag) or next_tag.name != "h2"):
            current_tag = next_tag
            next_tag = current_tag.next_sibling

            # Search inside the unordered lists for list items that contain new Matrix spec versions.
            if not isinstance(current_tag, Tag) or current_tag.name != "ul":
                continue

            # Find newly added spec versions.
            new_spec_versions = find_versions(
                current_tag, "Advertise support", SPEC_VERSION_PATTERN
            )
            for new_spec_version in new_spec_versions:
                # This shouldn't happen.
                assert new_spec_version not in versions_by_tag
                versions_by_tag[new_spec_version] = [
                    VersionInfo(release_name, release_date)
                ]

            # Find newly added room versions.
            new_room_versions = find_versions(
                current_tag, "room version", ROOM_VERSION_PATTERN
            )
            for new_room_version in new_room_versions:
                # This shouldn't happen.
                assert new_room_version not in room_versions_by_tag
                room_versions_by_tag[new_room_version] = [
                    VersionInfo(release_name, release_date)
                ]

            # Find changed default room version.
            new_default_room_versions = find_versions(
                current_tag, "default room version", DEFAULT_ROOM_VERSION_PATTERN
            )
            assert len(new_default_room_versions) <= 1, new_default_room_versions
            if new_default_room_versions:
                new_default_room_version = next(iter(new_default_room_versions))
                # This shouldn't happen.
                assert new_default_room_version not in default_room_versions_by_tag
                default_room_versions_by_tag[new_default_room_version] = [
                    VersionInfo(release_name, release_date)
                ]

    # Add the stop dates of the default room versions by ordering them.
    for (_, current_default_room_ver), (_, next_default_room_ver) in pairwise(
        sorted(default_room_versions_by_tag.items())
    ):
        # These always are a list of 1 item.
        current_default_room_ver[0] = dataclasses.replace(
            current_default_room_ver[0],
            last_commit=next_default_room_ver[0].first_commit,
            end_date=next_default_room_ver[0].start_date,
        )

    # Ensure something was processed.
    assert latest_release_date is not None

    print(f"Loaded synapse-pro spec versions: {list(versions_by_tag.keys())}")
    print(f"Loaded synapse-pro room versions: {list(room_versions_by_tag.keys())}")
    print(
        f"Loaded synapse-pro default room versions: {list(default_room_versions_by_tag.keys())}"
    )

    return ManualProjectData(
        # See https://element.io/blog/synapse-pro-slashes-costs-for-running-nation-scale-matrix-deployments/
        # <meta property="article:published_time" content="2024-12-10T08:27:21.000Z">
        initial_release_date=initial_release_date,
        initial_commit_date=initial_release_date,  # This can't be None, even though we don't know this info.
        forked_date=initial_release_date,  # Forked sometime before this date.
        merged_back=False,
        forked_from="synapse",
        last_commit_date=latest_release_date,
        maturity=Maturity.Stable,
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag=versions_by_tag,
        room_version_dates_by_commit={},
        room_version_dates_by_tag=room_versions_by_tag,
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag=default_room_versions_by_tag,
    )
