import os.path
import tomllib
from dataclasses import asdict, dataclass
from typing import Iterator
from urllib.request import urlopen

SERVER_METADATA_URL = "https://raw.githubusercontent.com/matrix-org/matrix.org/main/content/ecosystem/servers/servers.toml"


@dataclass
class ServerMetadata:
    # From the TOML file.
    name: str
    description: str
    author: str
    maturity: str
    language: str
    licence: str
    repository: str
    room: str | None = None


@dataclass
class AdditionalMetadata:
    # The branch which has the latest commit.
    branch: str
    # The file paths (relative to repo root) to check for spec version information.
    #
    # Leave empty if no spec versions were ever implemented.
    spec_version_paths: list[str]
    # Some homeservers store room version info in a different repo.
    #
    # Defaults to the project repo. If the project repo is used, earliest_commit
    # still applies; otherwise it does not.
    room_version_repo: str | None
    # The file paths (relative to room version or project root) to check for room
    # version information.
    #
    # Leave empty if no room versions were ever implemented.
    room_version_paths: list[str]
    # The pattern to use to fetch room versions.
    #
    # This should have 0 or 1 single capturing group.
    room_version_pattern: str
    # The file paths (relative to repo root) to check for default
    # room version information.
    #
    # Leave empty if no room versions were ever implemented.
    default_room_version_paths: list[str]
    # The pattern to use to fetch the default room version.
    #
    # This should have 0 or 1 single capturing group.
    default_room_version_pattern: str
    # The earliest commit to consider.
    #
    # Useful for forks where the project contains many old commits.
    earliest_commit: str | None
    # The earliest tag to consider. If not given, the earliest tag in the repo
    # is used.
    #
    # Note that earlier tags might exist in the repo due to forks or other reasons.
    earliest_tag: str | None


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
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "conduit": AdditionalMetadata(
        "next",
        spec_version_paths=[
            "src/client_server.rs",
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        room_version_repo=None,
        room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/service/globals/mod.rs",
        ],
        room_version_pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)',
        default_room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/config/mod.rs",
        ],
        default_room_version_pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$',
        earliest_commit=None,
        earliest_tag=None,
    ),
    "conduwuit": AdditionalMetadata(
        branch="main",
        spec_version_paths=[
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
            "src/api/client/unversioned.rs",
        ],
        room_version_repo=None,
        room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/service/globals/mod.rs",
        ],
        room_version_pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)',
        default_room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/config/mod.rs",
            "src/core/config/mod.rs",
        ],
        default_room_version_pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$|default_default_room_version.+RoomVersionId::V(\d+)',
        earliest_commit="9c3b3daafcbc95647b5641a6edc975e2ffc04b04",
        earliest_tag=None,
    ),
    "construct": AdditionalMetadata(
        "master",
        spec_version_paths=["ircd/json.cc", "modules/client/versions.cc"],
        room_version_repo=None,
        room_version_paths=["modules/client/capabilities.cc"],
        room_version_pattern=r'"(\d+)"',
        default_room_version_paths=[
            "modules/m_room_create.cc",
            "modules/client/createroom.cc",
            "matrix/room_create.cc",
        ],
        default_room_version_pattern=r'(?:"default",|"room_version", json::value {) +"(\d+)',
        earliest_commit=None,
        # Earlier tags from charybdis exist.
        earliest_tag="0.0.10020",
    ),
    "dendrite": AdditionalMetadata(
        "main",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        room_version_repo="https://github.com/matrix-org/gomatrixserverlib",
        room_version_paths=["eventversion.go"],
        room_version_pattern=r"RoomVersionV(\d+)",
        default_room_version_paths=[
            "roomserver/version/version.go",
            "setup/config/config_roomserver.go",
        ],
        default_room_version_pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "jsynapse": AdditionalMetadata(
        "master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "ligase": AdditionalMetadata(
        "develop",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "proxy/routing/routing.go",
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit="bde8bc21a45a9dcffaaa812aa6a5a5341bca5f42",
        earliest_tag=None,
    ),
    "maelstrom": AdditionalMetadata(
        "master",
        spec_version_paths=["src/server/handlers/admin.rs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "matrex": AdditionalMetadata(
        "master",
        spec_version_paths=[
            "web/controllers/client_versions_controller.ex",
            "controllers/client/versions.ex",
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "mxhsd": AdditionalMetadata(
        "master",
        spec_version_paths=[
            "src/main/java/io/kamax/mxhsd/spring/client/controller/VersionController.java"
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "synapse": AdditionalMetadata(
        "develop",
        spec_version_paths=["synapse/rest/client/versions.py"],
        room_version_repo=None,
        room_version_paths=["synapse/api/constants.py", "synapse/api/room_versions.py"],
        room_version_pattern=r"RoomVersions.V(\d+)",
        default_room_version_paths=[
            "synapse/api/constants.py",
            "synapse/api/room_versions.py",
            "synapse/config/server.py",
        ],
        # Either the constant or fetching the default_room_version from the config.
        default_room_version_pattern=r'(?:DEFAULT_ROOM_VERSION = RoomVersions.V|DEFAULT_ROOM_VERSION = "|"default_room_version", ")(\d+)',
        earliest_commit=None,
        # Earlier tags exist from DINSIC.
        earliest_tag="v0.0.0",
    ),
    "transform": AdditionalMetadata(
        "master",
        spec_version_paths=["config.json"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    "telodendria": AdditionalMetadata(
        "master",
        spec_version_paths=["src/Routes/RouteMatrix.c", "src/Routes/RouteVersions.c"],
        room_version_repo=None,
        room_version_paths=["src/Routes/RouteCapabilities.c"],
        room_version_pattern=r'roomVersions, "(\d+)"',
        default_room_version_paths=["src/Routes/RouteCapabilities.c"],
        default_room_version_pattern=r'JsonValueString\("(\d+)"\), 2, "m.room_versions", "default"',
        earliest_commit=None,
        earliest_tag=None,
    ),
}

ADDITIONAL_PROJECTS = [
    ProjectMetadata(
        name="architex",
        description="A Matrix homeserver written in Elixir",
        author="Pim Kunis",
        maturity="Obsolete",
        language="Elixir",
        licence="AGPL-3.0",
        repository="https://gitlab.com/pizzapim/architex",
        room=None,
        branch="master",
        spec_version_paths=["lib/architex_web/client/controllers/info_controller.ex"],
        room_version_repo=None,
        room_version_paths=["lib/architex_web/client/controllers/info_controller.ex"],
        room_version_pattern=r'"(\d+)"',
        default_room_version_paths=[
            "lib/architex_web/client/controllers/info_controller.ex"
        ],
        default_room_version_pattern=r'"default: "(\d+)"',
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="axiom",
        description="Python Matrix Homeserver implementation aimed for easy prototyping and experimentation",
        author="Jonathan de Jong",
        maturity="Unstarted",
        language="Python",
        licence="EUPL-1.2",
        repository="https://github.com/ShadowJonathan/Axiom",
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="casniam",
        description="An experimental, modular, rust Matrix homeserver federation library. Currently mostly used as a test bed for ideas.",
        author="Erik Johnston",
        maturity="Obsolete",
        language="Rust",
        licence="",
        repository="https://github.com/erikjohnston/casniam",
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="coignet",
        description="A Matrix homeserver written in Rust",
        author="Marcus Medom Ryding",
        maturity="Unstarted",
        language="Rust",
        licence="AGPL-3.0",
        repository="https://github.com/Magnap/coignet",
        room=None,
        branch="master",
        spec_version_paths=["src/endpoints/client_server/mod.rs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="cortex",
        description="Cortex is a reference implementation of Matrix Home Server",
        author="Vedhavyas Singareddi",
        maturity="Unstarted",
        language="Go",
        licence="Apache-2.0",
        repository="https://github.com/vedhavyas/cortex",
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="dopamine",
        description="Matrix homeserver implementation written in Elixir ",
        author="Aidan Noll",
        maturity="Unstarted",
        language="Elixir",
        licence="BSD-2-Clause",
        repository="https://github.com/onixus74/Dopamine",
        room=None,
        branch="master",
        spec_version_paths=["apps/dopamine_web/lib/dopamine_web/views/info_view.ex"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="grapevine",
        description="Grapevine is a Matrix homeserver that was originally forked from Conduit 0.7.0. Eventually, Grapevine will be rewritten from scratch in a separate repository.",
        author="Charles Hall",
        maturity="Alpha",
        language="Rust",
        licence="Apache-2.0",
        repository="https://gitlab.computer.surgery/matrix/grapevine-fork",
        room=None,
        branch="main",
        spec_version_paths=[
            "src/client_server.rs",
            "src/main.rs",
            "src/client_server/unversioned.rs",
            "src/api/client_server/unversioned.rs",
        ],
        room_version_repo=None,
        room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/service/globals/mod.rs",
            "src/service/globals.rs",
        ],
        room_version_pattern=r'"(\d+)".to_owned\(\)|RoomVersionId::V(?:ersion)?(\d+)',
        default_room_version_paths=[
            "src/client_server.rs",
            "src/client_server/capabilities.rs",
            "src/database/globals.rs",
            "src/server_server.rs",
            "src/config/mod.rs",
            "src/config.rs",
        ],
        default_room_version_pattern=r'default: "(\d+)"|default: RoomVersionId::V(?:ersion)?(\d+),|default_room_version = RoomVersionId::V(?:ersion)?(\d+);|^ +RoomVersionId::V(?:ersion)?(\d+)$',
        earliest_commit="17a0b3430934fbb8370066ee9dc3506102c5b3f6",
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="Gridify Server",
        description="Corporate-level Unified communication server with support for several protocols: Matrix Home and Identity server and Grid Data Server",
        author="Kamax Sarl",
        maturity="Obsolete",
        language="Java",
        licence="AGPL-3.0-or-later",
        repository="https://gitlab.com/kamax-lu/software/gridify/server",
        room="#gridify-server:kamax.io",
        branch="master",
        spec_version_paths=[
            "src/main/java/io/kamax/grid/gridepo/http/handler/matrix/VersionsHandler.java",
            "src/main/java/io/kamax/grid/gridepo/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
            "src/main/java/io/kamax/gridify/server/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
        ],
        room_version_repo=None,
        room_version_paths=[
            "src/main/java/io/kamax/gridify/server/network/matrix/core/room/algo/BuiltinRoomAlgoLoader.java"
        ],
        room_version_pattern=r'versions\.add\("(\d+)"\);',
        default_room_version_paths=[
            "src/main/java/io/kamax/gridify/server/network/matrix/core/room/algo/RoomAlgos.java"
        ],
        default_room_version_pattern=r"RoomAlgoV(\d+)",
        earliest_commit=None,
        earliest_tag=None,
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
        repository="https://github.com/processone/ejabberd",
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="Harmony",
        description="A lighter-weight fork of the Dendrite homeserver for the Matrix protocol",
        author="Neil Alexander",
        maturity="Alpha",
        language="Go",
        licence="Apache-2.0",
        repository="https://github.com/neilalexander/harmony",
        room="#harmony:neilalexander.dev",
        branch="main",
        spec_version_paths=[
            "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
            "clientapi/routing/routing.go",
        ],
        room_version_repo="https://github.com/matrix-org/gomatrixserverlib",
        room_version_paths=["eventversion.go"],
        room_version_pattern=r"RoomVersionV(\d+)",
        default_room_version_paths=[
            "roomserver/version/version.go",
            "setup/config/config_roomserver.go",
        ],
        default_room_version_pattern=r"return gomatrixserverlib.RoomVersionV(\d+)|DefaultRoomVersion = gomatrixserverlib.RoomVersionV(\d+)",
        earliest_commit="6d1087df8dbd7982e7c7ad2f16b17588562c4048",
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="HG HomeServer",
        description="Minimal Matrix HomeServer written in TypeScript",
        author="Jaakko Heusala",
        maturity="Alpha",
        language="TypeScript",
        licence="MIT",
        repository="https://github.com/heusalagroup/hghs",
        room=None,
        branch="main",
        spec_version_paths=[],
        room_version_repo="https://github.com/heusalagroup/fi.hg.matrix",
        room_version_paths=["types/MatrixRoomVersion.ts"],
        room_version_pattern=r"MatrixRoomVersion\.V(\d+)",
        # TODO Should use room_version_repo.
        default_room_version_paths=["server/MatrixServerService.ts"],
        default_room_version_pattern=r"defaultRoomVersion : MatrixRoomVersion = MatrixRoomVersion\.V(\d+)",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="himatrix",
        description="[wip] matrix homeserver implementation",
        author="himanoa",
        maturity="Unstarted",
        language="Rust",
        licence="",
        repository="https://github.com/himanoa/himatrix",
        room=None,
        branch="master",
        spec_version_paths=["client-server-api/src/routes/versions.rs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="Insomnium",
        description="A Matrix homeserver implementation.",
        author="",
        maturity="Unstarted",
        language="C#",
        licence="GPL-3.0",
        repository="https://github.com/BerndSchmecka/Insomnium",
        room=None,
        branch="production",
        spec_version_paths=["Insomnium/src/Insomnium/Program.cs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="lomatia",
        description="Experimental Matrix homeserver written in Rust",
        author="LEARAX, vpzomtrrfrt",
        maturity="Unstarted",
        language="Rust",
        licence="GPL-3.0",
        repository="https://github.com/birders/lomatia",
        room=None,
        branch="master",
        spec_version_paths=["src/server_administration.rs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="MagnetHS",
        description="A new breed of homeserver for matrix.org",
        author="Half-Shot",
        maturity="Obsolete",
        language=".NET Core 2.0",
        licence="MIT",
        repository="https://github.com/Half-Shot/MagnetHS",
        room=None,
        branch="master",
        spec_version_paths=[
            "HalfShot.MagnetHS/Services/ClientServerAPIService/ClientServerAPI.cs"
        ],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="neuron",
        description="typescript matrix homeserver implementation",
        author="Michael",
        maturity="Unstarted",
        language="TypeScript",
        licence="MIT",
        repository="https://github.com/avatus/neuron",
        room=None,
        branch="master",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="plasma",
        description="Plasma is an open-source Matrix server implementation.",
        author="",
        maturity="Obsolete",
        language="Elixir",
        licence="Apache-2.0",
        repository="https://gitlab.com/plasmahs/plasma",
        room=None,
        branch="main",
        spec_version_paths=[],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="plasma_old",
        description="",
        author="",
        maturity="Obsolete",
        language="Elixir",
        licence="AGPL-3.0",
        repository="https://gitlab.com/plasmahs/plasma_old",
        room=None,
        branch="master",
        spec_version_paths=[
            "lib/matrix_client_api/controllers/versions.ex",
            "lib/matrix_client_api/controllers/versions_controller.ex",
        ],
        room_version_repo=None,
        room_version_paths=["config/config.exs"],
        # Note that \d doesn't seem to work in [] for grep.
        room_version_pattern=r"supported_room_versions: ~w\(([0-9 ]+)\)",
        default_room_version_paths=["config/config.exs"],
        default_room_version_pattern=r'default_room_version: "(\d+)"',
        earliest_commit=None,
        earliest_tag=None,
    ),
    # Is polyjuice server meant to be a full homeserver?
    ProjectMetadata(
        name="Polyjuice Server",
        description="Helper functions for creating a Matrix server",
        author="Hubert Chathi",
        maturity="Alpha",
        language="Elixir",
        licence="Apache-2.0",
        repository="https://gitlab.com/polyjuice/polyjuice_server",
        room=None,
        branch="develop",
        spec_version_paths=["lib/polyjuice/server/plug/client.ex"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="Ruma",
        description="A Matrix homeserver",
        author="Jimmy Cuadra",
        maturity="Obsolete",
        language="Rust",
        licence="MIT",
        repository="https://github.com/ruma/homeserver",
        room="#ruma:matrix.org",
        branch="master",
        spec_version_paths=["src/api/r0/versions.rs"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="Serverless-Matrix",
        description="A serverless (nodejs functions cloudflare workers, lambda, gcp functions...) matrix homeserver",
        author="Justin Parra",
        maturity="Unstarted",
        language="JavaScript",
        licence="ISC",
        repository="https://github.com/parrajustin/Serverless-Matrix",
        room=None,
        branch="main",
        spec_version_paths=["Identity/src/version.ts"],
        room_version_repo=None,
        room_version_paths=[],
        room_version_pattern="",
        default_room_version_paths=[],
        default_room_version_pattern="",
        earliest_commit=None,
        earliest_tag=None,
    ),
    ProjectMetadata(
        name="thurim",
        description="A Matrix homeserver implementation written in Elixir that has just begun",
        author="Serra Allgood",
        maturity="Alpha",
        language="Rust",
        licence="AGPL-3.0",
        repository="https://github.com/serra-allgood/thurim",
        room=None,
        branch="main",
        spec_version_paths=["lib/thurim_web/controllers/matrix/versions_controller.ex"],
        room_version_repo=None,
        room_version_paths=["config/config.exs"],
        # Note that \d doesn't seem to work in [] for grep.
        room_version_pattern=r"supported_room_versions: ~w\(([0-9 ]+)\)",
        default_room_version_paths=["config/config.exs"],
        default_room_version_pattern=r'default_room_version: "(\d+)"',
        earliest_commit=None,
        earliest_tag=None,
    ),
]


# Other projects with essentially no commits:
_OTHER_PROJECTS = [
    "https://github.com/pendula95/jmatrix",
    "https://github.com/SkaveRat/gopheus",
    "https://github.com/binex-dsk/calcium",
]

# Known proprietary servers: hungryserv


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
        server_name = server["name"].lower()

        if server_name in INVALID_PROJECTS:
            print(f"Ignoring {server_name}.")
            continue

        if server_name not in ADDITIONAL_METADATA:
            print(f"No metadata for {server_name}, skipping.")
            continue

        yield ProjectMetadata(**server, **asdict(ADDITIONAL_METADATA[server_name]))

    yield from ADDITIONAL_PROJECTS
