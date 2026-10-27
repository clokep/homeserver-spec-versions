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


def map_language_to_comment_styles(language: str) -> list[str] | None:
    """Maps a language to the comment styles supported."""
    language = language.strip()

    if language in ("C", "C#", "C++", "Go", "Java", "JavaScript", "Kotlin", "Rust", "Scala", "TypeScript"):
        return ["//"]
    elif language in ("Elixir", "Erlang"):
        return ["#", "--"]
    elif language == "Haskell":
        return ["--"]
    elif language == "OCaml":
        # OCaml doesn't have line comments.
        return ["(*"]
    if language == "Python":
        return ["#"]

    # Note that we're missing a language.
    raise ValueError(f"Unsupported language detected: {language}")


def parse_matches(
    finder: PatternFinder, lines: list[str], comment_styles: list[str] | None = None
) -> set[str]:
    """Apply parser to regex matches, return set of results."""
    results = set()
    for line in lines:
        if comment_styles:
            # Strip comments.
            #
            # TODO This only handles line comments, not block comments.
            pattern = r"(^|\s)(" + "|".join(re.escape(s) for s in  comment_styles) + ")"
            line = re.split(pattern, line)[0]
        # Search again for the results.
        matches = re.findall(finder.pattern, line)
        matches = [
            finder.parser(match)
            if finder.parser
            else [m for m in match if m]
            if isinstance(match, tuple)
            else [match]
            for match in matches
        ]
        # Flatten the list of lists
        results.update(*matches)

    # Ignore some versions that are "bad".
    if finder.to_ignore:
        for r in finder.to_ignore:
            results.discard(r)

    return results
