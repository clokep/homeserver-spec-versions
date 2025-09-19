import subprocess
import re
from typing import Callable


def get_pattern_from_file(
    root: str,
    paths: list[str],
    pattern: str,
    parser: Callable[[str], set[str]] | None,
    to_ignore: list[str],
) -> set[str]:
    """
    Fetch the spec versions from one or more files.

    To get the valid version numbers and to ignore ones that are in comments we use
    a two-pass system:

    1. Use grep to find lines that contain potential version numbers.
    2. Strip comments "off" those lines, then search again to see if they
       have version numbers.
    """
    result = subprocess.run(
        [
            "grep",
            "--no-filename",
            "-E",
            pattern,
            *paths,
        ],
        capture_output=True,
        cwd=root,
    )

    versions = set()

    for line in result.stdout.decode("ascii").splitlines():
        # Strip comments.
        #
        # TODO This only handles line comments, not block comments.
        line = re.split(r"#|//", line)[0]

        # Search again for the versions.
        matches = re.findall(pattern, line)
        matches = [
            parser(match)
            if parser
            else [m for m in match if m]
            if isinstance(match, tuple)
            else [match]
            for match in matches
        ]
        # Flatten the list of lists
        versions.update([m for ma in matches for m in ma])

    # Ignore some versions that are "bad".
    for v in to_ignore:
        versions.discard(v)

    return versions
