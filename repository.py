import itertools
from datetime import datetime, timezone, timedelta
from functools import cmp_to_key
from pathlib import Path
import os.path
from typing import Iterator, Iterable
from finders import get_pattern_from_file

import git.cmd
from git import Repo, Commit

from projects import (
    PatternFinder,
    SubRepoFinder,
    SubModuleFinder,
    ProjectMetadata,
)


def _check_refspecs(repo: Repo) -> bool:
    """Add a fetch refspec for pull requests as some sub-repos target pull requests of other repos."""
    url = next(repo.remote().urls)
    if "github.com" in url:
        reader = repo.config_reader("repository")
        refspecs = reader.get_values('remote "origin"', "fetch")
        if len(refspecs) < 2:
            with repo.config_writer("repository") as writer:
                writer.add_value(
                    'remote "origin"',
                    "fetch",
                    "+refs/pull/*:refs/remotes/origin/pull/*",
                )
            return True
    return False


def get_repo(name: str, remote: str) -> Repo:
    """
    Given a project name and the remote git URL, return a tuple of file path and git repo.

    This will either clone the project (if it doesn't exist) or fetch from the
    remote to update the repository.
    """
    repo_dir = Path(".") / ".projects" / name.lower()
    if not os.path.isdir(repo_dir):
        repo = Repo.clone_from(remote, repo_dir)

        # Fetch again if the additional refspec is added.
        if _check_refspecs(repo):
            repo.remote().fetch()
    else:
        repo = Repo(repo_dir)
        _check_refspecs(repo)
        repo.remote().fetch()

    return repo


def checkout(repo: Repo, commit: str | Commit) -> None:
    """Checkout a specific commit or refspec."""
    # Checkout this commit (why is this so hard?).
    repo.head.reference = commit
    repo.head.reset(index=True, working_tree=True)


def get_modified_commits(
    repo: Repo,
    project: ProjectMetadata,
    finders: list[PatternFinder | SubRepoFinder] | None,
) -> Iterable[Commit]:
    """
    Find the ordered list of commits that have modifications based on a set of finders.

    The commits from each finder are combined and re-ordered.
    """

    if not finders:
        return []

    # A list of iterators, each which contain
    all_commits_iterators = []
    for finder in finders:
        if isinstance(finder, PatternFinder):
            commits_iterator = _get_commits_by_paths(project, repo, finder.paths)
        elif isinstance(finder, SubRepoFinder):
            commits_iterator = _get_commits_by_subrepo(project, repo, finder)
        else:
            raise ValueError(f"Unsupported finder: {finder.__class__.__name__}")

        all_commits_iterators.append(commits_iterator)

    # Compare the commits to order them and ensure there are no duplicates.
    if len(all_commits_iterators) > 1:
        # De-duplicate commits.
        commit_map = {c.hexsha: c for c in itertools.chain(*all_commits_iterators)}

        return sorted(
            commit_map.values(),
            key=cmp_to_key(lambda a, b: -1 if repo.is_ancestor(a, b) else 1),
        )
    elif len(all_commits_iterators) == 1:
        return all_commits_iterators[0]

    return []


def _get_commits_by_paths(
    project: ProjectMetadata, repo: Repo, paths: list[str]
) -> list[Commit]:
    """
    Get the commits where a file may have been modified.
    """

    # Calculate the set of versions each time these files were changed, including
    # the earliest commit, if one exists.
    commits = list(
        repo.iter_commits(
            f"{project.earliest_commit}~..origin/{project.branch}"
            if project.earliest_commit
            else f"origin/{project.branch}",
            paths=paths,
            reverse=True,
            # Follow the development branch through merges (i.e. use dates that
            # changes are merged instead of original commit date).
            first_parent=True,
        )
    )
    if project.earliest_commit and (
        not commits or commits[0].hexsha != project.earliest_commit
    ):
        commits.insert(0, repo.commit(project.earliest_commit))
    return commits


def get_pattern_from_subrepo(repo: Repo, finder: SubRepoFinder) -> set[str]:
    # Get the sub-repository.
    sub_repo = get_repo(finder.repository.split("/")[-1], finder.repository)

    # The commit to checkout in the sub-repository.
    sub_repo_commit = None

    if isinstance(finder.commit_finder, PatternFinder):
        commits = get_pattern_from_file(
            repo.working_dir,
            finder.commit_finder.paths,
            finder.commit_finder.pattern,
            finder.commit_finder.parser,
            [],
        )

        if len(commits) > 1:
            raise ValueError("Unexpected number of commits: {commits}")
        elif len(commits) == 1:
            sub_repo_commit = next(iter(commits))

    elif isinstance(finder.commit_finder, SubModuleFinder):
        # The commit of the sub-repo is found via the submodule path.
        # Find the sub-module information, if it exists.
        sub_module = next(
            (s for s in repo.submodules if s.path == finder.commit_finder.path),
            None,
        )
        if sub_module:
            sub_repo_commit = sub_module.hexsha

    else:
        raise ValueError(
            f"Unsupported commit finder: {finder.commit_finder.__class__.__name__}"
        )

    # No commit was found, sub-repo must not exist.
    if not sub_repo_commit:
        return set()

    checkout(sub_repo, sub_repo_commit)

    return get_pattern_from_file(
        sub_repo.working_dir,
        finder.finder.paths,
        finder.finder.pattern,
        finder.finder.parser,
        [],
    )


def _get_commits_by_subrepo(
    project: ProjectMetadata,
    repo: Repo,
    finder: SubRepoFinder,
) -> Iterator[Commit]:
    """Get the commits which a referenced sub-repository was modified."""

    if isinstance(finder.commit_finder, PatternFinder):
        # The commit of the sub-repo is found via the pattern.
        yield from _get_commits_by_paths(project, repo, finder.commit_finder.paths)

    elif isinstance(finder.commit_finder, SubModuleFinder):
        # The commit of the sub-repo is found via the submodule path.
        yield from _get_commits_by_paths(project, repo, [finder.commit_finder.path])

    else:
        raise ValueError(
            f"Unsupported commit finder: {finder.commit_finder.__class__.__name__}"
        )


def get_tag_datetime(tag: git.TagReference) -> datetime:
    """
    Generate a datetime from a tag.

    This prefers the tagged date, but falls back to the commit date.
    """
    if tag.tag is None:
        return tag.commit.committed_datetime
    return datetime.fromtimestamp(
        tag.tag.tagged_date,
        tz=timezone(offset=timedelta(seconds=-tag.tag.tagger_tz_offset)),
    )


def get_tag_from_commit(git_cmd: git.Git, commit: str) -> str | None:
    """Find the first tag which contains a commit."""
    # Resolve the commit to the *next* tag. Sorting by creatordate will use the
    # tagged date for annotated tags, otherwise the commit date.
    tags = git_cmd.execute(
        ("git", "tag", "--sort=creatordate", "--contains", commit),
        with_extended_output=False,
        as_process=False,
        stdout_as_string=True,
    ).splitlines()
    # TODO Hack for Dendrite to remove the helm-dendrite-* tags.
    tags = [t for t in tags if not t.startswith("helm-dendrite-")]
    if tags:
        return tags[0]
    return None
