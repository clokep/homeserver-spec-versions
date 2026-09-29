import abc
import itertools
import os.path
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from functools import cmp_to_key
from pathlib import Path
from typing import Generic, TypeVar

from git import Commit, Repo, TagReference
from git.exc import GitCommandError

from finders import PatternFinder, SubModuleFinder, SubRepoFinder, parse_matches
from projects import ProjectMetadata

CommitType = TypeVar("CommitType")
TagType = TypeVar("TagType")


class Repository(Generic[CommitType, TagType], metaclass=abc.ABCMeta):
    def __init__(self, name: str, remote: str) -> None:
        """
        Given a project name and the remote git URL, return a tuple of file path and git repo.

        This will either clone the project (if it doesn't exist) or fetch from the
        remote to update the repository.
        """
        repo_dir = Path(".") / ".projects" / name.lower()
        self.working_dir = str(repo_dir)

    @classmethod
    def create(self, url: str):
        org, name = url.rsplit("/", maxsplit=2)[-2:]
        return GitRepository(f"{org}/{name}".lower(), url)

    @abc.abstractmethod
    def checkout(self, commit: str | CommitType) -> None:
        """Checkout a specific commit or refspec."""

    def get_modified_commits(
        self,
        project: ProjectMetadata,
        finders: list[PatternFinder | SubRepoFinder] | None,
    ) -> Iterable[CommitType]:
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
                commits_iterator = self._get_commits_by_paths(project, finder.paths)
            elif isinstance(finder, SubRepoFinder):
                commits_iterator = self._get_commits_by_subrepo(project, finder)
            else:
                raise TypeError(f"Unsupported finder: {finder.__class__.__name__}")

            all_commits_iterators.append(commits_iterator)

        # Compare the commits to order them and ensure there are no duplicates.
        if len(all_commits_iterators) > 1:
            return self._dedup_and_order_commits(all_commits_iterators)
        elif len(all_commits_iterators) == 1:
            return all_commits_iterators[0]

        return []

    @abc.abstractmethod
    def _dedup_and_order_commits(
        self, commits: list[Iterable[CommitType]]
    ) -> Iterable[CommitType]:
        """
        De-duplicate and order the commits from multiple iterators.
        """

    @abc.abstractmethod
    def _get_commits_by_paths(
        self, project: ProjectMetadata, paths: list[str]
    ) -> list[CommitType]:
        """
        Get the commits where a file may have been modified.
        """

    @abc.abstractmethod
    def extract_subrepo_versions(
        self, finder: SubRepoFinder, main_commit_hashes: list[str]
    ) -> dict[str, set[str]]:
        """
        Extract version patterns from a sub-repository at specific main-repo commits.

        For each main commit, resolves the sub-repo commit hash, then searches
        that sub-repo commit for version patterns.

        Returns: {main_commit_hash: set[versions]}
        """

    @abc.abstractmethod
    def map_main_to_subrepo_commit(
        self,
        main_commit_hash: str,
        commit_finder: PatternFinder | SubModuleFinder,
    ) -> str | None:
        """
        Extract sub-repo commit hash from a specific main commit.
        """

    def _get_commits_by_subrepo(
        self,
        project: ProjectMetadata,
        finder: SubRepoFinder,
    ) -> Iterator[CommitType]:
        """Get the commits which a referenced sub-repository was modified."""

        if isinstance(finder.commit_finder, PatternFinder):
            # The commit of the sub-repo is found via the pattern.
            yield from self._get_commits_by_paths(project, finder.commit_finder.paths)

        elif isinstance(finder.commit_finder, SubModuleFinder):
            # The commit of the sub-repo is found via the submodule path.
            yield from self._get_commits_by_paths(project, [finder.commit_finder.path])

        else:
            raise TypeError(
                f"Unsupported commit finder: {finder.commit_finder.__class__.__name__}"
            )

    @abc.abstractmethod
    def get_earliest_commit(self, project: ProjectMetadata) -> CommitType:
        """Get the earliest commit on the main branch."""

    @abc.abstractmethod
    def get_latest_commit(self, project: ProjectMetadata) -> CommitType:
        """Get the latest commit on the main branch."""

    @abc.abstractmethod
    def get_project_datetimes(
        self, project: ProjectMetadata
    ) -> tuple[datetime, datetime, datetime | None]:
        """Get some important dates for the project."""

    @abc.abstractmethod
    def get_earliest_tag(self, project: ProjectMetadata) -> TagType | None:
        """Get the earliest release of this project."""

    @abc.abstractmethod
    def get_commit_info(self, commit: CommitType) -> tuple[str, datetime]:
        """
        Get the sha and datetime of a commit.
        """

    @abc.abstractmethod
    def get_tag_from_commit(self, commit: str, project: ProjectMetadata) -> str | None:
        """Find the first tag which contains a commit."""

    @abc.abstractmethod
    def get_tag_datetime(self, tag: str | TagType) -> datetime:
        """
        Generate a datetime from a tag.

        This prefers the tagged date, but falls back to the commit date.
        """

    @abc.abstractmethod
    def search_commits(
        self,
        pattern: str,
        paths: list[str],
        commit_hashes: list[str],
    ) -> dict[str, list[str]]:
        """
        Search for pattern in specific commits using git grep (no checkout).

        Returns: {commit_hash: [(line_num, matched_line), ...]}
        """


class GitRepository(Repository[Commit, TagReference]):
    def __init__(self, name: str, remote: str) -> None:
        """
        Given a project name and the remote git URL, return a tuple of file path and git repo.

        This will either clone the project (if it doesn't exist) or fetch from the
        remote to update the repository.
        """
        super().__init__(name, remote)
        if not os.path.isdir(self.working_dir):
            self._repo = Repo.clone_from(remote, self.working_dir)

            # Fetch again if the additional refspec is added.
            if self._check_refspecs():
                self._fetch()
        else:
            self._repo = Repo(self.working_dir)
            self._check_refspecs()
            self._fetch()

    def _fetch(self) -> None:
        """Fetch new commits & tags."""
        self._repo.remote().fetch(tags=True, force=True)

    def _check_refspecs(self) -> bool:
        """Add a fetch refspec for pull requests as some sub-repos target pull requests of other repos."""
        url = next(self._repo.remote().urls)
        if "github.com" in url:
            reader = self._repo.config_reader("repository")
            refspecs = reader.get_values('remote "origin"', "fetch")
            if len(refspecs) < 2:
                with self._repo.config_writer("repository") as writer:
                    writer.add_value(
                        'remote "origin"',
                        "fetch",
                        "+refs/pull/*:refs/remotes/origin/pull/*",
                    )
                return True
        return False

    def checkout(self, commit: str | Commit) -> None:
        """Checkout a specific commit or refspec."""
        # Checkout this commit (why is this so hard?).
        self._repo.head.reference = commit
        self._repo.head.reset(index=True, working_tree=True)

    def _dedup_and_order_commits(
        self, commits: list[Iterable[Commit]]
    ) -> Iterable[Commit]:
        """
        De-duplicate and order the commits from multiple iterators.
        """
        commit_map = {c.hexsha: c for c in itertools.chain(*commits)}
        return sorted(
            commit_map.values(),
            key=cmp_to_key(lambda a, b: -1 if self._repo.is_ancestor(a, b) else 1),
        )

    def _get_commits_by_paths(
        self, project: ProjectMetadata, paths: list[str]
    ) -> list[Commit]:
        """
        Get the commits where a file may have been modified.
        """
        earliest_commit = (
            project.commits.earliest_commit
            if project.commits and project.commits.earliest_commit
            else None
        )

        # Calculate the set of versions each time these files were changed, including
        # the earliest commit, if one exists.
        commits = list(
            self._repo.iter_commits(
                f"{earliest_commit}~..origin/{project.branch}"
                if earliest_commit
                else f"origin/{project.branch}",
                paths=paths,
                reverse=True,
                # Follow the development branch through merges (i.e. use dates that
                # changes are merged instead of original commit date).
                first_parent=True,
            )
        )
        if earliest_commit and (not commits or commits[0].hexsha != earliest_commit):
            commits.insert(0, self._repo.commit(earliest_commit))
        return commits

    def extract_subrepo_versions(
        self, finder: SubRepoFinder, main_commit_hashes: list[str]
    ) -> dict[str, set[str]]:
        """
        Extract version patterns from a sub-repository at specific main-repo commits.

        For each main commit, resolves the sub-repo commit hash, then searches
        that sub-repo commit for version patterns.

        Returns: {main_commit_hash: set[versions]}
        """
        if not main_commit_hashes:
            return {}

        # Get or create sub-repository
        sub_repo = Repository.create(finder.repository)

        # Extract sub-repo commit for each main commit
        main_to_subrepo: dict[str, str] = {}
        subrepo_hashes: set[str] = set()

        for main_hash in main_commit_hashes:
            sub_hash = self.map_main_to_subrepo_commit(main_hash, finder.commit_finder)
            if sub_hash:
                main_to_subrepo[main_hash] = sub_hash
                subrepo_hashes.add(sub_hash)

        if not subrepo_hashes:
            return {}

        # Run single git grep in sub-repo across all unique sub-repo commits
        subrepo_results = sub_repo.search_commits(
            finder.finder.pattern,
            finder.finder.paths,
            list(subrepo_hashes),
        )

        # Parse results and map back to main commits
        result: dict[str, set[str]] = {}
        for main_hash, sub_hash in main_to_subrepo.items():
            matches = subrepo_results.get(sub_hash, [])
            versions = parse_matches(finder.finder, matches)

            if versions:
                result[main_hash] = versions

        # TODO: Cache sub-repo grep results across project runs
        # Currently each project creates new Repository instance

        return result

    def map_main_to_subrepo_commit(
        self,
        main_commit_hash: str,
        commit_finder: PatternFinder | SubModuleFinder,
    ) -> str | None:
        """
        Extract sub-repo commit hash from a specific main commit WITHOUT checkout.

        For PatternFinder: git show <commit>:<path> + regex
        For SubModuleFinder: git ls-tree <commit>:<path> + parse submodule entry
        """
        if isinstance(commit_finder, PatternFinder):
            # Try each path until we find a match
            for path in commit_finder.paths:
                try:
                    content = self._repo.git.show(f"{main_commit_hash}:{path}")
                except GitCommandError:
                    continue

                parsed = parse_matches(commit_finder, content.splitlines())

                if parsed:
                    return next(iter(parsed))

            return None

        elif isinstance(commit_finder, SubModuleFinder):
            # Use git ls-tree to get submodule commit at path
            try:
                output = self._repo.git.ls_tree(main_commit_hash, commit_finder.path)
                # Output format: <mode> <type> <hash>\t<path>
                # For submodule: 160000 commit <hash>\t<path>
                for line in output.splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == "commit":
                        return parts[2]
            except GitCommandError:
                pass

        return None

    def search_commits(
        self,
        pattern: str,
        paths: list[str],
        commit_hashes: list[str],
    ) -> dict[str, list[str]]:
        """
        Search for pattern in specific commits using git grep (no checkout).

        Returns: {commit_hash: [(line_num, matched_line), ...]}
        """
        if not commit_hashes:
            return {}

        # Use GitPython's git.grep method
        # -n: show line numbers
        # -P: Perl-compatible regex
        # commit_hashes: list of commits to search
        # --: separator before paths
        # *paths: paths to search
        try:
            result = self._repo.git.grep(
                "-n", "-P", pattern, *commit_hashes, "--", *paths
            )
        except GitCommandError as e:
            # grep returns exit code 1 when no matches found
            if e.status == 1 and e.stdout == "":
                return {}
            raise

        matches_by_commit: dict[str, list[str]] = {}
        for line in result.splitlines():
            if not line:
                continue
            # Format: commit_hash:file_path:line_num:matched_line
            parts = line.split(":", 3)
            if len(parts) == 4:
                commit_hash, _, _, matched = parts
                matches_by_commit.setdefault(commit_hash, []).append(matched)

        return matches_by_commit

    def get_earliest_commit(self, project: ProjectMetadata) -> Commit:
        """Get the earliest commit on the main branch."""
        if project.commits and project.commits.earliest_commit:
            return self._repo.commit(project.commits.earliest_commit)

        return next(self._repo.iter_commits(reverse=True))

    def get_latest_commit(self, project: ProjectMetadata) -> Commit:
        """Get the latest commit on the main branch."""
        if project.commits and project.commits.latest_commit:
            return self._repo.commit(project.commits.latest_commit)

        return self._repo.commit(f"origin/{project.branch}")

    def get_project_datetimes(
        self, project: ProjectMetadata
    ) -> tuple[datetime, datetime, datetime | None]:
        """
        Gets important dates/commits for the project:

        * The initial commit
        * The latest commit
        * The forked from date (if one exists)

        """
        # Get the earliest and latest commit of this project.
        earliest_commit = self.get_earliest_commit(project)
        initial_commit_date = earliest_commit.committed_datetime
        last_commit_date = self.get_latest_commit(project).committed_datetime

        # Maybe add fork information.
        if project.forked_from:
            # Maybe override the forked from a manual date.
            if project.forked_from.date:
                forked_from_date = project.forked_from.date

            elif project.commits and project.commits.earliest_commit:
                forked_from_date = earliest_commit.parents[0].committed_datetime

            # If there's no date info, then use the initial commit.
            else:
                forked_from_date = initial_commit_date
        else:
            forked_from_date = None

        return initial_commit_date, last_commit_date, forked_from_date

    def get_earliest_tag(self, project: ProjectMetadata) -> TagReference | None:
        """Get the earliest release of this project."""
        if self._repo.tags:
            # Find the first tag after the earliest commit.
            if project.commits and project.commits.earliest_commit:
                earliest_tag_sha = self.get_tag_from_commit(
                    project.commits.earliest_commit, project
                )
                if earliest_tag_sha:
                    return self._repo.tags[earliest_tag_sha]
            else:
                return min(self._repo.tags, key=lambda t: self.get_tag_datetime(t))
        return None

    def get_commit_info(self, commit: Commit) -> tuple[str, datetime]:
        """
        Get the sha and datetime of a commit.
        """
        return commit.hexsha, commit.committed_datetime

    def get_tag_from_commit(self, commit: str, project: ProjectMetadata) -> str | None:
        """Find the first tag which contains a commit."""
        # Resolve the commit to the *next* tag. Sorting by creatordate will use the
        # tagged date for annotated tags, otherwise the commit date.
        tags = self._repo.git.tag(
            "--sort=creatordate", "--contains", commit
        ).splitlines()
        if project.commits and project.commits.ignored_tags:
            tags = [t for t in tags if not project.commits.ignored_tags(t)]
        if tags:
            return tags[0]
        return None

    def get_tag_datetime(self, tag: str | TagReference) -> datetime:
        """
        Generate a datetime from a tag.

        This prefers the tagged date, but falls back to the commit date.
        """
        if isinstance(tag, str):
            tag = self._repo.tags[tag]

        if tag.tag is None:
            return tag.commit.committed_datetime
        return datetime.fromtimestamp(
            tag.tag.tagged_date,
            tz=timezone(offset=timedelta(seconds=-tag.tag.tagger_tz_offset)),
        )
