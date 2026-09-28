#!/usr/bin/env python3
"""Generate a provider network mirror index from a GitHub release.

The mirror protocol is two static JSON files per provider plus the zips, which
is why GitHub Pages can serve it:

    /:namespace/:type/index.json     versions available
    /:namespace/:type/:version.json  archives, keyed by os_arch

Archive URLs point at the GitHub release assets rather than copies, so Pages
hosts a few KB of JSON and nothing else. Hashes come from the SHA256SUMS
goreleaser already produces; OpenTofu verifies the strongest one it recognises.

It also writes the provider REGISTRY protocol documents, so the provider
installs by source address with no CLI config once the host's
/.well-known/terraform.json points providers.v1 at REGISTRY_DIR:

    v1/providers/:namespace/:type/versions                            versions
    v1/providers/:namespace/:type/:version/download/:os/:arch         one package

The download document carries the public signing key, so the CLI checks the
SHA256SUMS signature before trusting the shasum.

Usage: build-mirror.py --version 2.1.0 --sums <SHA256SUMS> --out site/
"""
import argparse, json, pathlib, re, subprocess

REPO = "jibey-fs/terraform-provider-fspanos"
NAMESPACE, TYPE = "jibey-fs", "fspanos"
# The mirror protocol keys packages by REGISTRY HOSTNAME, and the default
# differs by CLI: tofu resolves "jibey-fs/fspanos" to
# registry.opentofu.org/jibey-fs/fspanos, terraform to registry.terraform.io/...
# Publishing under both means either CLI finds it.
HOSTNAMES = ["registry.opentofu.org", "registry.terraform.io"]
PROJECT = "terraform-provider-fspanos"
REGISTRY_DIR = pathlib.Path("v1/providers") / NAMESPACE / TYPE
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "terraform-registry-manifest.json"
SIGNING_KEY = REPO_ROOT / "signing-key.asc"


def load_versions(index_path):
    """Versions from an existing index.json; empty if absent or unreadable."""
    try:
        return dict(json.loads(index_path.read_text())["versions"])
    except FileNotFoundError:
        return {}
    except (ValueError, KeyError, TypeError) as e:
        print(f"warning: ignoring invalid {index_path}: {e}")
        return {}


def signing_key():
    """The release signing key as the registry protocol's gpg_public_keys entry."""
    armor = SIGNING_KEY.read_text()
    out = subprocess.run(["gpg", "--show-keys", "--with-colons"], input=armor,
                         capture_output=True, text=True, check=True).stdout
    key_id = next(l.split(":")[4] for l in out.splitlines() if l.startswith("pub:"))
    return {"key_id": key_id, "ascii_armor": armor}


def write_registry(out, version, packages, protocols):
    """Registry protocol documents; older versions kept if their docs survive."""
    d = pathlib.Path(out) / REGISTRY_DIR
    try:
        versions = {v["version"]: v for v in json.loads((d / "versions").read_text())["versions"]}
    except FileNotFoundError:
        versions = {}
    except (ValueError, KeyError, TypeError) as e:
        print(f"warning: ignoring invalid {d / 'versions'}: {e}")
        versions = {}
    for v, entry in sorted(versions.items()):
        missing = [p for p in entry["platforms"]
                   if not (d / v / "download" / p["os"] / p["arch"]).exists()]
        if missing:
            print(f"warning: registry: {v} download docs missing, dropping {v}")
            del versions[v]

    key = signing_key()
    base = f"https://github.com/{REPO}/releases/download/v{version}"
    sums = f"{base}/{PROJECT}_{version}_SHA256SUMS"
    platforms = []
    for (goos, goarch), (filename, digest) in sorted(packages.items()):
        doc = d / version / "download" / goos / goarch
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(json.dumps({
            "protocols": protocols,
            "os": goos,
            "arch": goarch,
            "filename": filename,
            "download_url": f"{base}/{filename}",
            "shasums_url": sums,
            "shasums_signature_url": f"{sums}.sig",
            "shasum": digest,
            "signing_keys": {"gpg_public_keys": [key]},
        }, indent=2) + "\n")
        platforms.append({"os": goos, "arch": goarch})
    versions[version] = {"version": version, "protocols": protocols, "platforms": platforms}
    (d / "versions").write_text(json.dumps(
        {"versions": [versions[v] for v in sorted(versions)]}, indent=2) + "\n")
    print(f"registry: {len(platforms)} platforms for {version}, {len(versions)} version(s)")


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
    packages = {}
    for line in pathlib.Path(a.sums).read_text().splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        digest, goos, goarch = m.groups()
        archives[f"{goos}_{goarch}"] = {
            "url": f"{base}/{PROJECT}_{version}_{goos}_{goarch}.zip",
            "hashes": [f"zh:{digest}"],
        }
        packages[(goos, goarch)] = (f"{PROJECT}_{version}_{goos}_{goarch}.zip", digest)
    if not archives:
        raise SystemExit(f"no archives matched in {a.sums} for version {version}")

    for host in HOSTNAMES:
        d = pathlib.Path(a.out) / host / NAMESPACE / TYPE
        d.mkdir(parents=True, exist_ok=True)

        # index.json accumulates versions, so an older release stays
        # installable after a new one lands. A version whose <version>.json
        # was not carried over is dropped: listing it would break installs.
        versions = load_versions(d / "index.json")
        for v in sorted(versions):
            if not (d / f"{v}.json").exists():
                print(f"warning: {host}: {v}.json missing, dropping {v} from the index")
                del versions[v]
        versions[version] = {}
        index_path = d / "index.json"
        index_path.write_text(json.dumps({"versions": versions}, indent=2, sort_keys=True) + "\n")

        (d / f"{version}.json").write_text(
            json.dumps({"archives": dict(sorted(archives.items()))}, indent=2) + "\n")
        print(f"{host}: {len(archives)} platforms for {version}, {len(versions)} version(s)")

    protocols = json.loads(MANIFEST.read_text())["metadata"]["protocol_versions"]
    write_registry(a.out, version, packages, protocols)


if __name__ == "__main__":
    main()
