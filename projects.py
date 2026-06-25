import hashlib
import inspect
import os.path
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterator
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import tomllib

from data import ManualProjectData, Maturity
from finders import PatternFinder, SpecVersionFinder, SubModuleFinder, SubRepoFinder
from manual_projects import generate_synapse_pro
from project_finders import (
    ConduitFinders,
    ConduwuitFinders,
    ContinuwuityFinders,
    DendriteFinders,
    Finders,
    SynapseFinders,
    SynapseLegacyFinders,
)

SERVER_METADATA_URL = "https://raw.githubusercontent.com/matrix-org/matrix.org/main/content/ecosystem/servers/servers.toml"


def parse_elixir_range_operator(s: str) -> set[str]:
    """Parse a range operator in Elixir, e.g. 3..5 should become {3, 4, 5}."""
    return set(map(str, range(*map(int, s.split(".."))))) | {s.split("..")[1]}


@dataclass
class ServerMetadata:
    # From the TOML file.
    name: str
    description: str
    author: str
    maturity: Maturity
    language: str
    licence: str
    repository: str
    room: str | None = None


@dataclass
class ForkInfo:
    # Project name this is forked from.
    name: str | None

    # Date of the last commit in the project this was forked from.
    #
    # This is calculated automatically as the parent of earliest_commit, if available.
    date: datetime | None = None

    # True if the fork merged back to main project.
    merged_back: bool = False


@dataclass
class CommitInfo:
    # The earliest commit to consider.
    #
    # Useful for forks where the project contains many old commits.
    earliest_commit: str | None = None

    # The earliest commit to consider.
    #
    # Useful for if a project is archived and has documentation commits much later
    # than the last real commit.
    latest_commit: str | None = None

    # The earliest tag to consider. If not given, the earliest tag which contains
    # the earliest commit is used. If there's no earliest commit, then the earliest
    # tag is used.
    #
    # Note that earlier tags might exist in the repo due to forks or other reasons.
    earliest_tag: str | None = None


@dataclass
class AdditionalMetadata(Finders):
    # The branch which has the latest commit.
    branch: str

    # Override earliest/latest commit information.
    commits: CommitInfo | None

    # Project this is forked from.
    forked_from: ForkInfo | None

    # True to process updates, false to use what's currently in the JSON file.
    process_updates: bool


@dataclass
class ProjectMetadata(ServerMetadata, AdditionalMetadata):
    def get_project_hash(self) -> str:
        props = asdict(self)

        # Replace some references to memory locations.
        for prop_name in [
            "spec_version_finders",
            "room_version_finders",
            "default_room_version_finders",
        ]:
            prop = props[prop_name]
            if not prop:
                continue

            for serialized_finder, finder in zip(prop, getattr(self, prop_name)):
                if isinstance(finder, SubRepoFinder):
                    if (
                        isinstance(finder.commit_finder, PatternFinder)
                        and finder.commit_finder.parser is not None
                    ):
                        serialized_finder["commit_finder"]["parser"] = (
                            inspect.getsource(finder.finder.parser).strip()
                        )

                    if finder.finder.parser is not None:
                        serialized_finder["finder"]["parser"] = inspect.getsource(
                            finder.finder.parser
                        ).strip()

                if isinstance(finder, PatternFinder) and finder.parser is not None:
                    serialized_finder["parser"] = inspect.getsource(
                        finder.parser
                    ).strip()

        return hashlib.md5(str(props).encode()).hexdigest()


# Projects to ignore.
INVALID_PROJECTS = {
    # Dendron is essentially a reverse proxy, not a homeserver.
    "dendron",
}


# Constants.
ADDITIONAL_METADATA = {
    "bullettime": AdditionalMetadata(
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "conduit": AdditionalMetadata(
        branch="next",
        spec_version_finders=ConduitFinders.spec_version_finders,
        room_version_finders=ConduitFinders.room_version_finders,
        default_room_version_finders=ConduitFinders.default_room_version_finders,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "conduwuit": AdditionalMetadata(
        branch="main",
        spec_version_finders=ConduwuitFinders.spec_version_finders,
        room_version_finders=ConduwuitFinders.room_version_finders,
        default_room_version_finders=ConduwuitFinders.default_room_version_finders,
        commits=CommitInfo(earliest_commit="40908b24e74bda4c80a5a6183602afcc0c04449b"),
        forked_from=ForkInfo(name="conduit"),
        process_updates=False,
    ),
    "continuwuity": AdditionalMetadata(
        branch="main",
        spec_version_finders=ContinuwuityFinders.spec_version_finders,
        room_version_finders=ContinuwuityFinders.room_version_finders,
        default_room_version_finders=ContinuwuityFinders.default_room_version_finders,
        commits=CommitInfo(earliest_commit="e054a56b3286a6fb3091bedd5261089435ed26d1"),
        forked_from=ForkInfo(name="conduwuit"),
        process_updates=True,
    ),
    "construct": AdditionalMetadata(
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["ircd/json.cc", "modules/client/versions.cc"],
                # Construct declares a r2.0.0, which never existed.
                to_ignore=["r2.0.0"],
            )
        ],
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
        ],
        commits=CommitInfo(
            # Earlier commits/tags from charybdis.
            earliest_commit="b592b69b8670413340c297e5a41caf153d832e57",
        ),
        forked_from=None,
        process_updates=True,
    ),
    "dendrite": AdditionalMetadata(
        branch="main",
        spec_version_finders=DendriteFinders.spec_version_finders,
        room_version_finders=DendriteFinders.room_version_finders,
        default_room_version_finders=DendriteFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="6bfe946bd2d82db12c1e49918612cc3d7139b8ce",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="dendrite-legacy"),
        process_updates=True,
    ),
    "jsynapse": AdditionalMetadata(
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "ligase": AdditionalMetadata(
        branch="develop",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/github.com/matrix-org/dendrite/clientapi/routing/routing.go",
                    "proxy/routing/routing.go",
                ]
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=CommitInfo(
            earliest_commit="bde8bc21a45a9dcffaaa812aa6a5a5341bca5f42",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="dendrite-legacy"),
        process_updates=True,
    ),
    "maelstrom": AdditionalMetadata(
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/server/handlers/admin.rs",
                    "crates/maelstrom-api/src/handlers/versions.rs",
                ]
            ),
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "matrex": AdditionalMetadata(
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "web/controllers/client_versions_controller.ex",
                    "controllers/client/versions.ex",
                ]
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "mxhsd": AdditionalMetadata(
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/main/java/io/kamax/mxhsd/spring/client/controller/VersionController.java"
                ]
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "pallium": AdditionalMetadata(
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "synapse": AdditionalMetadata(
        branch="develop",
        spec_version_finders=SynapseFinders.spec_version_finders,
        room_version_finders=SynapseFinders.room_version_finders,
        default_room_version_finders=SynapseFinders.default_room_version_finders,
        commits=CommitInfo(
            # Earlier commits/tags from Apache Synapse.
            earliest_commit="230decd5b8deea78674f92b2c0c11bd41090470a",
        ),
        forked_from=ForkInfo(name="synapse-legacy"),
        process_updates=True,
    ),
    "transform": AdditionalMetadata(
        branch="master",
        spec_version_finders=[SpecVersionFinder(paths=["config.json"])],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    "telodendria": AdditionalMetadata(
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["src/Routes/RouteMatrix.c", "src/Routes/RouteVersions.c"]
            )
        ],
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
        commits=None,
        forked_from=None,
        process_updates=False,
    ),
    "tuwunel": AdditionalMetadata(
        branch="dev",
        spec_version_finders=ConduitFinders.get_spec_version_finders(
            ["src/api/client/unversioned.rs", "src/api/client/versions.rs"]
        ),
        room_version_finders=ConduitFinders.get_room_version_finders(
            ["src/core/info/room_version.rs", "src/core/config/room_version.rs"]
        ),
        default_room_version_finders=ConduwuitFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="ce6e5e48de2a3580e17609f382cd4520fb6d8c63",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="conduwuit"),
        process_updates=True,
    ),
}

# Maybe https://github.com/lilyanavalley/264e.org?
# RasmusRendal/smh
# tcpipuk/hammerhead
# Zion's Gate https://matrix.to/#/!4YgPCZyvXlfgjRhD-4N3CfvTgVwMQ5hKq-qmouH_R-8/$p7NuDUKG8i-UyqgkBylTcQTEzQUpfBXKsPuEqqzP4oU?via=element.io&via=matrix.org&via=mozilla.org
ADDITIONAL_PROJECTS = [
    ProjectMetadata(
        name="architex",
        description="A Matrix homeserver written in Elixir",
        author="Pim Kunis",
        maturity=Maturity.Obsolete,
        language="Elixir",
        licence="AGPL-3.0",
        repository="https://gitlab.com/pizzapim/architex",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["lib/architex_web/client/controllers/info_controller.ex"]
            )
        ],
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="arrow",
        description="An implementation of the matrix API spec in Haskell",
        author="MaT1g3R",
        maturity=Maturity.Unstarted,
        language="Haskell",
        licence="AGPL-3.0-or-later",
        repository="https://github.com/MaT1g3R/arrow",
        room=None,
        branch="master",
        spec_version_finders=[SpecVersionFinder(paths=["src/Versions.hs"])],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="axiom",
        description="Python Matrix Homeserver implementation aimed for easy prototyping and experimentation",
        author="Jonathan de Jong",
        maturity=Maturity.Unstarted,
        language="Python",
        licence="EUPL-1.2",
        repository="https://github.com/ShadowJonathan/Axiom",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="axon",
        description="High-performance Matrix homeserver written in Rust",
        author="mm-goli1386",
        maturity=Maturity.Unstarted,
        language="Rust",
        licence="AGPL-3.0",
        repository="https://github.com/mm-goli1386/Axon",
        room=None,
        branch="main",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="babbleserv",
        description="Babbleserv is a Matrix homeserver built on top of FoundationDB",
        author="Beeper",
        maturity=Maturity.Alpha,
        language="Go",
        licence="AGPL-3.0",
        repository="https://github.com/beeper/babbleserv",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(paths=["internal/routes/client/client.go"])
        ],
        room_version_finders=DendriteFinders.room_version_finders,
        default_room_version_finders=[
            PatternFinder(
                paths=["babbleserv/internal/routes/client/room_create.go"],
                pattern=r'defaultRoomVersion = "(\d+)"',
            )
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="bromal",
        description="A lightweight opensource messaging server, that uses the Matrix protocol",
        author="Igorj Gorjaĉev",
        maturity=Maturity.Alpha,
        language="Elixir",
        licence="AGPL-3.0-or-later",
        repository="https://code.bromal.im/main/bromal",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "lib/bromal_api/matrix/client/versions.ex",
                    "lib/bromal_client/matrix/client/versions.ex",
                ]
            )
        ],
        room_version_finders=[
            PatternFinder(
                paths=["lib/bromal_client/matrix/client/capabilities.ex"],
                pattern=r'"(\d+)" => "stable"',
            ),
            PatternFinder(
                paths=["lib/bromal/rooms/versions.ex"],
                pattern=r"Versions\.Version(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["lib/bromal_client/matrix/client/capabilities.ex"],
                pattern=r'"default" => "(\d+)"',
            ),
            PatternFinder(
                paths=["lib/bromal/rooms/versions/version10.ex"],
                pattern=r"def default.+: true",
                parser=lambda s: {"10"},
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="calyx",
        description="A soft fork of Synapse",
        author="Helix K",
        maturity=Maturity.Beta,
        language="Python",
        licence="AGPL-3.0",
        repository="https://leakedsynapsepro.nhjkl.com/matrix/calyx",
        room=None,
        branch="master",
        spec_version_finders=SynapseFinders.spec_version_finders,
        # calyx did not include the Rust rewrite of room versions.
        room_version_finders=SynapseLegacyFinders.room_version_finders,
        default_room_version_finders=SynapseFinders.default_room_version_finders,
        commits=None,
        forked_from=ForkInfo(
            "synapse",
            # TODO Find this automatically.
            # git show v1.145.0 on element-hq/synapse
            date=datetime(2026, 1, 13, 9, 29, 9, tzinfo=ZoneInfo("Canada/Mountain")),
        ),
        process_updates=True,
    ),
    ProjectMetadata(
        name="casniam",
        description="An experimental, modular, rust Matrix homeserver federation library. Currently mostly used as a test bed for ideas.",
        author="Erik Johnston",
        maturity=Maturity.Obsolete,
        language="Rust",
        licence="",
        repository="https://github.com/erikjohnston/casniam",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="coignet",
        description="A Matrix homeserver written in Rust",
        author="Marcus Medom Ryding",
        maturity=Maturity.Unstarted,
        language="Rust",
        licence="AGPL-3.0",
        repository="https://github.com/Magnap/coignet",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(paths=["src/endpoints/client_server/mod.rs"])
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="coordinate",
        description="Erlang based Matrix homeserver",
        author="Justin Wood",
        maturity=Maturity.Unstarted,
        language="Erlang",
        licence="Apache-2.0",
        repository="https://git.sr.ht/~ankhers/coordinate",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["apps/coordinate/src/coordinate_client_versions_h.erl"]
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="cortex",
        description="Cortex is a reference implementation of Matrix Home Server",
        author="Vedhavyas Singareddi",
        maturity=Maturity.Unstarted,
        language="Go",
        licence="Apache-2.0",
        repository="https://github.com/vedhavyas/cortex",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="cubby",
        description="A matrix homeserver backed by Apache Parquet through polars, because that's definitely a good idea.",
        author="Vedhavyas Singareddi",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="MIT",
        repository="https://github.com/SiliconSelf/cubby",
        room=None,
        branch="main",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="daberiba",
        description="Matrix homeserver",
        author="masak1yu",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="MIT",
        repository="https://github.com/masak1yu/daberiba",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(paths=["crates/server/src/api/client/versions.rs"]),
        ],
        room_version_finders=[
            PatternFinder(
                paths=["crates/server/src/api/client/capabilities.rs"],
                pattern=r'"(\d+)": "stable"',
            )
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["crates/server/src/api/client/capabilities.rs"],
                pattern=r'"default": "(\d+)"',
            )
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="dendrite-legacy",
        description="Dendrite is a second-generation Matrix homeserver written in Go!",
        author="Matrix.org team",
        maturity=Maturity.Beta,
        language="Go",
        licence="Apache-2.0",
        repository="https://github.com/matrix-org/dendrite",
        room=None,
        branch="main",
        spec_version_finders=DendriteFinders.spec_version_finders,
        room_version_finders=DendriteFinders.room_version_finders,
        default_room_version_finders=DendriteFinders.default_room_version_finders,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="dopamine",
        description="Matrix homeserver implementation written in Elixir",
        author="Aidan Noll",
        maturity=Maturity.Unstarted,
        language="Elixir",
        licence="BSD-2-Clause",
        repository="https://github.com/onixus74/Dopamine",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["apps/dopamine_web/lib/dopamine_web/views/info_view.ex"]
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="elatrix",
        description="Matrix server implementation attempt",
        author="MKenin / kirill-kruchkov",
        maturity=Maturity.Unstarted,
        language="Elixir",
        licence="",
        repository="https://github.com/elatrix/elatrix",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="exagon",
        description="Exagon is an open-source Matrix homeserver implementation built to be resilient, performant and simple to maintain and administer.",
        author="Nicolas Jouanin",
        maturity=Maturity.Alpha,
        language="Elixir",
        licence="Apache-2.0",
        repository="https://gitlab.com/ex_agon/exagon",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["lib/exagon_web/matrix/client/controllers/client_controller.ex"],
                to_ignore=["v1.0"],
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="ferretcannon",
        description="FERRETCANNON is an LLM-only implementation of The Matrix Specification in Kotlin/KTor.",
        author="Ed Geraghty",
        maturity=Maturity.Alpha,
        language="Kotlin",
        licence="YPL",
        repository="https://github.com/EdGeraghty/FERRETCANNON",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["src/main/kotlin/routes/client-server/client/ClientRoutes.kt"],
            ),
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "src/main/kotlin/routes/client-server/client/AuthRoutes.kt",
                    "src/main/kotlin/routes/client-server/client/ClientRoutes.kt",
                ],
                pattern=r'"default" to "(\d+)"|put\("(\d+)", "stable"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "src/main/kotlin/routes/client-server/client/AuthRoutes.kt",
                    "src/main/kotlin/routes/client-server/client/ClientRoutes.kt",
                ],
                pattern=r'"(\d+)" to "stable"|put\("default", "(\d+)"',
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="ferrix",
        description="A toy Matrix homeserver written in Rust, for me to learn more about the Matrix protocol",
        author="EliseZeroTwo",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="MIT",
        repository="https://gitlab.com/elise/ferrix",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(paths=["src/api/clientserver/standards.rs"])
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="fluctlight",
        description="Fluctlight is a playground for testing random ideas for speed improvements on a chat server with the Matrix protocol.",
        author="Andrei Vasiliu",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="Apache-2.0 OR MIT",
        repository="https://github.com/andreivasiliu/fluctlight",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="go-matrix-homeserver",
        description="",
        author="Vlad Tokarev",
        maturity=Maturity.Unstarted,
        language="Golang",
        licence="",
        repository="https://github.com/vlad-tokarev/go-matrix-homeserver",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="grapevine",
        description="Grapevine is a Matrix homeserver that was originally forked from Conduit 0.7.0. Eventually, Grapevine will be rewritten from scratch in a separate repository.",
        author="Charles Hall",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="Apache-2.0",
        repository="https://gitlab.computer.surgery/matrix/grapevine",
        room=None,
        branch="main",
        spec_version_finders=ConduitFinders.spec_version_finders,
        room_version_finders=ConduitFinders.get_room_version_finders(
            ["src/service/globals.rs"]
        ),
        default_room_version_finders=ConduitFinders.get_default_room_version_finders(
            ["src/config.rs"]
        ),
        commits=CommitInfo(
            earliest_commit="17a0b3430934fbb8370066ee9dc3506102c5b3f6",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="conduit"),
        process_updates=False,
    ),
    ProjectMetadata(
        name="Gridify",
        description="Corporate-level Unified communication server with support for several protocols: Matrix Home and Identity server and Grid Data Server",
        author="Kamax Sarl",
        maturity=Maturity.Obsolete,
        language="Java",
        licence="AGPL-3.0-or-later",
        repository="https://gitlab.com/kamax-lu/software/gridify/server",
        room="#gridify-server:kamax.io",
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/main/java/io/kamax/grid/gridepo/http/handler/matrix/VersionsHandler.java",
                    "src/main/java/io/kamax/grid/gridepo/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
                    "src/main/java/io/kamax/gridify/server/network/grid/http/handler/matrix/home/client/VersionsHandler.java",
                ]
            )
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    # Note that ejabberd doesn't implement the Client-Server API, thus it doesn't declare
    # itself compatible with any particular versions.
    ProjectMetadata(
        name="ejabberd",
        description="Robust, Ubiquitous and Massively Scalable Messaging Platform (XMPP, MQTT, SIP Server)",
        author="ProcessOne",
        maturity=Maturity.Alpha,
        language="Erlang/OTP",
        licence="GPL-2.0-only",
        repository="https://github.com/processone/ejabberd",
        room=None,
        branch="master",
        # Check src/mod_matrix* for matrix related files.
        spec_version_finders=None,
        room_version_finders=[
            PatternFinder(
                paths=["src/mod_matrix_gw_room.erl"],
                pattern=r'binary_to_room_version\(<<"(\d+)">>\)',
            ),
        ],
        default_room_version_finders=None,
        # First commit & tag w/ Matrix support.
        commits=CommitInfo(
            earliest_commit="f44e23b8cc2c3ab7d1c36f702f00a6b5b947c5d0",
            earliest_tag=None,
        ),
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="feditrix",
        description="Feditrix Homeserver, a super-app-like for the fediverse (Mastodon, PeerTube, etc.) with Matrix included.",
        author="Andrei Jiroh Halili",
        maturity=Maturity.Unstarted,
        language="TypeScript",
        licence="AGPL-3.0-or-later",
        repository="https://gitlab.com/recaptime-dev-olddata/app",
        room=None,
        branch="main",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="gopheus",
        description="Testing goplang with Matrix.org Homeserver",
        author="SkaveRat",
        maturity=Maturity.Unstarted,
        language="Go",
        licence="GPL-2.0",
        repository="https://github.com/SkaveRat/gopheus",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Harmony",
        description="A lighter-weight fork of the Dendrite homeserver for the Matrix protocol",
        author="Neil Alexander",
        maturity=Maturity.Beta,
        language="Go",
        licence="Apache-2.0",
        repository="https://github.com/neilalexander/harmony",
        room="#harmony:neilalexander.dev",
        branch="main",
        spec_version_finders=DendriteFinders.spec_version_finders,
        room_version_finders=DendriteFinders.room_version_finders
        + [
            # Harmony re-vendored gomatrixserverlib
            PatternFinder(
                paths=["internal/gomatrixserverlib/eventversion.go"],
                pattern=r"RoomVersionV(\d+)",
            ),
        ],
        default_room_version_finders=DendriteFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="6d1087df8dbd7982e7c7ad2f16b17588562c4048",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="dendrite-legacy"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="HG",
        description="Minimal Matrix HomeServer written in TypeScript",
        author="Jaakko Heusala",
        maturity=Maturity.Alpha,
        language="TypeScript",
        licence="MIT",
        repository="https://github.com/heusalagroup/hghs",
        room=None,
        branch="main",
        spec_version_finders=None,
        room_version_finders=[
            SubRepoFinder(
                repository="https://github.com/heusalagroup/fi.hg.matrix",
                commit_finder=SubModuleFinder(path="src/fi/hg/matrix"),
                finder=PatternFinder(
                    paths=["types/MatrixRoomVersion.ts"],
                    pattern=r"MatrixRoomVersion\.V(\d+)",
                ),
            ),
        ],
        default_room_version_finders=[
            SubRepoFinder(
                repository="https://github.com/heusalagroup/fi.hg.matrix",
                commit_finder=SubModuleFinder(path="src/fi/hg/matrix"),
                finder=PatternFinder(
                    paths=["server/MatrixServerService.ts"],
                    pattern=r"defaultRoomVersion : MatrixRoomVersion = MatrixRoomVersion\.V(\d+)",
                ),
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="himatrix",
        description="[wip] matrix homeserver implementation",
        author="himanoa",
        maturity=Maturity.Unstarted,
        language="Rust",
        licence="",
        repository="https://github.com/himanoa/himatrix",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(paths=["client-server-api/src/routes/versions.rs"])
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Insomnium",
        description="A Matrix homeserver implementation.",
        author="Lucas Neuber",
        maturity=Maturity.Unstarted,
        language="C#",
        licence="GPL-3.0",
        repository="https://github.com/BerndSchmecka/Insomnium",
        room=None,
        branch="production",
        spec_version_finders=[
            SpecVersionFinder(paths=["Insomnium/src/Insomnium/Program.cs"])
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="jmatrix",
        description="Matrix homeserver written in Java/Quarkus",
        author="Lazar Bulić",
        maturity=Maturity.Unstarted,
        language="Java",
        licence="Apache-2.0",
        repository="https://github.com/pendula95/jmatrix",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="lomatia",
        description="Experimental Matrix homeserver written in Rust",
        author="LEARAX, vpzomtrrfrt",
        maturity=Maturity.Unstarted,
        language="Rust",
        licence="GPL-3.0",
        repository="https://github.com/birders/lomatia",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(paths=["src/server_administration.rs"])
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="MagnetHS",
        description="A new breed of homeserver for matrix.org",
        author="Half-Shot",
        maturity=Maturity.Obsolete,
        language=".NET Core 2.0",
        licence="MIT",
        repository="https://github.com/Half-Shot/MagnetHS",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "HalfShot.MagnetHS/Services/ClientServerAPIService/ClientServerAPI.cs"
                ]
            )
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="mascarene",
        description="Mascarene is an open source homeserver implementation of the Matrix protocol.",
        author="?",
        maturity=Maturity.Obsolete,
        language="Scala",
        licence="AGPL-3.0",
        repository="https://gitlab.com/mascarene/mascarene",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "homeserver/src/main/scala/org/mascarene/homeserver/matrix/server/client/ClientApiRoutes.scala"
                ]
            )
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="m-lstrom",
        description="M-lstorm is a continuon of matrix homeserver software maelstorm",
        author="Alexander Max Ranabel",
        maturity=Maturity.Obsolete,
        language="Rust",
        licence="Apache-2.0 OR MIT",
        repository="https://github.com/AlexanderMaxRanabel/m-lstrom",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/server/handlers/admin.rs",
                    "crates/maelstrom-api/src/handlers/versions.rs",
                ]
            ),
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=CommitInfo(earliest_commit="7554e295522a1008a40b8067d2ea5d042776c08e"),
        forked_from=ForkInfo(name="maelstrom"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="Matrices",
        description="Matrix.org homeservers",
        author="James Aimonetti",
        maturity=Maturity.Unstarted,
        language="Erlang",
        licence="MPL-2.0",
        repository="https://github.com/jamesaimonetti/kazoo-matrices",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    # potenial forks:
    # https://github.com/cf-remi/goodshab-matrix
    # https://github.com/linksever137/matrix-homeserver
    # https://github.com/jmbish04/matrix-homeserver
    ProjectMetadata(
        name="matrix-workers",
        description="Matrix Homeserver on Cloudflare Workers",
        author="Nick Kuntz",
        maturity=Maturity.Alpha,
        language="TypeScript",
        licence="MIT",
        repository="https://github.com/nkuntz1934/matrix-workers",
        room=None,
        branch="main",
        spec_version_finders=[SpecVersionFinder(paths=["main/src/api/versions.ts"])],
        room_version_finders=[
            PatternFinder(paths=["src/index.ts"], pattern=r"'(\d+)'")
        ],
        default_room_version_finders=[
            PatternFinder(paths=["src/index.ts"], pattern=r"default: '(\d+)'")
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="matrixon",
        description="Next-Generation Matrix Server with AI and Web3 Integration",
        author="arkCyber",
        maturity=Maturity.Unstarted,
        language="Rust",
        licence="MIT OR Apache-2.0",
        repository="https://github.com/arkCyber/Matrixon",
        room=None,
        branch="main",
        spec_version_finders=[SpecVersionFinder(paths=["src/lib.rs"])],
        room_version_finders=[
            PatternFinder(
                paths=["src/lib.rs"],
                pattern=r'"(\d+)": "stable"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["src/lib.rs"],
                pattern=r'"default": "(\d+)"',
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="messagehub",
        description="A P2P Matrix home server created using libp2p.",
        author="gdlol",
        maturity=Maturity.Alpha,
        language="C#",
        licence="MIT",
        repository="https://github.com/gdlol/MessageHub",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "MessageHub/ClientServerApi/VersionsController.cs",
                    "MessageHub/ClientServer/VersionsController.cs",
                ]
            )
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "MessageHub/ClientServerApi/CapabilitiesController.cs",
                    "MessageHub/ClientServer/CapabilitiesController.cs",
                ],
                pattern=r'\["(\d+)"\] = "stable"',
            )
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "MessageHub/ClientServerApi/CapabilitiesController.cs",
                    "MessageHub/ClientServer/CapabilitiesController.cs",
                ],
                pattern=r'\["default"\] = (\d+),',
            )
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="mocktrix",
        description="Partial implementation of a Matrix homeserver (work in progress)",
        author="Dirk Stolle",
        maturity=Maturity.Alpha,
        language="C#",
        licence="GPL-3.0",
        repository="https://github.com/striezel/Mocktrix",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "Mocktrix/client/Versions.cs",
                ]
            )
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="nebu",
        description="An enterprise-grade, Matrix-compatible chat server — Apache 2.0, no federation, horizontally scalable.",
        author="INNOQ",
        maturity=Maturity.Alpha,
        language="Go, Elixir",
        licence="Apache-2.0",
        repository="https://github.com/innoq/nebu",
        room=None,
        branch="main",
        spec_version_finders=[SpecVersionFinder(paths=["gateway/cmd/gateway/main.go"])],
        room_version_finders=[
            PatternFinder(
                paths=["gateway/cmd/gateway/main.go"], pattern=r'"(\d+)":"stable"'
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["gateway/cmd/gateway/main.go"],
                pattern=r'"default":"(\d+)"',
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="neuron",
        description="typescript matrix homeserver implementation",
        author="Michael",
        maturity=Maturity.Unstarted,
        language="TypeScript",
        licence="MIT",
        repository="https://github.com/avatus/neuron",
        room=None,
        branch="master",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="ocaml-matrix",
        description="Implementation of a matrix server in OCaml for MirageOS",
        author="Gwenaëlle Lecat",
        maturity=Maturity.Unstarted,
        language="OCaml",
        licence="ISC",
        repository="https://github.com/mirage/ocaml-matrix",
        room=None,
        branch="main",
        spec_version_finders=None,
        room_version_finders=[
            PatternFinder(
                paths=["ci-server/federation_routes.ml"],
                pattern=r'room_version = "(\d+)"',
            )
        ],
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="palpo",
        description="Palpo is a Matrix homeserver written in Rust",
        author="Chrislearn Young",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="Apache-2.0",
        repository="https://github.com/palpo-im/palpo",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "crates/server/src/routing/client/mod.rs",
                    "crates/server/src/routing/client.rs",
                ]
            )
        ],
        room_version_finders=[
            PatternFinder(
                paths=["crates/server/src/bl/mod.rs"],
                pattern=r"RoomVersionId::V(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["crates/server/src/config/server_config.rs"],
                pattern=r"RoomVersionId::V(\d+)",
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="persephone",
        description="A WIP experimental C++20 matrix server",
        author="MTRNord",
        maturity=Maturity.Alpha,
        language="C++",
        licence="AGPL-3.0",
        repository="https://github.com/MTRNord/persephone",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/webserver/client_server_api/c_s_api.hpp",
                    "src/webserver/client_server_api/ClientServerCtrl.cpp",
                ]
            )
        ],
        room_version_finders=[
            PatternFinder(
                paths=["src/utils/room_version.hpp"],
                pattern=r'supported_versions = {(?:"(\d+)"(?:, )?)+}',
            ),
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="peykon",
        description="A lightweight Matrix homeserver implementation written in C#.",
        author="Poulad",
        maturity=Maturity.Obsolete,
        language="C#",
        licence="MIT",
        repository="https://github.com/poulad/PeykOn",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "src/PeykOn/Controllers/2. API Standards/VersionsController.cs",
                ]
            ),
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="plasma",
        description="Plasma is an open-source Matrix server implementation.",
        author="",
        maturity=Maturity.Obsolete,
        language="Elixir",
        licence="Apache-2.0",
        repository="https://gitlab.com/plasmahs/plasma",
        room=None,
        branch="main",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="plasma_old",
        description="",
        author="",
        maturity=Maturity.Obsolete,
        language="Elixir",
        licence="AGPL-3.0",
        repository="https://gitlab.com/plasmahs/plasma_old",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "lib/matrix_client_api/controllers/versions.ex",
                    "lib/matrix_client_api/controllers/versions_controller.ex",
                ]
            )
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="radio_beam",
        description="A WIP Matrix homeserver, powered by the BEAM",
        author="Ben W.",
        maturity=Maturity.Alpha,
        language="Erlang",
        licence="AGPL-3.0",
        repository="https://github.com/Bentheburrito/radio_beam",
        room=None,
        branch="main",
        spec_version_finders=[SpecVersionFinder(paths=["config/config.exs"])],
        room_version_finders=[
            PatternFinder(
                paths=["config/config.exs"],
                pattern=r'Map\.new\((\d+\.\.\d+),|"(\d+)" => "stable"',
                # If the first matching group matches, then split on .. and convert to a range
                # of values. If the second group matches, it is just a single value.
                parser=lambda s: parse_elixir_range_operator(s[0]) if s[0] else {s[1]},
            ),
        ],
        default_room_version_finders=[
            PatternFinder(paths=["config/config.exs"], pattern=r'default: "(\d+)"'),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="relapse",
        description="",
        author="Patrick Cloke",
        maturity=Maturity.Alpha,
        language="Python",
        licence="Apache-2.0",
        repository="https://github.com/clokep/relapse",
        room=None,
        branch="develop",
        # These are equivalent to SynapseLegacyFinder with a different base path.
        spec_version_finders=[
            SpecVersionFinder(paths=["relapse/rest/client/versions.py"])
        ],
        room_version_finders=[
            PatternFinder(
                paths=["relapse/api/room_versions.py"],
                pattern=r"RoomVersions.V(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["relapse/config/server.py"],
                pattern=r'DEFAULT_ROOM_VERSION = "(\d+)',
            ),
        ],
        commits=CommitInfo(
            earliest_commit="fbd498c65cb0a0a82de4e63588d2c91c54bf24ee",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="synapse-legacy"),
        process_updates=True,
    ),
    # Note that RocketChat homeserver doesn't implement the Client-Server API, thus
    # it doesn't declare itself compatible with any particular versions.
    ProjectMetadata(
        name="RocketChat-homeserver",
        description="",
        author="",
        maturity=Maturity.Alpha,
        language="TypeScript",
        licence="?",
        repository="https://github.com/RocketChat/homeserver",
        room=None,
        branch="main",
        spec_version_finders=None,
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
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Ruma",
        description="A Matrix homeserver",
        author="Jimmy Cuadra",
        maturity=Maturity.Obsolete,
        language="Rust",
        licence="MIT",
        repository="https://github.com/ruma/homeserver",
        room="#ruma:matrix.org",
        branch="master",
        spec_version_finders=[SpecVersionFinder(paths=["src/api/r0/versions.rs"])],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="Serverless-Matrix",
        description="A serverless (nodejs functions cloudflare workers, lambda, gcp functions...) matrix homeserver",
        author="Justin Parra",
        maturity=Maturity.Unstarted,
        language="JavaScript",
        licence="ISC",
        repository="https://github.com/parrajustin/Serverless-Matrix",
        room=None,
        branch="main",
        spec_version_finders=[SpecVersionFinder(paths=["Identity/src/version.ts"])],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="signaller",
        description="A homeserver designed to be used on systems with limited resources.",
        author="signaller-matrix",
        maturity=Maturity.Alpha,
        language="Go",
        licence="MIT",
        repository="https://github.com/signaller-matrix/signaller",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(paths=["consts.go", "internal/consts.go"])
        ],
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="starnapse",
        description="element-hq/synapse with patches for starstruck.systems",
        author="star",
        maturity=Maturity.Beta,
        language="Python",
        licence="AGPL-3.0",
        repository="https://git.nexy7574.co.uk/star/starnapse",
        room=None,
        branch="starnapse",
        spec_version_finders=SynapseFinders.spec_version_finders,
        room_version_finders=SynapseFinders.room_version_finders,
        default_room_version_finders=SynapseFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="a862e7f8fd149f735c901e516d54038e5b35c9e3",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="synapse"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-ancient",
        description="The pre-release repo for synapse from git.openmarket.com/tng/synapse ",
        author="OpenMarket",
        maturity=Maturity.Obsolete,
        language="Python",
        licence="Apache-2.0",
        repository="https://github.com/matrix-org/synapse-ancient",
        room=None,
        branch="master",
        spec_version_finders=[],
        room_version_finders=[],
        default_room_version_finders=[],
        commits=CommitInfo(
            # Ignore "archaeological notes" from commit b1553fb57fe440c59538e093014d6fc232482176.
            latest_commit="578fb13fe6dca01c8542c5c2e25a1f43c96588d1"
        ),
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-beeper",
        description="Synapse with Beeper customizations",
        author="Beeper",
        maturity=Maturity.Stable,
        language="Python",
        licence="AGPL-3.0",
        repository="https://github.com/beeper/synapse",
        room=None,
        branch="beeper",
        spec_version_finders=SynapseFinders.spec_version_finders,
        room_version_finders=SynapseFinders.room_version_finders,
        default_room_version_finders=SynapseFinders.default_room_version_finders,
        commits=CommitInfo(earliest_commit="9c9759c22b7fa5def10366e64f6ceceffc229a20"),
        forked_from=ForkInfo(name="synapse"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-beeper-legacy",
        description="Beeper's legacy synapse fork",
        author="Beeper",
        maturity=Maturity.Obsolete,
        language="Python",
        licence="Apache-2.0",
        repository="https://github.com/beeper/synapse-legacy-fork",
        room=None,
        branch="beeper",
        spec_version_finders=SynapseLegacyFinders.spec_version_finders,
        room_version_finders=SynapseLegacyFinders.room_version_finders,
        default_room_version_finders=SynapseLegacyFinders.default_room_version_finders,
        commits=CommitInfo(earliest_commit="40fdd06ab6c55d8f38fca5d23f10be31bc5e054d"),
        forked_from=ForkInfo(name="synapse-legacy"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-dinsic",
        description="Synapse: Matrix reference homeserver (DINSIC/Tchap fork)",
        author="DINSIC",
        maturity=Maturity.Obsolete,
        language="Python",
        licence="Apache-2.0",
        repository="https://github.com/matrix-org/synapse-dinsic",
        room=None,
        branch="dinsic",
        spec_version_finders=SynapseLegacyFinders.spec_version_finders,
        room_version_finders=SynapseLegacyFinders.room_version_finders,
        default_room_version_finders=SynapseLegacyFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="3f79378d4bc27efd80e302f3c8c512ea41cbd395",
            # First tag in synapse-dinsic that is not in synapse.
            earliest_tag="dinsic_2019-09-19",
            # Ignore cleanup and archival notice.
            latest_commit="a694353ec4e59f9ba331a7aa691f22d49a415b0b",
        ),
        forked_from=ForkInfo(name="synapse-legacy", merged_back=True),
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-famedly",
        description="Fork of synapse by Famedly with patches.",
        author="Famedly",
        maturity=Maturity.Stable,
        language="Python",
        licence="AGPL-3.0",
        repository="https://github.com/famedly/synapse",
        room=None,
        branch="master",
        spec_version_finders=SynapseFinders.spec_version_finders,
        room_version_finders=SynapseFinders.room_version_finders,
        default_room_version_finders=SynapseFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="ab0a981c32509813e68ea9ffcd5a01960bc873a5",
        ),
        forked_from=ForkInfo(name="synapse-legacy"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="synapse-legacy",
        description="Matrix.org homeserver",
        author="Matrix.org team",
        maturity=Maturity.Stable,
        language="Python",
        licence="Apache-2.0",
        repository="https://github.com/matrix-org/synapse",
        room=None,
        branch="develop",
        spec_version_finders=SynapseLegacyFinders.spec_version_finders,
        room_version_finders=SynapseLegacyFinders.room_version_finders,
        default_room_version_finders=SynapseLegacyFinders.default_room_version_finders,
        # Earlier tags exist from DINSIC.
        commits=CommitInfo(earliest_tag="v0.0.0"),
        forked_from=ForkInfo("synapse-ancient"),
        process_updates=True,
    ),
    ProjectMetadata(
        name="thurim",
        description="A Matrix homeserver implementation written in Elixir that has just begun",
        author="Serra Allgood",
        maturity=Maturity.Alpha,
        language="Elixir",
        licence="AGPL-3.0",
        repository="https://github.com/serra-allgood/thurim",
        room="#thurim:matrix.org",
        branch="main",
        spec_version_finders=None,
        room_version_finders=None,
        default_room_version_finders=None,
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="thurim-old",
        description="A Matrix homeserver implementation written in Elixir that has just begun",
        author="Serra Allgood",
        maturity=Maturity.Alpha,
        language="Elixir",
        licence="AGPL-3.0",
        repository="https://github.com/serra-allgood/thurim-old",  # Fake repository so path is correct
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=["lib/thurim_web/controllers/matrix/versions_controller.ex"]
            )
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
        commits=None,
        forked_from=None,
        process_updates=False,  # History was stomped on and is no longer available
    ),
    ProjectMetadata(
        name="venator",
        description='"Matrix Venator - versatile capital Matrix homeserver written from scratch in mautrix-go',
        author="nexy",
        maturity=Maturity.Alpha,
        language="Go",
        licence="MPL-2.0",
        repository="https://codeberg.org/timedout/venator",
        room=None,
        branch="dev",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "nexserv/server/versions.go",
                    "nexserv/router/routes/client/versions.go",
                    "hammerhead/router/routes/client/versions.go",
                    "hammerhead/config/config.go",
                    "pkg/hammerhead/config/config.go",
                ]
            ),
            PatternFinder(
                paths=[
                    "pkg/hammerhead/config/consts.go",
                    "pkg/venatord/config/consts.go",
                    "internal/venatord/config/consts.go",
                ],
                pattern=r"mautrix.SpecV(\d+)",
                parser=lambda s: {f"v{s[0]}.{s[1:]}"},
            ),
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "hammerhead/router/routes/client/v3/createRoom.go",
                    "hammerhead/config/config.go",
                    "pkg/hammerhead/config/config.go",
                    "pkg/hammerhead/config/consts.go",
                    "pkg/venatord/config/consts.go",
                    "internal/venatord/config/consts.go",
                ],
                pattern=r"RoomV(\d+)",
            )
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "cmd/hammerhead/hammerhead.go",
                    "pkg/hammerhead/config/consts.go",
                    "pkg/venatord/config/consts.go",
                    "internal/venatord/config/consts.go",
                ],
                pattern=r"DefaultRoomVersion(?::| =) id\.RoomV(\d+)",
            )
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="vela",
        description="A self-hostable Matrix homeserver written in Rust.",
        author="sufforest",
        maturity=Maturity.Alpha,
        language="Rust",
        licence="Apache-2.0",
        repository="https://github.com/sufforest/vela",
        room=None,
        branch="main",
        spec_version_finders=[
            SpecVersionFinder(
                paths=[
                    "vela-api/src/discovery.rs",
                    "vela-api/src/directory/discovery.rs",
                ]
            ),
        ],
        room_version_finders=[
            PatternFinder(
                paths=[
                    "vela-api/src/capabilities.rs",
                    "vela-api/src/profile/capabilities.rs",
                ],
                pattern=r'"(\d+)": "stable"',
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=[
                    "vela-api/src/capabilities.rs",
                    "vela-api/src/profile/capabilities.rs",
                ],
                pattern=r'"default": "(\d+)"',
            ),
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="vona",
        description="Vona is a flazing bast 🌟, and semory mafe [matrix] implementation made in Python 🐍 for stability.",
        author="Helix K",
        maturity=Maturity.Alpha,
        language="Python",
        licence="Velicense",
        repository="https://leakedsynapsepro.nhjkl.com/matrix/vona",
        room=None,
        branch="master",
        spec_version_finders=[
            SpecVersionFinder(paths=["src/c2s.py"]),
            PatternFinder(
                paths=["src/c2s.py", "vona/client/__init__.py"],
                pattern=r"""f"(r0.{i}.0|v1.{i})" for i in range\((\d+), (\d+)\)""",
                parser=lambda s: (
                    {s[0].format(i=i) for i in range(int(s[1]), int(s[2]))}
                    if s
                    else set()
                ),
            ),
        ],
        room_version_finders=[
            PatternFinder(
                paths=["src/c2s.py", "vona/client/__init__.py"],
                pattern=r'"(\d+)": ?"stable"',
                to_ignore=["1337"],
            ),
            PatternFinder(
                paths=["vona/globals/room_versions.py"],
                pattern=r"V(\d+)",
            ),
        ],
        default_room_version_finders=[
            PatternFinder(
                paths=["src/c2s.py", "vona/client/__init__.py"],
                pattern=r'"default": ?"(\d+)"',
                to_ignore=["1337"],
            )
        ],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="worrywart",
        description="A Matrix Homeserver written with modern tools",
        author="Jason Little",
        maturity=Maturity.Alpha,
        language="Python",
        licence="",
        repository="https://forgejo.littlevortex.net/jason/worrywart",
        room=None,
        branch="main",
        spec_version_finders=[],
        room_version_finders=[],
        default_room_version_finders=[],
        commits=None,
        forked_from=None,
        process_updates=True,
    ),
    ProjectMetadata(
        name="zendrite",
        description=" An opinionated fork of element-hq/dendrite",
        author="Patrick Schratz",
        maturity=Maturity.Beta,
        language="Go",
        licence="AGPL-3.0-or-later OR Element Commercial License",
        repository="https://codefloe.com/pat-s/zendrite",
        room=None,
        branch="main",
        spec_version_finders=DendriteFinders.spec_version_finders,
        room_version_finders=DendriteFinders.room_version_finders
        + [
            # For a period github.com/jackmaninov/gomatrixserverlib was used to replace github.com/matrix-org/gomatrixserverlib
            # but this didn't have any impact on supported versions.
            SubRepoFinder(
                repository="https://codefloe.com/pat-s/gomatrixserverlib",
                commit_finder=PatternFinder(
                    paths=["go.mod"],
                    pattern=r"codefloe.com/pat-s/gomatrixserverlib (?:v0\.0\.0-\d+-([0-9a-f]+)|(v\d\.\d.\d))",
                ),
                finder=PatternFinder(
                    paths=["eventversion.go"], pattern=r"RoomVersionV(\d+)"
                ),
            ),
        ],
        default_room_version_finders=DendriteFinders.default_room_version_finders,
        commits=CommitInfo(
            earliest_commit="379ffff1f6673ddd39164f65194716d2e3c2ebb0",
            earliest_tag=None,
        ),
        forked_from=ForkInfo(name="dendrite"),
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
    #     merged_back=False,
    #     forked_from=None, forked_from_date=None,
    #     last_commit_date=datetime(),
    #     spec_version_dates_by_commit={},
    #     spec_version_dates_by_tag={},
    #     room_version_dates_by_commit={},
    #     room_version_dates_by_tag={},
    #     default_room_version_dates_by_commit={},
    #     default_room_version_dates_by_tag={},
    #     maturity=Maturity.Unstarted,
    # ),
    # https://git.spec.cat/Nyaaori/catalyst
    "catalyst": lambda: ManualProjectData(
        initial_release_date=None,
        # Pre-end of 2022-10-10:
        # https://matrix.org/blog/2023/01/03/matrix-community-year-in-review-2022
        # https://gitlab.com/famedly/conduit/-/commit/2b7c19835b65e4dd3a6a32466a9f45b06bf1ced2
        initial_commit_date=datetime(2022, 10, 10, 0, 0, 0),
        forked_date=datetime(2022, 10, 10, 0, 0, 0),
        merged_back=True,
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
        maturity=Maturity.Alpha,
    ),
    "hungryserv": lambda: ManualProjectData(
        initial_release_date=None,
        # Pre 2022-06-10: https://sumnerevans.com/posts/travel/2022-lisbon-and-paris/ericeira-portugal/
        initial_commit_date=datetime(2022, 6, 5, 0, 0, 0),
        forked_date=None,
        merged_back=False,
        forked_from=None,
        # It is being actively developed.
        last_commit_date=datetime.now(),
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag={},
        room_version_dates_by_commit={},
        room_version_dates_by_tag={},
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag={},
        maturity=Maturity.Beta,
    ),
    # Reddit is forked from dendrite, but there's little public information about this.
    # It does not have federation enabled.
    #
    # See matrix.redditspace.com
    "reddit": lambda: ManualProjectData(
        initial_release_date=None,
        # Earliest known reference: https://macaw.social/@wongmjane/109529583352532543
        initial_commit_date=datetime(2022, 12, 7, 0, 0, 0),
        forked_date=datetime(2022, 12, 7, 0, 0, 0),
        merged_back=False,
        forked_from="dendrite-legacy",
        # It is being actively developed.
        last_commit_date=datetime.now(),
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag={},
        room_version_dates_by_commit={},
        room_version_dates_by_tag={},
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag={},
        maturity=Maturity.Stable,
    ),
    "StashCat": lambda: ManualProjectData(
        initial_release_date=None,
        # Earliest known reference: https://element.io/blog/element-sponsors-public-sector-track-at-the-matrix-conference/
        initial_commit_date=datetime(2024, 8, 6, 0, 0, 0),
        forked_date=None,
        merged_back=False,
        forked_from=None,
        # It is being actively developed.
        last_commit_date=datetime.now(),
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag={},
        room_version_dates_by_commit={},
        room_version_dates_by_tag={},
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag={},
        maturity=Maturity.Stable,
    ),
    "synapse-pro": generate_synapse_pro,
    # TeamSpeak 5 added support for Matrix, which was then dropped in TeamSpeak 6.
    # Was this actually homegrown or is this a fork?
    "TeamSpeak5": lambda: ManualProjectData(
        initial_release_date=None,
        # Earliest known reference: https://x.com/teamspeak/status/1589621116032585728
        initial_commit_date=datetime(2022, 11, 7, 14, 9, 0),
        forked_date=None,
        merged_back=False,
        forked_from=None,
        # TeamSpeak 6 does not include Matrix support: https://github.com/teamspeak/teamspeak6-server/issues/31#issuecomment-3563104693
        # First release of TeamSpeak 6 beta: https://community.teamspeak.com/t/teamspeak-6-0-0-beta1-screen-camera-sharing-communities-design-overhaul/54925
        last_commit_date=datetime(2025, 1, 21, 15, 15, 0),
        spec_version_dates_by_commit={},
        spec_version_dates_by_tag={},
        room_version_dates_by_commit={},
        room_version_dates_by_tag={},
        default_room_version_dates_by_commit={},
        default_room_version_dates_by_tag={},
        maturity=Maturity.Alpha,
    ),
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

        server["maturity"] = Maturity(server["maturity"].lower())

        # Can't use asdict here since it recurses into inner classes.
        yield ProjectMetadata(**server, **ADDITIONAL_METADATA[server_name].__dict__)

    yield from ADDITIONAL_PROJECTS
