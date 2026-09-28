import re
from collections.abc import Callable
from dataclasses import dataclass

ParserType = Callable[[str], set[str] | list[str]]


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
    #
    # This is called with a tuple of capturing groups from pattern.
    parser: ParserType | None = None

    # Invalid results that should be ignored.
    to_ignore: list[str] | None = None


@dataclass
class SubModuleFinder:
    # The path the submodule gets checked out at.
    path: str


@dataclass
class SubRepoFinder:
    # A separate repo to search in.
    repository: str

    # The finder to get the git hash to checkout from the main repository.
    commit_finder: PatternFinder | SubModuleFinder

    # The finder to use to get the desired information from the sub-repository.
    finder: PatternFinder


@dataclass
class SpecVersionFinder(PatternFinder):
    pattern: str = r"[vr]\d+(?:\.\d+)+"


def parse_matches(
    pattern: str,
    lines: list[str],
    parser: ParserType | None = None,
    to_ignore: list[str] | None = None,
) -> set[str]:
    """Apply parser to regex matches, return set of results."""
    results = set()
    for line in lines:
        # Strip comments.
        #
        # TODO This only handles line comments, not block comments.
        line = re.split(r"(^|\s)(#|//)", line)[0]
        # Search again for the results.
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
        results.update(*matches)

    # Ignore some versions that are "bad".
    if to_ignore:
        for r in to_ignore:
            results.discard(r)

    return results
