from dataclasses import dataclass

from finders import PatternFinder, SpecVersionFinder, SubRepoFinder

PatternFinderType = list[PatternFinder | SubRepoFinder]


@dataclass
class Finders:
    # The finder(s) to use to get supported spec versions.
    #
    # Leave empty if no spec versions were ever implemented.
    spec_version_finders: PatternFinderType | None

    # The finder(s) to use to get supported room versions.
    #
    # Leave empty if no room versions were ever implemented.
    room_version_finders: PatternFinderType | None

    # The finder(s) to use to get the default room version.
    #
    # Leave empty if no default room version was ever implemented.
    default_room_version_finders: PatternFinderType | None


class ConduitFinders(Finders):
    """Base finders for Conduit=based projects."""

    @staticmethod
    def get_spec_version_finders(extra_paths: list[str]) -> PatternFinderType:
        return [
            SpecVersionFinder(
                paths=[
                    "src/client_server.rs",
                    "src/main.rs",
                    "src/client_server/unversioned.rs",
                    "src/api/client_server/unversioned.rs",
                ]
                + extra_paths,
            )
        ]

    spec_version_finders: PatternFinderType = get_spec_version_finders([])

    @staticmethod
    def get_room_version_finders(extra_paths: list[str]) -> PatternFinderType:
        return [
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/service/globals/mod.rs",
                ]
                + extra_paths,
                pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)(?:,|])',
            ),
        ]

    room_version_finders: PatternFinderType = get_room_version_finders([])

    @staticmethod
    def get_default_room_version_finders(
        extra_paths: list[str], additional_pattern: str = r""
    ) -> PatternFinderType:
        return [
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/config/mod.rs",
                ]
                + extra_paths,
                pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$'
                + additional_pattern,
            ),
        ]

    default_room_version_finders: PatternFinderType = get_default_room_version_finders(
        []
    )


class ConduwuitFinders(ConduitFinders):
    spec_version_finders: PatternFinderType = ConduitFinders.get_spec_version_finders(
        ["src/api/client/unversioned.rs"]
    )
    room_version_finders: PatternFinderType = ConduitFinders.get_room_version_finders(
        ["src/core/info/room_version.rs"]
    )
    default_room_version_finders: PatternFinderType = (
        ConduitFinders.get_default_room_version_finders(
            ["src/core/config/mod.rs"],
            r"|default_default_room_version.+RoomVersionId::V(\d+)",
        )
    )


class DendriteFinders(Finders):
    """Base finders for Dendrite-based projects."""

    spec_version_finders: PatternFinderType = [
        SpecVersionFinder(
            paths=[
                "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
                "clientapi/routing/routing.go",
            ],
            # Dendrite declares a v1.0, which never existed.
            to_ignore=["v1.0"],
        )
    ]
    room_version_finders: PatternFinderType = [
        # gomatrixserverlib was vendored early in the project, but before room versions were a thing.
        PatternFinder(
            paths=["roomserver/version/version.go"],
            pattern=r"RoomVersionV(\d+)",
        ),
        SubRepoFinder(
            repository="https://github.com/matrix-org/gomatrixserverlib",
            commit_finder=PatternFinder(
                paths=["go.mod"],
                pattern=r"github.com/matrix-org/gomatrixserverlib v0\.0\.0-\d+-([0-9a-f]+)",
            ),
            finder=PatternFinder(
                paths=["eventversion.go"], pattern=r"RoomVersionV(\d+)"
            ),
        ),
    ]
    default_room_version_finders: PatternFinderType = [
        PatternFinder(
            paths=[
                "roomserver/version/version.go",
                "setup/config/config_roomserver.go",
            ],
            pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
            # Dendrite declared room version 2 as a default, but that was invalid.
            to_ignore=["2"],
        ),
    ]


class SynapseLegacyFinders(Finders):
    """Base finders for Synapse legacy-based projects."""

    spec_version_finders: PatternFinderType = [
        SpecVersionFinder(paths=["synapse/rest/client/versions.py"])
    ]
    room_version_finders: PatternFinderType = [
        PatternFinder(
            paths=["synapse/api/constants.py", "synapse/api/room_versions.py"],
            pattern=r"RoomVersions.V(\d+)",
        ),
    ]
    default_room_version_finders: PatternFinderType = [
        PatternFinder(
            paths=[
                "synapse/api/constants.py",
                "synapse/api/room_versions.py",
                "synapse/config/server.py",
            ],
            pattern=r'(?:DEFAULT_ROOM_VERSION = RoomVersions.V|DEFAULT_ROOM_VERSION = "|"default_room_version", ")(\d+)',
        ),
    ]


class SynapseFinders(SynapseLegacyFinders):
    """Base finders for Synapse-based projects."""

    room_version_finders: PatternFinderType = (
        SynapseLegacyFinders.room_version_finders
        + [
            PatternFinder(
                paths=["rust/src/room_versions.rs"], pattern=r"ROOM_VERSION_V(\d+)"
            ),
        ]
    )
