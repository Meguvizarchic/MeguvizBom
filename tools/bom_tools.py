#!/usr/bin/env python3
"""Verification and Maven Central bundling for meguviz-bom. Standard library only (Python 3.9+).

  bom_tools.py check --repo build/staging-maven
      The staged POM and Gradle module metadata must list exactly the artifacts and versions in members.txt,
      with the platform category in the module metadata, no real dependencies, the metadata Maven Central
      requires and matching checksum files.
  bom_tools.py bundle --repo build/staging-maven --out build/central/<name>.zip [--require-signatures]
      Zips the staged files in Maven Central layout (deterministically) and verifies the result.
  bom_tools.py verify-bundle BUNDLE.zip [--skip-gpg] [--allow-unsigned] [--check-unpublished]
      Checks an upload bundle: layout, checksums, signatures (system gpg), POM fields, and with --check-unpublished
      that the version is not on Central yet (a release cannot be replaced).
  bom_tools.py central-status [--require-all] [--version V]
      Which members exist on Maven Central at their specified versions. Publish the BOM only when all do.

Scope: this checks the files and the alignment metadata. It cannot check that the namespace is verified on the
Central Portal or that the signing key is on a key server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
GROUP = "io.github.jichuo1.meguviz"
BOM = "meguviz-bom"
NS = {"m": "http://maven.apache.org/POM/4.0.0"}
CHECKSUMS = {".md5": "md5", ".sha1": "sha1", ".sha256": "sha256", ".sha512": "sha512"}
CENTRAL = "https://repo1.maven.org/maven2"
GROUP_PATH = GROUP.replace(".", "/")


def bom_version(root: Path = ROOT) -> str:
    for line in (root / "gradle.properties").read_text("utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "meguviz.version" and value.strip():
            return value.strip()
    raise ValueError("gradle.properties has no meguviz.version")


def member_coordinate(member: str, default_version: str) -> tuple[str, str, str]:
    parts = member.split(":")
    if len(parts) == 1:
        group, artifact, version = GROUP, parts[0], default_version
    elif len(parts) == 2:
        group, artifact, version = parts[0], parts[1], default_version
    elif len(parts) == 3:
        group, artifact, version = parts
    else:
        raise ValueError(f"invalid member: {member}")
    if (not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", group)
            or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", artifact)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?", version)
            or version.upper().endswith("-SNAPSHOT")):
        raise ValueError(f"invalid member: {member}")
    return group, artifact, version


def read_members(root: Path = ROOT) -> List[str]:
    members = []
    for raw in (root / "members.txt").read_text("utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            members.append(line)
    if not members:
        raise ValueError("members.txt lists no artifacts")
    coordinates = [member_coordinate(member, "0.0.0")[:2] for member in members]
    if len(set(coordinates)) != len(members):
        raise ValueError("members.txt lists an artifact twice")
    if (GROUP, BOM) in coordinates:
        raise ValueError("the BOM must not constrain itself")
    return members


def staged_directory(repo: Path, version: str) -> Path:
    return repo / GROUP_PATH / BOM / version


def read_sidecar(path: Path) -> str:
    return path.read_text("ascii", "replace").split()[0].lower()


# ---- POM and module metadata ---------------------------------------------------------------------------------

def check_pom(data: bytes, version: str, members: List[str]) -> List[str]:
    problems: List[str] = []
    root = ET.fromstring(data)

    def text(path: str) -> Optional[str]:
        node = root.find(path, NS)
        return node.text.strip() if node is not None and node.text and node.text.strip() else None

    for field, path, expected in (("groupId", "m:groupId", GROUP), ("artifactId", "m:artifactId", BOM),
                                  ("version", "m:version", version), ("packaging", "m:packaging", "pom")):
        if text(path) != expected:
            problems.append(f"POM {field} is {text(path)!r}, expected {expected!r}")
    for field, path in (("name", "m:name"), ("description", "m:description"), ("url", "m:url"),
                        ("license name", "m:licenses/m:license/m:name"), ("license url", "m:licenses/m:license/m:url"),
                        ("developer", "m:developers/m:developer/m:name"), ("scm url", "m:scm/m:url"),
                        ("scm connection", "m:scm/m:connection")):
        if text(path) is None:
            problems.append(f"POM lacks {field}")
    if root.findall("m:dependencies/m:dependency", NS):
        problems.append("POM declares real dependencies; a BOM may only manage versions")
    managed = set()
    for dep in root.findall("m:dependencyManagement/m:dependencies/m:dependency", NS):
        managed.add((dep.findtext("m:groupId", namespaces=NS), dep.findtext("m:artifactId", namespaces=NS),
                     dep.findtext("m:version", namespaces=NS)))
    expected_set = {member_coordinate(member, version) for member in members}
    for item in sorted(expected_set - managed, key=str):
        problems.append(f"POM does not manage {item[0]}:{item[1]}:{item[2]}")
    for item in sorted(managed - expected_set, key=str):
        problems.append(f"POM manages {item[0]}:{item[1]}:{item[2]}, which members.txt and the BOM version do not allow")
    return problems


def check_module(data: bytes, version: str, members: List[str]) -> List[str]:
    problems: List[str] = []
    document = json.loads(data.decode("utf-8"))
    component = document.get("component", {})
    if (component.get("group"), component.get("module"), component.get("version")) != (GROUP, BOM, version):
        problems.append(f"module metadata component is {component!r}")
    variants = document.get("variants", [])
    if not variants:
        problems.append("module metadata has no variants")
    expected = {member_coordinate(member, version) for member in members}
    for variant in variants:
        name = variant.get("name")
        if variant.get("attributes", {}).get("org.gradle.category") != "platform":
            problems.append(f"variant {name} is not org.gradle.category=platform")
        if variant.get("dependencies"):
            problems.append(f"variant {name} has real dependencies")
        if variant.get("files"):
            problems.append(f"variant {name} publishes files")
        constraints = set()
        for item in variant.get("dependencyConstraints", []):
            constraints.add((item.get("group"), item.get("module"), item.get("version", {}).get("requires")))
        for item in sorted(expected - constraints, key=str):
            problems.append(f"variant {name} lacks the constraint {item[0]}:{item[1]}:{item[2]}")
        for item in sorted(constraints - expected, key=str):
            problems.append(f"variant {name} constrains {item[0]}:{item[1]}:{item[2]}, which is not allowed")
    return problems


def check_staged(repo: Path, version: str, members: List[str]) -> List[str]:
    directory = staged_directory(repo, version)
    pom = directory / f"{BOM}-{version}.pom"
    module = directory / f"{BOM}-{version}.module"
    problems: List[str] = []
    for path in (pom, module):
        if not path.is_file():
            problems.append(f"missing {path.relative_to(repo)}")
            continue
        for suffix, algorithm in CHECKSUMS.items():
            sidecar = path.with_name(path.name + suffix)
            if not sidecar.is_file():
                problems.append(f"missing {sidecar.name}")
            elif read_sidecar(sidecar) != hashlib.new(algorithm, path.read_bytes()).hexdigest():
                problems.append(f"{sidecar.name} does not match {path.name}")
    if problems:
        return problems
    return check_pom(pom.read_bytes(), version, members) + check_module(module.read_bytes(), version, members)


# ---- Central bundle ------------------------------------------------------------------------------------------

def payload_files(directory: Path) -> List[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file() and not p.name.startswith("maven-metadata"))


def build_bundle(repo: Path, out: Path, version: str, members: List[str], require_signatures: bool) -> List[str]:
    problems = check_staged(repo, version, members)
    directory = staged_directory(repo, version)
    if problems:
        return problems
    files = payload_files(directory)
    if require_signatures:
        for name in (f"{BOM}-{version}.pom", f"{BOM}-{version}.module"):
            if not (directory / (name + ".asc")).is_file():
                problems.append(f"missing {name}.asc: run with -Pmeguviz.sign=true")
        if problems:
            return problems
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(f"{GROUP_PATH}/{BOM}/{version}/{path.name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return verify_bundle(out, members, skip_gpg=True, allow_unsigned=not require_signatures)


def verify_bundle(bundle: Path, members: List[str], skip_gpg: bool, allow_unsigned: bool,
                  check_unpublished: bool = False, head: Optional[Callable[[str], Optional[int]]] = None) -> List[str]:
    problems: List[str] = []
    with zipfile.ZipFile(bundle) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        directories = set()
        for name in names:
            parts = PurePosixPath(name).parts
            if parts[-1].startswith("maven-metadata"):
                problems.append(f"remove {name}: the Portal generates repository metadata itself")
            elif len(parts) != len(GROUP_PATH.split("/")) + 3 or "/".join(parts[:-3]) != GROUP_PATH or parts[-3] != BOM:
                problems.append(f"unexpected path {name}")
            else:
                directories.add(parts[-2])
        if len(directories) != 1:
            problems.append(f"bundle must hold exactly one version of {BOM}, found {sorted(directories)}")
            return problems
        version = directories.pop()
        if version.endswith("SNAPSHOT"):
            problems.append("SNAPSHOT versions cannot be released")
        prefix = f"{GROUP_PATH}/{BOM}/{version}/"
        stem = f"{BOM}-{version}"
        payload = [n[len(prefix):] for n in names
                   if n.startswith(prefix) and not n.endswith(".asc") and not n.endswith(tuple(CHECKSUMS))]
        for required in (f"{stem}.pom", f"{stem}.module"):
            if required not in payload:
                problems.append(f"missing {required}")
        for name in payload:
            if not name.startswith(stem):
                problems.append(f"unexpected file name {name}")
                continue
            data = archive.read(prefix + name)
            for suffix, algorithm in CHECKSUMS.items():
                sidecar = prefix + name + suffix
                if sidecar not in names:
                    if suffix in (".md5", ".sha1"):
                        problems.append(f"missing {name}{suffix}")
                elif archive.read(sidecar).decode("ascii", "replace").split()[0].lower() != hashlib.new(algorithm, data).hexdigest():
                    problems.append(f"{name}{suffix} does not match")
            signature = prefix + name + ".asc"
            if signature not in names:
                if not allow_unsigned:
                    problems.append(f"missing {name}.asc")
            elif not skip_gpg:
                problems.extend(verify_signature(data, archive.read(signature), name))
        if f"{stem}.pom" in payload:
            problems.extend(check_pom(archive.read(prefix + f"{stem}.pom"), version, members))
        if f"{stem}.module" in payload:
            problems.extend(check_module(archive.read(prefix + f"{stem}.module"), version, members))
    if check_unpublished:
        status = (head or http_head)(f"{CENTRAL}/{GROUP_PATH}/{BOM}/{version}/{BOM}-{version}.pom")
        if status == 200:
            problems.append(f"{BOM} {version} is already on Maven Central and cannot be replaced")
        elif status not in (404,):
            problems.append(f"could not confirm that {BOM} {version} is unpublished (answer: {status})")
    return problems


def verify_signature(data: bytes, signature: bytes, label: str) -> List[str]:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "data").write_bytes(data)
        (Path(tmp) / "data.asc").write_bytes(signature)
        try:
            result = subprocess.run(["gpg", "--batch", "--verify", str(Path(tmp) / "data.asc"), str(Path(tmp) / "data")],
                                    capture_output=True, text=True)
        except FileNotFoundError:
            return [f"{label}: gpg is not installed; use --skip-gpg to skip the signature check"]
    if result.returncode != 0:
        return [f"{label}: signature does not verify ({result.stderr.strip().splitlines()[-1:]})"]
    return []


# ---- Central status ------------------------------------------------------------------------------------------

def http_head(url: str) -> Optional[int]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return None


def central_status(members: List[str], version: str,
                   head: Optional[Callable[[str], Optional[int]]] = None) -> Dict[str, str]:
    lookup = head or http_head
    result = {}
    for member in members:
        group, artifact, member_version = member_coordinate(member, version)
        status = lookup(f"{CENTRAL}/{group.replace('.', '/')}/{artifact}/{member_version}/{artifact}-{member_version}.pom")
        result[member] = "published" if status == 200 else "missing" if status == 404 else f"unknown ({status})"
    return result


# ---- CLI -----------------------------------------------------------------------------------------------------

def report(problems: List[str], ok: str) -> int:
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(ok)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--repo", type=Path, required=True)
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--repo", type=Path, required=True)
    bundle.add_argument("--out", type=Path, required=True)
    bundle.add_argument("--require-signatures", action="store_true")
    verify = commands.add_parser("verify-bundle")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--skip-gpg", action="store_true")
    verify.add_argument("--allow-unsigned", action="store_true")
    verify.add_argument("--check-unpublished", action="store_true")
    status = commands.add_parser("central-status")
    status.add_argument("--require-all", action="store_true")
    status.add_argument("--version")
    args = parser.parse_args(argv)

    members = read_members()
    version = bom_version()
    if args.command == "check":
        return report(check_staged(args.repo, version, members),
                      f"{BOM} {version}: {len(members)} members, POM and module metadata consistent")
    if args.command == "bundle":
        return report(build_bundle(args.repo, args.out, version, members, args.require_signatures),
                      f"wrote {args.out} ({'signed' if args.require_signatures else 'unsigned'})")
    if args.command == "verify-bundle":
        return report(verify_bundle(args.bundle, members, args.skip_gpg, args.allow_unsigned, args.check_unpublished),
                      f"{args.bundle}: bundle is consistent")
    wanted = args.version or version
    result = central_status(members, wanted)
    width = max(len(name) for name in result)
    for name, state in result.items():
        print(f"{name.ljust(width)}  {state}")
    missing = [name for name, state in result.items() if state != "published"]
    print(f"{len(result) - len(missing)} of {len(result)} members are on Maven Central "
          f"(family version {wanted}; independent versions as pinned)")
    return 1 if args.require_all and missing else 0


if __name__ == "__main__":
    sys.exit(main())
