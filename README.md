# homeserver-spec-versions

## About

This repo contains raw data and simple web UI for https://patrick.cloke.us/homeserver-spec-versions/.

It aims to provide some information related to the [Matrix specficiation](https://spec.matrix.org/):

1. When each homeserver started (and stopped) supporting each version of the spec.
2. The latency from a spec version being released to homeservers supporting it.
3. The correlation between the amount of time between spec versions and the amount of time it took a homeserver to support that version after release.

It also contains some information specific to [room versions](https://spec.matrix.org/v1.10/rooms/):

1. When each homeserver started (and stopped) supporting each room version.
2. When each homeserver declared a room version as the "default" room version.

Separately there's also a timeline of homeservers (considering their first and
latest commits) and information about forks, forming a family tree of homeservers.

Note that this repository deals with homeserver implementations and not particular deployments.

## Prerequisities

This assumes you have the following available on your `PATH`:

* `git`

## Updating

### Updating the metadata

`servers.toml` and `projects.py` contains metadata about each homeserver implementation.
See the comments in that file for the necessary metadata to provide to add a homeserver.

### Fetching latest data

1. Create a Python virtual env
2. Install the dependencies (`pip install -r requirements.txt`)
3. Run the script: `python -m main`
4. Check it for errors.

You can also fetch individual projects by providing one or more projects:

`python -m main spec synapse`

----

## Finding Homeservers

### Forges

* bitbucket.org
* codeberg.org
* codefloe.com
* sr.ht
* gitea.com
* github.com
* gitlab.com
* launchpad.net
* savannah.gnu.org
* sourceforge.net

### Package repositories

* .NET (NuGet): nuget.org
* C/C++ (Conan): conan.io
* Erlang (Hex): hex.pm
* Haskell (Hackage): hackage.haskell.org
* Java (Maven): mvnrepository.com
* Lua (LuaRocks): luarocks.org
* OCaml (OPAM): opam.ocaml.org
* Node.js (npm): npmjs.com
* Perl (CPAN): cpan.org
* PHP (Pear): pear.php.net
* PHP (Packagist): packagist.org
* Python (PyPI): pypi.org
* Ruby (RubyGems): rubygems.org
* Rust (Crates.io): crates.io
* Swift / Objective-C (CocoaPods): cocoapods.org

----

[This work](https://patrick.cloke.us/homeserver-spec-versions/) © 2024 by [Patrick Cloke](https://github.com/clokep) is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
