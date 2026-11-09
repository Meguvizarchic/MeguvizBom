import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bom_tools as tools  # noqa: E402

VERSION = "9.9.9"
MEMBERS = ["meguviz-a", "meguviz-b", "meguviz-c"]


def pom(version=VERSION, members=MEMBERS, extra=None, license_name="Apache", dependencies="", artifact=tools.BOM):
    managed = "".join(
        f"<dependency><groupId>{tools.GROUP}</groupId><artifactId>{m}</artifactId><version>{version}</version></dependency>"
        for m in list(members) + list(extra or []))
    license_block = f"<licenses><license><name>{license_name}</name><url>https://example.test/l</url></license></licenses>" if license_name else ""
    return (f'<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
            f"<groupId>{tools.GROUP}</groupId><artifactId>{artifact}</artifactId><version>{version}</version><packaging>pom</packaging>"
            f"<name>BOM</name><description>d</description><url>https://example.test</url>{license_block}"
            f"<developers><developer><name>dev</name></developer></developers>"
            f"<scm><connection>scm:git:x</connection><url>https://example.test</url></scm>"
            f"<dependencyManagement><dependencies>{managed}</dependencies></dependencyManagement>{dependencies}</project>").encode()


def module(version=VERSION, members=MEMBERS, category="platform", constraint_version=None, dependencies=None):
    constraints = [{"group": tools.GROUP, "module": m, "version": {"requires": constraint_version or version}} for m in members]
    variants = []
    for name, usage in (("apiElements", "java-api"), ("runtimeElements", "java-runtime")):
        variant = {"name": name, "attributes": {"org.gradle.category": category, "org.gradle.usage": usage},
                   "dependencyConstraints": constraints}
        if dependencies:
            variant["dependencies"] = dependencies
        variants.append(variant)
    return json.dumps({"formatVersion": "1.1", "component": {"group": tools.GROUP, "module": tools.BOM, "version": version},
                       "variants": variants}).encode()


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, pom_bytes=None, module_bytes=None, sign=False, version=VERSION):
        directory = tools.staged_directory(self.repo, version)
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in ((f"{tools.BOM}-{version}.pom", pom_bytes if pom_bytes is not None else pom(version)),
                           (f"{tools.BOM}-{version}.module", module_bytes if module_bytes is not None else module(version))):
            (directory / name).write_bytes(data)
            for suffix, algorithm in tools.CHECKSUMS.items():
                (directory / (name + suffix)).write_text(hashlib.new(algorithm, data).hexdigest())
            if sign:
                (directory / (name + ".asc")).write_text("-----BEGIN PGP SIGNATURE-----\nfixture\n")
        return directory

    def problems(self, **kwargs):
        self.stage(**kwargs)
        return tools.check_staged(self.repo, VERSION, MEMBERS)


class CheckStaged(Case):
    def test_consistent_repo_passes(self):
        self.assertEqual([], self.problems())

    def test_member_missing_from_pom(self):
        found = self.problems(pom_bytes=pom(members=MEMBERS[:2]))
        self.assertTrue(any("does not manage" in p and "meguviz-c" in p for p in found), found)

    def test_unlisted_member_in_pom(self):
        found = self.problems(pom_bytes=pom(extra=["meguviz-z"]))
        self.assertTrue(any("meguviz-z" in p for p in found), found)

    def test_member_with_another_version(self):
        found = self.problems(pom_bytes=pom(version="1.0.0"))
        self.assertTrue(any("POM version" in p for p in found), found)

    def test_pom_with_real_dependency(self):
        dependency = "<dependencies><dependency><groupId>g</groupId><artifactId>a</artifactId><version>1</version></dependency></dependencies>"
        found = self.problems(pom_bytes=pom(dependencies=dependency))
        self.assertTrue(any("real dependencies" in p for p in found), found)

    def test_pom_without_license(self):
        found = self.problems(pom_bytes=pom(license_name=None))
        self.assertTrue(any("license" in p for p in found), found)

    def test_module_without_platform_category(self):
        found = self.problems(module_bytes=module(category="library"))
        self.assertTrue(any("platform" in p for p in found), found)

    def test_module_constraint_with_another_version(self):
        found = self.problems(module_bytes=module(constraint_version="1.0.0"))
        self.assertTrue(any("lacks the constraint" in p for p in found), found)

    def test_module_with_real_dependencies(self):
        found = self.problems(module_bytes=module(dependencies=[{"group": "g", "module": "m"}]))
        self.assertTrue(any("real dependencies" in p for p in found), found)

    def test_missing_module_file(self):
        directory = self.stage()
        (directory / f"{tools.BOM}-{VERSION}.module").unlink()
        self.assertTrue(any("missing" in p for p in tools.check_staged(self.repo, VERSION, MEMBERS)))

    def test_checksum_mismatch(self):
        directory = self.stage()
        (directory / f"{tools.BOM}-{VERSION}.pom.sha256").write_text("0" * 64)
        self.assertTrue(any("does not match" in p for p in tools.check_staged(self.repo, VERSION, MEMBERS)))


class Bundle(Case):
    def build(self, sign=False, require=False):
        self.stage(sign=sign)
        out = Path(self.tmp.name) / "bundle.zip"
        return out, tools.build_bundle(self.repo, out, VERSION, MEMBERS, require)

    def test_unsigned_bundle_is_allowed_only_when_signatures_are_not_required(self):
        out, problems = self.build()
        self.assertEqual([], problems)
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
        self.assertIn(f"{tools.GROUP_PATH}/{tools.BOM}/{VERSION}/{tools.BOM}-{VERSION}.pom", names)
        self.assertFalse(any(n.endswith(".asc") for n in names))

    def test_required_signatures_fail_without_asc(self):
        _, problems = self.build(require=True)
        self.assertTrue(any(".asc" in p for p in problems), problems)

    def test_signed_bundle_passes_without_gpg_check(self):
        out, problems = self.build(sign=True, require=True)
        self.assertEqual([], problems)
        self.assertEqual([], tools.verify_bundle(out, MEMBERS, skip_gpg=True, allow_unsigned=False))

    def test_bundle_is_deterministic(self):
        first, _ = self.build()
        second = Path(self.tmp.name) / "again.zip"
        tools.build_bundle(self.repo, second, VERSION, MEMBERS, False)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_tampered_payload_is_rejected(self):
        out, _ = self.build()
        tampered = Path(self.tmp.name) / "tampered.zip"
        with zipfile.ZipFile(out) as source, zipfile.ZipFile(tampered, "w") as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename.endswith(".pom"):
                    data += b"<!-- changed -->"
                target.writestr(item.filename, data)
        problems = tools.verify_bundle(tampered, MEMBERS, skip_gpg=True, allow_unsigned=True)
        self.assertTrue(any("does not match" in p for p in problems), problems)

    def test_repository_metadata_is_rejected(self):
        out, _ = self.build()
        extra = Path(self.tmp.name) / "extra.zip"
        with zipfile.ZipFile(out) as source, zipfile.ZipFile(extra, "w") as target:
            for item in source.infolist():
                target.writestr(item.filename, source.read(item.filename))
            target.writestr(f"{tools.GROUP_PATH}/{tools.BOM}/maven-metadata.xml", "<metadata/>")
        self.assertTrue(any("maven-metadata" in p for p in tools.verify_bundle(extra, MEMBERS, True, True)))

    def test_version_already_on_central_is_rejected(self):
        out, _ = self.build()
        problems = tools.verify_bundle(out, MEMBERS, True, True, check_unpublished=True, head=lambda url: 200)
        self.assertTrue(any("already on Maven Central" in p for p in problems), problems)
        self.assertEqual([], tools.verify_bundle(out, MEMBERS, True, True, check_unpublished=True, head=lambda url: 404))

    def test_unreachable_central_is_not_treated_as_unpublished(self):
        out, _ = self.build()
        problems = tools.verify_bundle(out, MEMBERS, True, True, check_unpublished=True, head=lambda url: None)
        self.assertTrue(any("could not confirm" in p for p in problems), problems)


class CentralStatus(unittest.TestCase):
    def test_states(self):
        answers = {"meguviz-a": 200, "meguviz-b": 404, "meguviz-c": None}
        result = tools.central_status(MEMBERS, VERSION, head=lambda url: answers[url.split("/")[-3]])
        self.assertEqual({"meguviz-a": "published", "meguviz-b": "missing", "meguviz-c": "unknown (None)"}, result)

    def test_url_names_group_artifact_and_version(self):
        seen = []
        tools.central_status(["meguviz-a"], VERSION, head=lambda url: seen.append(url) or 200)
        self.assertEqual([f"{tools.CENTRAL}/io/github/jichuo1/meguviz/meguviz-a/{VERSION}/meguviz-a-{VERSION}.pom"], seen)


class Repository(unittest.TestCase):
    def test_members_file_is_clean(self):
        members = tools.read_members()
        self.assertEqual(len(members), len(set(members)))
        self.assertTrue(all(m.startswith("meguviz-") and m != tools.BOM for m in members), members)

    def test_version_is_a_release(self):
        version = tools.bom_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

    def test_members_parser_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "members.txt").write_text("# header\n\nmeguviz-a  # trailing\nmeguviz-b\n")
            self.assertEqual(["meguviz-a", "meguviz-b"], tools.read_members(Path(tmp)))
            (Path(tmp) / "members.txt").write_text("meguviz-a\nmeguviz-a\n")
            with self.assertRaises(ValueError):
                tools.read_members(Path(tmp))


if __name__ == "__main__":
    unittest.main()
