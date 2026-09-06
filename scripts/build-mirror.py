#!/usr/bin/env python3
"""Generate a provider network mirror index from a GitHub release.

The mirror protocol is two static JSON files per provider plus the zips, which
is why GitHub Pages can serve it:

    /:namespace/:type/index.json     versions available
    /:namespace/:type/:version.json  archives, keyed by os_arch

Archive URLs point at the GitHub release assets rather than copies, so Pages
hosts a few KB of JSON and nothing else. Hashes come from the SHA256SUMS
goreleaser already produces; OpenTofu verifies the strongest one it recognises.

Usage: build-mirror.py --version 2.1.0 --sums <SHA256SUMS> --out site/
"""
import argparse, json, pathlib, re

REPO = "jibey-fs/terraform-provider-fspanos"
NAMESPACE, TYPE = "jibey-fs", "fspanos"
PROJECT = "terraform-provider-fspanos"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--sums", required=True, help="SHA256SUMS file from the release")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    version = a.version.lstrip("v")

    base = f"https://github.com/{REPO}/releases/download/v{version}"
    pat = re.compile(
        r"^([0-9a-f]{64})\s+\*?" + re.escape(PROJECT) + "_" + re.escape(version) + r"_(\w+)_(\w+)\.zip$")

    archives = {}
    for line in pathlib.Path(a.sums).read_text().splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        digest, goos, goarch = m.groups()
        archives[f"{goos}_{goarch}"] = {
            "url": f"{base}/{PROJECT}_{version}_{goos}_{goarch}.zip",
            "hashes": [f"zh:{digest}"],
        }
    if not archives:
        raise SystemExit(f"no archives matched in {a.sums} for version {version}")

    d = pathlib.Path(a.out) / NAMESPACE / TYPE
    d.mkdir(parents=True, exist_ok=True)

    # index.json accumulates versions, so an older release stays installable
    # after a new one lands.
    index_path = d / "index.json"
    versions = json.loads(index_path.read_text())["versions"] if index_path.exists() else {}
    versions[version] = {}
    index_path.write_text(json.dumps({"versions": versions}, indent=2, sort_keys=True) + "\n")

    (d / f"{version}.json").write_text(
        json.dumps({"archives": dict(sorted(archives.items()))}, indent=2) + "\n")

    print(f"{len(archives)} platforms for {version}; {len(versions)} version(s) in index")


if __name__ == "__main__":
    main()
