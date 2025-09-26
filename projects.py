import os.path
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable, Iterator
from urllib.request import urlopen

import tomllib

from data import ManualProjectData
from manual_projects import SYNAPSE_PRO

SERVER_METADATA_URL = "https://raw.githubusercontent.com/matrix-org/matrix.org/main/content/ecosystem/servers/servers.toml"


def parse_range_operator(s: str) -> set[str]:
    """Parse a range operator in Elixir, e.g. 3..5 should become {3, 4, 5}."""
    return set(map(str, range(*map(int, s.split(".."))))) | {s.split("..")[1]}


class RepositoryType(StrEnum):
    HG = "hg"
    GIT = "git"


class ProxyType(StrEnum):
    NONE = "none"
    YGGDRASIL = "yggdrasil"


@dataclass
class RepositoryMetadata:
    url: str
    type: RepositoryType = RepositoryType.GIT
    proxy_type: ProxyType = ProxyType.NONE


@dataclass
class ServerMetadata:
    # From the TOML file.
    name: str
    description: str
    author: str
    maturity: str
    language: str
    licence: str
    repository: RepositoryMetadata
    room: str | None = None


@dataclass
class PatternFinder:
    # The file paths relative to the root to check for the pattern.
    paths: list[str]

    # The pattern to use to information.
    #
    # This can have multiple capturing groups, all of which will be considered.
    #
    # If parser is provided, then the results are further processed with that.
    pattern: str

    # The parser, defaults to none.
    parser: Callable[[str], set[str]] | None = None

    # Invalid results that should be ignored.
    to_ignore: list[str] | None = None


@dataclass
class SubModuleFinder:
    # The path the submodule gets checked out at.
    path: str


@dataclass
class SubRepoFinder:
    # A separate repo to search in.
    repository: RepositoryMetadata

    # The finder to get the git hash to checkout from the main repository.
    commit_finder: PatternFinder | SubModuleFinder

    # The finder to use to get the desired information from the sub-repository.
    finder: PatternFinder


@dataclass
class AdditionalMetadata:
    # The branch which has the latest commit.
    branch: str

    # The file paths (relative to repo root) to check for spec version information.
    #
    # Leave empty if no spec versions were ever implemented.
    spec_version_paths: list[str]

    # The finder(s) to use to get supported room versions.
    #
    # Leave empty if no room versions were ever implemented.
    room_version_finders: list[PatternFinder | SubRepoFinder] | None

    # The finder(s) to use to get the default room version.
    #
    # Leave empty if no default room version was ever implemented.
    default_room_version_finders: list[PatternFinder | SubRepoFinder] | None

    # The earliest commit to consider.
    #
    # Useful for forks where the project contains many old commits.
    earliest_commit: str | None
    # The earliest tag to consider. If not given, the earliest tag in the repo
    # which contains the earliest commit is used. If there's no earliest commit,
    # then the earliest tag is used.
    #
    # Note that earlier tags might exist in the repo due to forks or other reasons.
    earliest_tag: str | None

    # Project this is forked from.
    forked_from: str | None

    # True to process updates, false to use what's currently in the JSON file.
    process_updates: bool


@dataclass
class ProjectMetadata(ServerMetadata, AdditionalMetadata):
    pass


# Projects to ignore.
INVALID_PROJECTS = {
    # Dendron is essentially a reverse proxy, not a homeserver.
    "dendron",
}


# Constants.
ADDITIONAL_METADATA = {
    "bullettime": AdditionalMetadata(
        "master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "conduit": AdditionalMetadata(
        "next",
        spec_version_paths=[
            "src/client_server.rs",
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/service/globals/mod.rs",
                ],
                pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)(?:,|])',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/config/mod.rs",
                ],
                pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$',
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "conduwuit": AdditionalMetadata(
        branch="main",
        spec_version_paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
            "src/api/client/unversioned.rs",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/service/globals/mod.rs",
                    "src/core/info/room_version.rs",
                ],
                pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)(?:,|])',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/config/mod.rs",
                    "src/core/config/mod.rs",
                ],
                pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$|default_default_room_version.+RoomVersionId::V(\d+)',
            ),
        ],
        earliest_commit="40908b24e74bda4c80a5a6183602afcc0c04449b",
        earliest_tag=None,
        forked_from="conduit",
        process_updates=False,
    ),
    "continuwuity": AdditionalMetadata(
        branch="main",
        spec_version_paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
            "src/api/client/unversioned.rs",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/service/globals/mod.rs",
                    "src/core/info/room_version.rs",
                ],
                pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)(?:,|])',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/config/mod.rs",
                    "src/core/config/mod.rs",
                ],
                pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$|default_default_room_version.+RoomVersionId::V(\d+)',
            ),
        ],
        earliest_commit="e054a56b3286a6fb3091bedd5261089435ed26d1",
        earliest_tag=None,
        forked_from="conduwuit",
        process_updates=True,
    ),
    "construct": AdditionalMetadata(
        "master",
        spec_version_paths=["ircd/json.cc", "modules/client/versions.cc"],
        room_version_finders=[
            PatternFinder(paths=["modules/client/capabilities.cc"], pattern=r'"(\d+)"'),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "modules/m_room_create.cc",
                    "modules/client/createroom.cc",
                    "matrix/room_create.cc",
                ],
                pattern=r'(?:"default",|"room_version", json::value {) +"(\d+)',
            ),
        ],  # Earlier commits from charybdis.
        earliest_commit="b592b69b8670413340c297e5a41caf153d832e57",
        # Earlier tags from charybdis.
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "dendrite": AdditionalMetadata(
        "main",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        room_version_finders=[
            # gomatrixserverlib was vendored early in the project, but before
            # room versions were a thing.
            PatternFinder(
                paths=["roomserver/version/version.go"],
                pattern=r"RoomVersionV(\d+)",
            ),
            SubRepoFinder(
                repository=RepositoryMetadata(
                    url="https://github.com/matrix-org/gomatrixserverlib"
                ),
                commit_finder=PatternFinder(
                    paths=["go.mod"],
                    pattern=r"github.com/matrix-org/gomatrixserverlib v0.0.0-\d+-([0-9a-f]+)",
                ),
                finder=PatternFinder(
                    paths=["eventversion.go"], pattern=r"RoomVersionV(\d+)"
                ),
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "roomserver/version/version.go",
                    "setup/config/config_roomserver.go",
                ],
                pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
                # Dendrite declared room version 2 as a default, but that was invalid.
                to_ignore=["2"],
            ),
        ],
        earliest_commit="6bfe946bd2d82db12c1e49918612cc3d7139b8ce",
        earliest_tag=None,
        forked_from="dendrite-legacy",
        process_updates=True,
    ),
    "jsynapse": AdditionalMetadata(
        "master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "ligase": AdditionalMetadata(
        "develop",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "proxy/routing/routing.go",
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit="bde8bc21a45a9dcffaaa812aa6a5a5341bca5f42",
        earliest_tag=None,
        forked_from="dendrite-legacy",
        process_updates=True,
    ),
    "maelstrom": AdditionalMetadata(
        "master",
        spec_version_paths=["src/server/handlers/admin.rs"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "matrex": AdditionalMetadata(
        "master",
        spec_version_paths=[
            "web/controllers/client_versions_controller.ex",
            "controllers/client/versions.ex",
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "mxhsd": AdditionalMetadata(
        "master",
        spec_version_paths=[
            "src/main/java/io/kamax/mxhsd/spring/client/controller/VersionController.java"
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "pallium": AdditionalMetadata(
        "master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "synapse": AdditionalMetadata(
        "develop",
        spec_version_paths=["synapse/rest/client/versions.py"],
        room_version_finders=[
            PatternFinder(
                paths=["synapse/api/constants.py", "synapse/api/room_versions.py"],
                pattern=r"RoomVersions.V(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "synapse/api/constants.py",
                    "synapse/api/room_versions.py",
                    "synapse/config/server.py",
                ],
                pattern=r'(?:DEFAULT_ROOM_VERSION = RoomVersions.V|DEFAULT_ROOM_VERSION = "|"default_room_version", ")(\d+)',
            ),
        ],
        # First tag from AGPL Synapse.
        earliest_commit="230decd5b8deea78674f92b2c0c11bd41090470a",
        # Earlier tags exist from Apache Synapse.
        earliest_tag=None,
        forked_from="synapse-legacy",
        process_updates=True,
    ),
    "transform": AdditionalMetadata(
        "master",
        spec_version_paths=["config.json"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "telodendria": AdditionalMetadata(
        "master",
        spec_version_paths=["src/Routes/RouteMatrix.c", "src/Routes/RouteVersions.c"],
        room_version_finders=[
            PatternFinder(
                paths=["src/Routes/RouteCapabilities.c"],
                pattern=r'roomVersions, "(\d+)"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["src/Routes/RouteCapabilities.c"],
                pattern=r'JsonValueString\("(\d+)"\), 2, "m.room_versions", "default"',
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    "tuwunel": AdditionalMetadata(
        branch="dev",
        spec_version_paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
            "src/api/client/unversioned.rs",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/service/globals/mod.rs",
                    "src/core/info/room_version.rs",
                ],
                pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)(?:,|])',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/config/mod.rs",
                    "src/core/config/mod.rs",
                ],
                pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$|default_default_room_version.+RoomVersionId::V(\d+)',
            ),
        ],
        earliest_commit="ce6e5e48de2a3580e17609f382cd4520fb6d8c63",
        earliest_tag=None,
        forked_from="conduwuit",
        process_updates=True,
    ),
}

# https://github.com/vlad-tokarev/go-matrix-homeserver

ADDITIONAL_PROJECTS = [
    ProjectMetadata(
        name="architex",
        description="A Matrix homeserver written in Elixir",
        author="Pim Kunis",
        maturity="Obsolete",
        language="Elixir",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://gitlab.com/pizzapim/architex"),
        room=None,
        branch="master",
        spec_version_paths=["lib/architex_web/client/controllers/info_controller.ex"],
        room_version_finders=[
            PatternFinder(
                paths=["lib/architex_web/client/controllers/info_controller.ex"],
                pattern=r'"(\d+)"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["lib/architex_web/client/controllers/info_controller.ex"],
                pattern=r'"default: "(\d+)"',
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="axiom",
        description="Python Matrix Homeserver implementation aimed for easy prototyping and experimentation",
        author="Jonathan de Jong",
        maturity="Unstarted",
        language="Python",
        licence="EUPL-1.2",
        repository=RepositoryMetadata(url="https://github.com/ShadowJonathan/Axiom"),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="babbleserv",
        description="Babbleserv is a Matrix homeserver built on top of FoundationDB",
        author="Beeper",
        maturity="Alpha",
        language="Go",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/beeper/babbleserv"),
        room=None,
        branch="main",
        # Note that the spec version is wrong and is defined without a "v" prefix.
        spec_version_paths=["internal/routes/client/client.go"],
        room_version_finders=[
            SubRepoFinder(
                repository=RepositoryMetadata(
                    url="https://github.com/matrix-org/gomatrixserverlib"
                ),
                commit_finder=PatternFinder(
                    paths=["go.mod"],
                    pattern=r"github.com/matrix-org/gomatrixserverlib v0.0.0-\d+-([0-9a-f]+)",
                ),
                finder=PatternFinder(
                    paths=["eventversion.go"], pattern=r"RoomVersionV(\d+)"
                ),
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["babbleserv/internal/routes/client/room_create.go"],
                pattern=r'defaultRoomVersion = "(\d+)"',
            )
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="casniam",
        description="An experimental, modular, rust Matrix homeserver federation library. Currently mostly used as a test bed for ideas.",
        author="Erik Johnston",
        maturity="Obsolete",
        language="Rust",
        licence="",
        repository=RepositoryMetadata(url="https://github.com/erikjohnston/casniam"),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="coignet",
        description="A Matrix homeserver written in Rust",
        author="Marcus Medom Ryding",
        maturity="Unstarted",
        language="Rust",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/Magnap/coignet"),
        room=None,
        branch="master",
        spec_version_paths=["src/endpoints/client_server/mod.rs"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="cortex",
        description="Cortex is a reference implementation of Matrix Home Server",
        author="Vedhavyas Singareddi",
        maturity="Unstarted",
        language="Go",
        licence="Apache-2.0",
        repository=RepositoryMetadata(url="https://github.com/vedhavyas/cortex"),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="cubby",
        description="A matrix homeserver backed by Apache Parquet through polars, because that's definitely a good idea.",
        author="Vedhavyas Singareddi",
        maturity="Alpha",
        language="Rust",
        licence="MIT",
        repository=RepositoryMetadata(url="https://github.com/SiliconSelf/cubby"),
        room=None,
        branch="main",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="dendrite-legacy",
        description="Dendrite is a second-generation Matrix homeserver written in Go!",
        author="Matrix.org team",
        maturity="Beta",
        language="Go",
        licence="Apache-2.0",
        repository=RepositoryMetadata(url="https://github.com/matrix-org/dendrite"),
        room=None,
        branch="main",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        room_version_finders=[
            # gomatrixserverlib was vendored early in the project, but before
            # room versions were a thing.
            PatternFinder(
                paths=["roomserver/version/version.go"],
                pattern=r"RoomVersionV(\d+)",
            ),
            SubRepoFinder(
                repository=RepositoryMetadata(
                    url="https://github.com/matrix-org/gomatrixserverlib"
                ),
                commit_finder=PatternFinder(
                    paths=["go.mod"],
                    pattern=r"github.com/matrix-org/gomatrixserverlib v0.0.0-\d+-([0-9a-f]+)",
                ),
                finder=PatternFinder(
                    paths=["eventversion.go"], pattern=r"RoomVersionV(\d+)"
                ),
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "roomserver/version/version.go",
                    "setup/config/config_roomserver.go",
                ],
                pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
                # Dendrite declared room version 2 as a default, but that was invalid.
                to_ignore=["2"],
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="dopamine",
        description="Matrix homeserver implementation written in Elixir ",
        author="Aidan Noll",
        maturity="Unstarted",
        language="Elixir",
        licence="BSD-2-Clause",
        repository=RepositoryMetadata(url="https://github.com/onixus74/Dopamine"),
        room=None,
        branch="master",
        spec_version_paths=["apps/dopamine_web/lib/dopamine_web/views/info_view.ex"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="fluctlight",
        description="Fluctlight is a playground for testing random ideas for speed improvements on a chat server with the Matrix protocol.",
        author="Andrei Vasiliu",
        maturity="Alpha",
        language="Rust",
        licence="Apache-2.0 OR MIT",
        repository=RepositoryMetadata(
            url="https://github.com/andreivasiliu/fluctlight"
        ),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="grapevine",
        description="Grapevine is a Matrix homeserver that was originally forked from Conduit 0.7.0. Eventually, Grapevine will be rewritten from scratch in a separate repository.",
        author="Charles Hall",
        maturity="Alpha",
        language="Rust",
        licence="Apache-2.0",
        repository=RepositoryMetadata(
            url="https://gitlab.computer.surgery/matrix/grapevine"
        ),
        room=None,
        branch="main",
        spec_version_paths=[
            "src/client_server.rs",
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/service/globals/mod.rs",
                    "src/service/globals.rs",
                ],
                pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)(?:,|])',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/client_server.rs",
                    "src/client_server/capabilities.rs",
                    "src/database/globals.rs",
                    "src/server_server.rs",
                    "src/config/mod.rs",
                    "src/config.rs",
                ],
                pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$',
            ),
        ],
        earliest_commit="17a0b3430934fbb8370066ee9dc3506102c5b3f6",
        earliest_tag=None,
        forked_from="conduit",
        process_updates=True,
    ),
    ProjectMetadata(
        name="Gridify",
        description="Corporate-level Unified communication server with support for several protocols: Matrix Home and Identity server and Grid Data Server",
        author="Kamax Sarl",
        maturity="Obsolete",
        language="Java",
        licence="AGPL-3.0-or-later",
        repository=RepositoryMetadata(
            url="https://gitlab.com/kamax-lu/software/gridify/server"
        ),
        room="#gridify-server:kamax.io",
        branch="master",
        spec_version_paths=[
            "src/main/java/io/kamax/grid/gridepo/http/handler/matrix/VersionsHandler.java",
            "src/main/java/io/kamax/grid/gridepo/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
            "src/main/java/io/kamax/gridify/server/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/main/java/io/kamax/gridify/server/network/matrix/core/room/algo/BuiltinRoomAlgoLoader.java"
                ],
                pattern=r'versions\.add\("(\d+)"\);',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/main/java/io/kamax/gridify/server/network/matrix/core/room/algo/RoomAlgos.java"
                ],
                pattern=r"RoomAlgoV(\d+)",
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    # Note that ejabberd doesn't implement the Client-Server API, thus it doesn't declare
    # itself compatible with any particular versions.
    ProjectMetadata(
        name="ejabberd",
        description="Robust, Ubiquitous and Massively Scalable Messaging Platform (XMPP, MQTT, SIP Server)",
        author="ProcessOne",
        maturity="Alpha",
        language="Erlang/OTP",
        licence="GPL-2.0-only",
        repository=RepositoryMetadata(url="https://github.com/processone/ejabberd"),
        room=None,
        branch="master",
        # Check src/mod_matrix* for matrix related files.
        spec_version_paths=[],
        room_version_finders=[
            PatternFinder(
                paths=["src/mod_matrix_gw_room.erl"],
                pattern=r'binary_to_room_version\(<<"(\d+)">>\)',
            ),
        ],
        default_room_version_finders=None,
        # First commit & tag w/ Matrix support.
        earliest_commit="f44e23b8cc2c3ab7d1c36f702f00a6b5b947c5d0",
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="gopheus",
        description="Testing goplang with Matrix.org Homeserver",
        author="SkaveRat",
        maturity="Unstarted",
        language="Go",
        licence="GPL-2.0",
        repository=RepositoryMetadata(url="https://github.com/SkaveRat/gopheus"),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="hammerhead",
        description='"Sublight thrusters, full power!" | nimble little matrix server you\'ll only see once',
        author="nexy",
        maturity="Alpha",
        language="Go",
        licence="MPL-2.0",
        repository=RepositoryMetadata(url="https://git.nexy7574.co.uk/nex/hammerhead"),
        room=None,
        branch="dev",
        spec_version_paths=[
            "nexserv/server/versions.go",
            "nexserv/router/routes/client/versions.go",
            "hammerhead/router/routes/client/versions.go",
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Harmony",
        description="A lighter-weight fork of the Dendrite homeserver for the Matrix protocol",
        author="Neil Alexander",
        maturity="Beta",
        language="Go",
        licence="Apache-2.0",
        repository=RepositoryMetadata(url="https://github.com/neilalexander/harmony"),
        room="#harmony:neilalexander.dev",
        branch="main",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        room_version_finders=[
            # gomatrixserverlib was vendored early in the project, but before
            # room versions were a thing.
            PatternFinder(
                paths=["roomserver/version/version.go"],
                pattern=r"RoomVersionV(\d+)",
            ),
            SubRepoFinder(
                repository=RepositoryMetadata(
                    url="https://github.com/matrix-org/gomatrixserverlib"
                ),
                commit_finder=PatternFinder(
                    paths=["go.mod"],
                    pattern=r"github.com/matrix-org/gomatrixserverlib v0.0.0-\d+-([0-9a-f]+)",
                ),
                finder=PatternFinder(
                    paths=["eventversion.go"], pattern=r"RoomVersionV(\d+)"
                ),
            ),
            PatternFinder(
                paths=["internal/gomatrixserverlib/eventversion.go"],
                pattern=r"RoomVersionV(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "roomserver/version/version.go",
                    "setup/config/config_roomserver.go",
                ],
                pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
                # Dendrite declared room version 2 as a default, but that was invalid.
                to_ignore=["2"],
            ),
        ],
        earliest_commit="6d1087df8dbd7982e7c7ad2f16b17588562c4048",
        earliest_tag=None,
        forked_from="dendrite-legacy",
        process_updates=True,
    ),
    ProjectMetadata(
        name="HG",
        description="Minimal Matrix HomeServer written in TypeScript",
        author="Jaakko Heusala",
        maturity="Alpha",
        language="TypeScript",
        licence="MIT",
        repository=RepositoryMetadata(url="https://github.com/heusalagroup/hghs"),
        room=None,
        branch="main",
        spec_version_paths=[],
        room_version_finders=[
            SubRepoFinder(
                repository=RepositoryMetadata(
                    url="https://github.com/heusalagroup/fi.hg.matrix"
                ),
                commit_finder=SubModuleFinder(path="src/fi/hg/matrix"),
                finder=PatternFinder(
                    paths=["types/MatrixRoomVersion.ts"],
                    pattern=r"MatrixRoomVersion\.V(\d+)",
                ),
            ),
        ],
        default_room_version_finders=[
            SubRepoFinder(
                repository=RepositoryMetadata(
                    url="https://github.com/heusalagroup/fi.hg.matrix"
                ),
                commit_finder=SubModuleFinder(path="src/fi/hg/matrix"),
                finder=PatternFinder(
                    paths=["server/MatrixServerService.ts"],
                    pattern=r"defaultRoomVersion : MatrixRoomVersion = MatrixRoomVersion\.V(\d+)",
                ),
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="himatrix",
        description="[wip] matrix homeserver implementation",
        author="himanoa",
        maturity="Unstarted",
        language="Rust",
        licence="",
        repository=RepositoryMetadata(url="https://github.com/himanoa/himatrix"),
        room=None,
        branch="master",
        spec_version_paths=["client-server-api/src/routes/versions.rs"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Insomnium",
        description="A Matrix homeserver implementation.",
        author="Lucas Neuber",
        maturity="Unstarted",
        language="C#",
        licence="GPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/BerndSchmecka/Insomnium"),
        room=None,
        branch="production",
        spec_version_paths=["Insomnium/src/Insomnium/Program.cs"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="jmatrix",
        description="Matrix homeserver written in Java/Quarkus",
        author="Lazar Bulić",
        maturity="Unstarted",
        language="Java",
        licence="Apache-2.0",
        repository=RepositoryMetadata(url="https://github.com/pendula95/jmatrix"),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Matrices",
        description="Matrix.org homeservers",
        author="James Aimonetti",
        maturity="Unstarted",
        language="Erlang",
        licence="MPL-2.0",
        repository=RepositoryMetadata(
            url="https://github.com/jamesaimonetti/kazoo-matrices"
        ),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="lomatia",
        description="Experimental Matrix homeserver written in Rust",
        author="LEARAX, vpzomtrrfrt",
        maturity="Unstarted",
        language="Rust",
        licence="GPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/birders/lomatia"),
        room=None,
        branch="master",
        spec_version_paths=["src/server_administration.rs"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="MagnetHS",
        description="A new breed of homeserver for matrix.org",
        author="Half-Shot",
        maturity="Obsolete",
        language=".NET Core 2.0",
        licence="MIT",
        repository=RepositoryMetadata(url="https://github.com/Half-Shot/MagnetHS"),
        room=None,
        branch="master",
        spec_version_paths=[
            "HalfShot.MagnetHS/Services/ClientServerAPIService/ClientServerAPI.cs"
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="mascarene",
        description="Mascarene is an open source homeserver implementation of the Matrix protocol.",
        author="?",
        maturity="Obsolete",
        language="Scala",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://gitlab.com/mascarene/mascarene"),
        room=None,
        branch="master",
        spec_version_paths=[
            "homeserver/src/main/scala/org/mascarene/homeserver/matrix/server/client/ClientApiRoutes.scala"
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "homeserver/src/main/scala/org/mascarene/homeserver/internal/rooms/RoomAgent.scala"
                ],
                pattern=r'"(\d+)"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["homeserver/src/main/resources/reference.conf"],
                pattern=r'default-room-version="(\d+)"',
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="mocktrix",
        description="Partial implementation of a Matrix homeserver (work in progress)",
        author="Dirk Stolle",
        maturity="Alpha",
        language="C#",
        licence="GPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/striezel/Mocktrix"),
        room=None,
        branch="main",
        spec_version_paths=[
            "Mocktrix/client/Versions.cs",
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "Mocktrix.RoomVersions/Support.cs",
                ],
                pattern=r'"(\d+)"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["Mocktrix/client/r0.6.1/Capabilities.cs"],
                pattern=r'DefaultVersion = "(\d+)",',
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="neuron",
        description="typescript matrix homeserver implementation",
        author="Michael",
        maturity="Unstarted",
        language="TypeScript",
        licence="MIT",
        repository=RepositoryMetadata(url="https://github.com/avatus/neuron"),
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="palpo",
        description="A Rust Matrix Server Implementation",
        author="Chrislearn Young",
        maturity="Alpha",
        language="Rust",
        licence="Apache-2.0",
        repository=RepositoryMetadata(
            url="https://github.com/palpo-matrix-server/palpo"
        ),
        room=None,
        branch="main",
        spec_version_paths=["crates/server/src/routing/client/mod.rs"],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "crates/server/src/bl/mod.rs",
                    "crates/server/src/global.rs",
                    "crates/server/src/config/mod.rs",
                ],
                pattern=r"RoomVersionId::V(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "crates/server/src/config/server_config.rs",
                    "crates/server/src/config/server.rs",
                ],
                pattern=r"RoomVersionId::V(\d+)",
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="persephone",
        description="A WIP experimental C++20 matrix server",
        author="MTRNord",
        maturity="Alpha",
        language="C++",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/MTRNord/persephone"),
        room=None,
        branch="main",
        spec_version_paths=[
            "src/webserver/client_server_api/c_s_api.hpp",
            "src/webserver/client_server_api/ClientServerCtrl.cpp",
        ],
        room_version_finders=[
            PatternFinder(paths=["src/utils/state_res.cpp"], pattern=r'"(\d+)"'),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/webserver/client_server_api/ClientServerCtrl.cpp",
                    "src/webserver/client_server_api/ClientServerCtrl.hpp",
                ],
                pattern=r'default_room_version = "(\d+)"',
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="plasma",
        description="Plasma is an open-source Matrix server implementation.",
        author="",
        maturity="Obsolete",
        language="Elixir",
        licence="Apache-2.0",
        repository=RepositoryMetadata(url="https://gitlab.com/plasmahs/plasma"),
        room=None,
        branch="main",
        spec_version_paths=[],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="plasma_old",
        description="",
        author="",
        maturity="Obsolete",
        language="Elixir",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://gitlab.com/plasmahs/plasma_old"),
        room=None,
        branch="master",
        spec_version_paths=[
            "lib/matrix_client_api/controllers/versions.ex",
            "lib/matrix_client_api/controllers/versions_controller.ex",
        ],
        room_version_finders=[
            PatternFinder(
                paths=["config/config.exs"],
                pattern=r"supported_room_versions: ~w\((.+)\)",
                parser=lambda s: s.split(" "),
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["config/config.exs"], pattern=r'default_room_version: "(\d+)"'
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="radio_beam",
        description="A WIP Matrix homeserver, powered by the BEAM",
        author="Ben W.",
        maturity="Alpha",
        language="Erlang",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(
            url="https://github.com/Bentheburrito/radio_beam"
        ),
        room=None,
        branch="main",
        spec_version_paths=["config/config.exs"],
        room_version_finders=[
            PatternFinder(
                paths=["config/config.exs"],
                pattern=r'Map\.new\((.+),|"(\d+)" => "stable"',
                # If the first matching group matches, then split on .. and convert to a range
                # of values. If the second group matches, it is just a single value.
                parser=lambda s: parse_range_operator(s[0]) if s[0] else {s[1]},
            ),
        ],
        default_room_version_finders=[
            PatternFinder(paths=["config/config.exs"], pattern=r'default: "(\d+)"'),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    # Note that RocketChat homeserver doesn't implement the Client-Server API, thus
    # it doesn't declare itself compatible with any particular versions.
    ProjectMetadata(
        name="RocketChat-homeserver",
        description="",
        author="",
        maturity="Alpha",
        language="TypeScript",
        licence="?",
        repository=RepositoryMetadata(url="https://github.com/RocketChat/homeserver"),
        room=None,
        branch="main",
        spec_version_paths=[],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "packages/homeserver/src/services/event.service.ts",
                    "packages/federation-sdk/src/services/event.service.ts",
                ],
                pattern=r"""['"](\d+)['"]""",
            ),
        ],
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Ruma",
        description="A Matrix homeserver",
        author="Jimmy Cuadra",
        maturity="Obsolete",
        language="Rust",
        licence="MIT",
        repository=RepositoryMetadata(url="https://github.com/ruma/homeserver"),
        room="#ruma:matrix.org",
        branch="master",
        spec_version_paths=["src/api/r0/versions.rs"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Serverless-Matrix",
        description="A serverless (nodejs functions cloudflare workers, lambda, gcp functions...) matrix homeserver",
        author="Justin Parra",
        maturity="Unstarted",
        language="JavaScript",
        licence="ISC",
        repository=RepositoryMetadata(
            url="https://github.com/parrajustin/Serverless-Matrix"
        ),
        room=None,
        branch="main",
        spec_version_paths=["Identity/src/version.ts"],
        room_version_finders=None,
        default_room_version_finders=None,
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-legacy",
        description="Matrix.org homeserver",
        author="Matrix.org team",
        maturity="Stable",
        language="Python",
        licence="Apache-2.0",
        repository=RepositoryMetadata(url="https://github.com/matrix-org/synapse"),
        room=None,
        branch="develop",
        spec_version_paths=["synapse/rest/client/versions.py"],
        room_version_finders=[
            PatternFinder(
                paths=["synapse/api/constants.py", "synapse/api/room_versions.py"],
                pattern=r"RoomVersions.V(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "synapse/api/constants.py",
                    "synapse/api/room_versions.py",
                    "synapse/config/server.py",
                ],
                pattern=r'(?:DEFAULT_ROOM_VERSION = RoomVersions.V|DEFAULT_ROOM_VERSION = "|"default_room_version", ")(\d+)',
            ),
        ],
        earliest_commit=None,
        # Earlier tags exist from DINSIC.
        earliest_tag="v0.0.0",
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="thurim",
        description="A Matrix homeserver implementation written in Elixir that has just begun",
        author="Serra Allgood",
        maturity="Alpha",
        language="Rust",
        licence="AGPL-3.0",
        repository=RepositoryMetadata(url="https://github.com/serra-allgood/thurim"),
        room=None,
        branch="main",
        spec_version_paths=["lib/thurim_web/controllers/matrix/versions_controller.ex"],
        room_version_finders=[
            PatternFinder(
                paths=["config/config.exs"],
                pattern=r"supported_room_versions: ~w\((.+)\)",
                parser=lambda s: s.split(" "),
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["config/config.exs"], pattern=r'default_room_version: "(\d+)"'
            ),
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="vona",
        description="Vona is a flazing bast 🌟, and semory mafe [matrix] implementation made in Python 🐍 for stability.",
        author="Kierre Sametti",
        maturity="Alpha",
        language="Python",
        licence="Velicense",
        repository=RepositoryMetadata(
            url="http://[302:a6cd:5030:bb11::3000]/matrix/vona/",
            type=RepositoryType.HG,
            proxy_type=ProxyType.YGGDRASIL,
        ),
        room=None,
        branch="default",
        spec_version_paths=["src/c2s.py"],
        room_version_finders=[
            PatternFinder(
                paths=["src/c2s.py"], pattern=r'"(\d+)":"stable"', to_ignore=["1337"]
            )
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["src/c2s.py"], pattern=r'"default":"(\d+)"', to_ignore=["1337"]
            )
        ],
        earliest_commit=None,
        earliest_tag=None,
        forked_from=None,
        process_updates=True,
    ),
]

# Data to dump verbatim into data.json, this is for e.g. proprietary homeservers,
# repos that have been deleted, etc.
#
# Data may be inaccurate.
MANUAL_PROJECTS = {
    # https://github.com/binex-dsk/calcium
    #
    # matrix homeserver... but BASED!
    # "calcium": ManualProjectData(
    #     initial_release_date=None,
    #     initial_commit_date=datetime(2022, 6, 5, 0, 0, 0),
    #     forked_date=None,
    #     forked_from=None,
    #     last_commit_date=datetime(),
    #     spec_version_dates={},
    #     room_version_dates={},
    #     default_room_version_dates={},
    #     maturity="unstarted",
    # ),
    # https://git.spec.cat/Nyaaori/catalyst
    "catalyst": ManualProjectData(
        initial_release_date=None,
        # Pre-end of 2022-10-10:
        # https://matrix.org/blog/2023/01/03/matrix-community-year-in-review-2022
        # https://gitlab.com/famedly/conduit/-/commit/2b7c19835b65e4dd3a6a32466a9f45b06bf1ced2
        initial_commit_date=datetime(2022, 10, 10, 0, 0, 0),
        forked_date=datetime(2022, 10, 10, 0, 0, 0),
        forked_from="conduit",
        # No idea, use the latest commit in conduit from them?
        # https://gitlab.com/famedly/conduit/-/commit/7cc346bc18d50d614bd07f4d2dbe0186eb024389
        last_commit_date=datetime(2022, 12, 21, 0, 0, 0),
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag={},
        room_version_dates_by_commit={},
        room_version_dates_by_tag={},
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag={},
        maturity="alpha",
    ),
    "hungryserv": ManualProjectData(
        initial_release_date=None,
        # Pre 2022-06-10: https://sumnerevans.com/posts/travel/2022-lisbon-and-paris/ericeira-portugal/
        initial_commit_date=datetime(2022, 6, 5, 0, 0, 0),
        forked_date=None,
        forked_from=None,
        # It is being actively developed.
        last_commit_date=datetime.now(),
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag={},
        room_version_dates_by_commit={},
        room_version_dates_by_tag={},
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag={},
        maturity="beta",
    ),
    "synapse-pro": SYNAPSE_PRO,
}


def download_projects():
    """Download the servers.toml metadata file."""
    with open("servers.toml", "wb") as f:
        with urlopen(SERVER_METADATA_URL) as u:
            f.write(u.read())


def load_projects() -> Iterator[ProjectMetadata]:
    # Download the metadata if it doesn't exist.
    if not os.path.isfile("servers.toml"):
        download_projects()

    """Load the projects from the servers.toml file and augment with additional info."""
    with open("servers.toml", "rb") as f:
        data = tomllib.load(f)

    for server in data["servers"]:
        server_name = server["name"] = server["name"].lower()

        if server_name in INVALID_PROJECTS:
            print(f"Ignoring {server_name}.")
            print()
            continue

        if server_name not in ADDITIONAL_METADATA:
            print(f"No metadata for {server_name}, skipping.")
            continue

        server["repository"] = RepositoryMetadata(url=server["repository"])

        # Can't use asdict here since it recurses into inner classes.
        yield ProjectMetadata(**server, **ADDITIONAL_METADATA[server_name].__dict__)  # ty: ignore[missing-argument]

    yield from ADDITIONAL_PROJECTS
