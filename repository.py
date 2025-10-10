import abc
import contextlib
import itertools
import json
import os.path
import subprocess
from datetime import datetime, timedelta, timezone
from functools import cmp_to_key
from pathlib import Path
from typing import Generic, Iterable, Iterator, TypeVar
from urllib.parse import urlsplit, urlunsplit

import git.cmd
from git import Commit, Repo, TagReference

from finders import get_pattern_from_file
from projects import (
    PatternFinder,
    ProjectMetadata,
    ProxyType,
    RepositoryMetadata,
    RepositoryType,
    SubModuleFinder,
    SubRepoFinder,
)

CommitType = TypeVar("CommitType")
TagType = TypeVar("TagType")


YGGDRASIL_CONF_FILENAME = "./yggdrasil.conf"


def _generate_yggdrasil_conf():
    result = subprocess.run(["./yggstack", "-genconf", "--json"], capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate config: {result.stderr}")

    # Get the output.
    data = json.loads(result.stdout)

    # Add some default peers.
    # See https://github.com/yggdrasil-network/public-peers/blob/master/north-america/united-states.md
    data["Peers"] = [
        "tls://redcatho.de:9494",
        "quic://redcatho.de:9494",
        "tcp://longseason.1200bps.xyz:13121",
        "tls://longseason.1200bps.xyz:13122",
    ]

    with open(YGGDRASIL_CONF_FILENAME, "w") as f:
        json.dump(data, f, indent=4)


@contextlib.contextmanager
def ProxyContextManager(repository: RepositoryMetadata):
    """
    Start-up a proxy process, swap URLs to the proxy (yielding the new URL to use),
    and cleanly shutdown the proxy.
    """
    # Start with the original URL and no proxy.
    url = repository.url
    proxy_process = None

    if repository.proxy_type == ProxyType.YGGDRASIL:
        # Parse the URL to pull out the IPv6 address/port.
        parts = urlsplit(url)
        remote_url = parts.netloc if parts.port else f"{parts.netloc}:80"

        if not Path(YGGDRASIL_CONF_FILENAME).exists():
            _generate_yggdrasil_conf()

        # Bind this remote to a local IP/port.
        local_url = "127.0.0.1:11080"
        proxy_process = subprocess.Popen(
            [
                "./yggstack",
                "-useconffile",
                YGGDRASIL_CONF_FILENAME,
                "-local-tcp",
                f"{local_url}:{remote_url}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Clone from the local URL, but add the path, etc. back.
        url = urlunsplit((parts[0], local_url, parts[2], parts[3], parts[4]))

    try:
        yield url
    finally:
        if proxy_process:
            proxy_process.terminate()


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
    def create(self, name: str, metadata: RepositoryMetadata):
        with ProxyContextManager(metadata) as url:
            if metadata.type == RepositoryType.GIT:
                return GitRepository(name, url)
            elif metadata.type == RepositoryType.HG:
                return HgRepository(name, url)
            else:
                raise ValueError(f"Unknown repository type: {metadata.type}")

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
                raise ValueError(f"Unsupported finder: {finder.__class__.__name__}")

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

    def get_pattern_from_subrepo(self, finder: SubRepoFinder) -> set[str]:
        """
        Search a sub-repository for a pattern, this works by searching the main
        repo for the sub-repository commit, then checking it out and searching
        the sub-repository for the pattern.
        """
        # Get the sub-repository.
        sub_repo = Repository.create(
            finder.repository.url.split("/")[-1], finder.repository
        )

        # The commit to checkout in the sub-repository.
        sub_repo_commit = None

        if isinstance(finder.commit_finder, PatternFinder):
            commits = get_pattern_from_file(
                self.working_dir,
                finder.commit_finder.paths,
                finder.commit_finder.pattern,
                finder.commit_finder.parser,
                finder.commit_finder.to_ignore,
            )

            if len(commits) > 1:
                raise ValueError("Unexpected number of commits: {commits}")
            elif len(commits) == 1:
                sub_repo_commit = next(iter(commits))

        elif isinstance(finder.commit_finder, SubModuleFinder):
            # The commit of the sub-repo is found via the submodule path.
            # Find the sub-module information, if it exists.
            sub_repo_commit = self._get_submodule_commit(finder.commit_finder.path)

        else:
            raise ValueError(
                f"Unsupported commit finder: {finder.commit_finder.__class__.__name__}"
            )

        # No commit was found, sub-repo must not exist.
        if not sub_repo_commit:
            return set()

        sub_repo.checkout(sub_repo_commit)

        return get_pattern_from_file(
            sub_repo.working_dir,
            finder.finder.paths,
            finder.finder.pattern,
            finder.finder.parser,
            finder.finder.to_ignore,
        )

    @abc.abstractmethod
    def _get_submodule_commit(self, path: str) -> str | None:
        """Find the commit of a sub-module checked out at the given path."""

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
            raise ValueError(
                f"Unsupported commit finder: {finder.commit_finder.__class__.__name__}"
            )

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
    def get_tag_from_commit(self, commit: str) -> str | None:
        """Find the first tag which contains a commit."""

    @abc.abstractmethod
    def get_tag_datetime(self, tag: str | TagType) -> datetime:
        """
        Generate a datetime from a tag.

        This prefers the tagged date, but falls back to the commit date.
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
                self._repo.remote().fetch()
        else:
            self._repo = Repo(self.working_dir)
            self._check_refspecs()
            self._repo.remote().fetch()

        self._git_cmd = git.cmd.Git(self.working_dir)

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

        # Calculate the set of versions each time these files were changed, including
        # the earliest commit, if one exists.
        commits = list(
            self._repo.iter_commits(
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
            commits.insert(0, self._repo.commit(project.earliest_commit))
        return commits

    def _get_submodule_commit(self, path: str) -> str | None:
        """Find the commit of a sub-module checked out at the given path."""
        # The commit of the sub-repo is found via the submodule path.
        # Find the sub-module information, if it exists.
        sub_module = next(
            (s for s in self._repo.submodules if s.path == path),
            None,
        )
        if sub_module:
            return sub_module.hexsha
        return None

    def get_project_datetimes(
        self, project: ProjectMetadata
    ) -> tuple[datetime, datetime, datetime | None]:
        """Get some important dates for the project."""
        # Get the earliest and latest commit of this project.
        if project.earliest_commit:
            earliest_commit = self._repo.commit(project.earliest_commit)
            forked_date = earliest_commit.parents[0].committed_datetime
        else:
            earliest_commit = next(self._repo.iter_commits(reverse=True))
            forked_date = None
        initial_commit_date = earliest_commit.committed_datetime
        last_commit_date = self._repo.commit(
            f"origin/{project.branch}"
        ).committed_datetime

        return initial_commit_date, last_commit_date, forked_date

    def get_earliest_tag(self, project: ProjectMetadata) -> TagReference | None:
        """Get the earliest release of this project."""
        if self._repo.tags:
            # Find the first tag after the earliest commit.
            if project.earliest_commit:
                earliest_tag_sha = self.get_tag_from_commit(project.earliest_commit)
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

    def get_tag_from_commit(self, commit: str) -> str | None:
        """Find the first tag which contains a commit."""
        # Resolve the commit to the *next* tag. Sorting by creatordate will use the
        # tagged date for annotated tags, otherwise the commit date.
        tags = self._git_cmd.execute(
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


class HgRepository(Repository[str, str]):
    def __init__(self, name: str, remote: str) -> None:
        """
        Given a project name and the remote git URL, return a tuple of file path and git repo.

        This will either clone the project (if it doesn't exist) or fetch from the
        remote to update the repository.
        """
        super().__init__(name, remote)
        if not os.path.isdir(self.working_dir):
            # This doesn't use _run_command since that starts in the working directory which does not yet exist.
            subprocess.run(
                ["hg", "clone", remote, self.working_dir], capture_output=True
            )

        else:
            self._run_command("pull")

    def _run_command(self, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["hg", *args], capture_output=True, text=True, cwd=self.working_dir
        )
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError(f"Command failed to complete: hg {' '.join(args)}")
        return result

    def checkout(self, commit: str | CommitType) -> None:
        """Checkout a specific commit or refspec."""
        self._run_command("update", "--clean", "--rev", commit)

    def _dedup_and_order_commits(self, commits: list[Iterable[str]]) -> Iterable[str]:
        """
        De-duplicate and order the commits from multiple iterators.
        """
        # Feed them all into hg log, it will de-duplicate and order them for us.
        revs = "+".join(itertools.chain(*commits))
        result = self._run_command(
            "log", "--template", "{node}\n", "--rev", f"sort({revs})"
        )
        return result.stdout.splitlines()

    def _get_commits_by_paths(
        self, project: ProjectMetadata, paths: list[str]
    ) -> list[str]:
        """
        Get the commits where a file may have been modified.
        """
        # Calculate the set of versions each time these files were changed, including
        # the earliest commit, if one exists.
        result = self._run_command(
            "log",
            "--template",
            "{node}\n",
            "--rev",
            f"{project.earliest_commit}:{project.branch}"
            if project.earliest_commit
            else f":{project.branch}",
            *paths,
        )
        return result.stdout.splitlines()

    def _get_submodule_commit(self, path: str) -> str | None:
        """Find the commit of a sub-module checked out at the given path."""
        raise NotImplementedError("Submodules are not implemented for hg")

    def get_project_datetimes(
        self, project: ProjectMetadata
    ) -> tuple[datetime, datetime, datetime | None]:
        """Get some important dates for the project."""
        # Get the earliest and latest commit of this project.
        if project.earliest_commit:
            initial_commit_date = self.get_tag_datetime(project.earliest_commit)
            forked_date = self.get_tag_datetime(f"{project.earliest_commit}^")
        else:
            initial_commit_date = self.get_tag_datetime("0")
            forked_date = None
        return initial_commit_date, self.get_tag_datetime(project.branch), forked_date

    def get_earliest_tag(self, project: ProjectMetadata) -> str | None:
        """Get the earliest release of this project."""
        result = self._run_command(
            "log", "--template", "{tags}", "--rev", "first(tag())"
        )
        return result.stdout.strip() if result.stdout else None

    def get_commit_info(self, commit: str) -> tuple[str, datetime]:
        """
        Get the sha and datetime of a commit.
        """
        return commit, self.get_tag_datetime(commit)

    def get_tag_from_commit(self, commit: str) -> str | None:
        """Find the first tag which contains a commit."""
        result = self._run_command(
            "log", "--template", "{tags}\n", "--rev", f"first({commit}: and tag())"
        )
        return result.stdout.strip() if result.stdout else None

    def get_tag_datetime(self, tag: str) -> datetime:
        """
        Generate a datetime from a tag.

        This prefers the tagged date, but falls back to the commit date.
        """
        result = self._run_command(
            "log", "--template", "{date|isodate}\n", "--rev", tag
        )
        return datetime.fromisoformat(result.stdout.strip())
