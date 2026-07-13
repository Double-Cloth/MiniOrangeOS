"""验证工具链源码缓存由已锁定归档完整绑定。"""

from __future__ import annotations

import io
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests.host import test_environment_runtime


class ToolchainProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_environment_runtime.EnvironmentRuntimeTests()

    def _write_rich_archive(self, archive: Path) -> None:
        staging = archive.parent / "rich-binutils-staging"
        source = staging / "binutils-1.0"
        (source / "nested").mkdir(parents=True)
        (source / "bin").mkdir()
        configure = source / "configure"
        configure.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            "printf 'configure component=binutils cwd=%s args=%s\\n' "
            '"$PWD" "$*" >> "$FAKE_TOOLCHAIN_LOG"\n'
            "printf '%s\\n' binutils > .minios-component\n",
            encoding="utf-8",
            newline="\n",
        )
        configure.chmod(0o755)
        payload = source / "nested" / "payload.txt"
        payload.write_text("trusted payload\n", encoding="utf-8", newline="\n")
        shutil.copy2(payload, source / "nested" / "payload-copy.txt")
        helper = source / "bin" / "helper.sh"
        helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
        helper.chmod(0o755)
        (source / "nested" / "payload-link").symlink_to("payload.txt")
        os.link(payload, source / "nested" / "payload-hardlink.txt")
        with tarfile.open(archive, "w:xz", dereference=False) as tar:
            tar.add(source, arcname="binutils-1.0")
        shutil.rmtree(staging)

    def _write_fixture(
        self, temporary_root: Path
    ) -> tuple[Path, Path, dict[str, str]]:
        fixture_root, log, env = self.fixture._write_toolchain_fixture(
            temporary_root
        )
        archive = temporary_root / "rich-binutils.tar.xz"
        self._write_rich_archive(archive)
        self.fixture._replace_fixture_archive(fixture_root, "binutils", archive)
        return fixture_root, log, env

    def test_source_manifest_is_stable_and_up_to_date_skips_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_root, log, env = self._write_fixture(Path(temporary_directory))
            first = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)

            stamp = (
                Path(env["MINIOS_ENV_ROOT"])
                / "sources/binutils-1.0/.minios-source.env"
            )
            stamp_text = stamp.read_text(encoding="utf-8")
            self.assertIn("source_manifest_version=2\n", stamp_text)
            self.assertRegex(
                stamp_text,
                r"(?m)^source_manifest_sha256=[0-9a-f]{64}$",
            )
            log_before = log.read_bytes()

            second = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertIn("toolchain_status=up-to-date", second.stdout)
            self.assertEqual(log_before, log.read_bytes())

    def test_trusted_legacy_stamp_is_upgraded_without_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_root, log, env = self._write_fixture(Path(temporary_directory))
            first = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)

            stamp = (
                Path(env["MINIOS_ENV_ROOT"])
                / "sources/binutils-1.0/.minios-source.env"
            )
            legacy_stamp = "\n".join(
                line
                for line in stamp.read_text(encoding="utf-8").splitlines()
                if not line.startswith("source_manifest_")
            ) + "\n"
            self.assertEqual(4, len(legacy_stamp.splitlines()))
            stamp.write_text(legacy_stamp, encoding="utf-8", newline="\n")
            log_before = log.read_bytes()

            second = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertIn("toolchain_status=up-to-date", second.stdout)
            self.assertEqual(log_before, log.read_bytes())
            self.assertRegex(
                stamp.read_text(encoding="utf-8"),
                r"(?m)^source_manifest_sha256=[0-9a-f]{64}$",
            )

    def test_manifest_digest_cannot_be_rebased_by_editing_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture_root, log, env = self._write_fixture(Path(temporary_directory))
            first = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)

            environment_root = Path(env["MINIOS_ENV_ROOT"])
            stamp = environment_root / "sources/binutils-1.0/.minios-source.env"
            stamp.write_text(
                "\n".join(
                    (
                        f"source_manifest_sha256={'0' * 64}"
                        if line.startswith("source_manifest_sha256=")
                        else line
                    )
                    for line in stamp.read_text(encoding="utf-8").splitlines()
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            log_before = log.read_bytes()
            marker = environment_root / "state/toolchain.env"
            marker_before = marker.read_bytes()

            forced = self.fixture._run_fixture_toolchain(
                fixture_root, "--force", env=env
            )
            self.assertNotEqual(0, forced.returncode)
            self.assertEqual(log_before, log.read_bytes())
            self.assertEqual(marker_before, marker.read_bytes())

    def test_manifest_preflight_rejects_top_level_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, _, env = self.fixture._write_toolchain_fixture(
                temporary_root
            )
            archive = temporary_root / "top-level-symlink.tar.xz"
            root_link = tarfile.TarInfo("binutils-1.0")
            root_link.type = tarfile.SYMTYPE
            root_link.linkname = "../escaped-source"
            configure_data = b"#!/bin/sh\nexit 0\n"
            configure = tarfile.TarInfo("binutils-1.0/configure")
            configure.mode = 0o755
            configure.size = len(configure_data)
            with tarfile.open(archive, "w:xz") as tar:
                tar.addfile(root_link)
                tar.addfile(configure, io.BytesIO(configure_data))
            self.fixture._replace_fixture_archive(
                fixture_root, "binutils", archive
            )

            result = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertNotEqual(0, result.returncode)
            self.assertRegex(
                (result.stdout + result.stderr).lower(),
                r"unsafe archive member|归档成员",
            )
            self.assertFalse((temporary_root / "escaped-source").exists())

    def test_hardlink_chain_has_stable_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, log, env = self.fixture._write_toolchain_fixture(
                temporary_root
            )
            archive = temporary_root / "hardlink-chain.tar.xz"
            configure_data = (
                b"#!/bin/sh\nset -eu\n"
                b"printf 'configure component=binutils cwd=%s args=%s\\n' "
                b'"$PWD" "$*" >> "$FAKE_TOOLCHAIN_LOG"\n'
                b"printf '%s\\n' binutils > .minios-component\n"
            )
            payload_data = b"trusted payload\n"
            with tarfile.open(archive, "w:xz") as tar:
                for name in ("binutils-1.0", "binutils-1.0/nested"):
                    directory = tarfile.TarInfo(name)
                    directory.type = tarfile.DIRTYPE
                    directory.mode = 0o755
                    tar.addfile(directory)
                configure = tarfile.TarInfo("binutils-1.0/configure")
                configure.mode = 0o755
                configure.size = len(configure_data)
                tar.addfile(configure, io.BytesIO(configure_data))
                payload = tarfile.TarInfo("binutils-1.0/nested/payload.txt")
                payload.mode = 0o644
                payload.size = len(payload_data)
                tar.addfile(payload, io.BytesIO(payload_data))
                chain_b = tarfile.TarInfo("binutils-1.0/nested/chain-b")
                chain_b.type = tarfile.LNKTYPE
                chain_b.linkname = "binutils-1.0/nested/payload.txt"
                tar.addfile(chain_b)
                chain_a = tarfile.TarInfo("binutils-1.0/nested/chain-a")
                chain_a.type = tarfile.LNKTYPE
                chain_a.linkname = "binutils-1.0/nested/chain-b"
                tar.addfile(chain_a)
            self.fixture._replace_fixture_archive(
                fixture_root, "binutils", archive
            )

            first = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, first.returncode, first.stderr)
            log_before = log.read_bytes()
            second = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertIn("toolchain_status=up-to-date", second.stdout)
            self.assertEqual(log_before, log.read_bytes())

    def test_hardlink_cycle_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            fixture_root, _, env = self.fixture._write_toolchain_fixture(
                temporary_root
            )
            archive = temporary_root / "hardlink-cycle.tar.xz"
            with tarfile.open(archive, "w:xz") as tar:
                root = tarfile.TarInfo("binutils-1.0")
                root.type = tarfile.DIRTYPE
                root.mode = 0o755
                tar.addfile(root)
                for name, target in (
                    ("cycle-a", "cycle-b"),
                    ("cycle-b", "cycle-a"),
                ):
                    member = tarfile.TarInfo(f"binutils-1.0/{name}")
                    member.type = tarfile.LNKTYPE
                    member.linkname = f"binutils-1.0/{target}"
                    tar.addfile(member)
            self.fixture._replace_fixture_archive(
                fixture_root, "binutils", archive
            )

            result = self.fixture._run_fixture_toolchain(fixture_root, env=env)
            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "hardlink cycle",
                (result.stdout + result.stderr).lower(),
            )
            self.assertFalse(
                (Path(env["MINIOS_ENV_ROOT"]) / "sources/binutils-1.0").exists()
            )

    def test_force_rejects_every_source_tree_drift_before_configure(self) -> None:
        mutations = (
            "configure-content",
            "ordinary-content",
            "executable-mode",
            "symlink-target",
            "hardlink-to-copy",
            "copy-to-hardlink",
            "hardlink-repoint",
            "added-entry",
            "deleted-entry",
            "source-root-mode",
        )
        for mutation in mutations:
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                temporary_root = Path(temporary_directory)
                fixture_root, log, env = self._write_fixture(temporary_root)
                first = self.fixture._run_fixture_toolchain(fixture_root, env=env)
                self.assertEqual(0, first.returncode, first.stderr)

                environment_root = Path(env["MINIOS_ENV_ROOT"])
                source = environment_root / "sources/binutils-1.0"
                marker = environment_root / "state/toolchain.env"
                marker_before = marker.read_bytes()
                log_before = log.read_bytes()
                executed = temporary_root / "tampered-configure-executed"

                if mutation == "configure-content":
                    configure = source / "configure"
                    configure.write_text(
                        "#!/bin/sh\n"
                        f"printf executed > {executed}\n"
                        "exit 77\n",
                        encoding="utf-8",
                        newline="\n",
                    )
                    configure.chmod(0o755)
                elif mutation == "ordinary-content":
                    (source / "nested/payload.txt").write_text(
                        "tampered\n", encoding="utf-8", newline="\n"
                    )
                elif mutation == "executable-mode":
                    (source / "bin/helper.sh").chmod(0o644)
                elif mutation == "symlink-target":
                    link = source / "nested/payload-link"
                    link.unlink()
                    link.symlink_to("../configure")
                elif mutation == "hardlink-to-copy":
                    hardlink = source / "nested/payload-hardlink.txt"
                    hardlink.unlink()
                    shutil.copy2(source / "nested/payload.txt", hardlink)
                elif mutation == "copy-to-hardlink":
                    copy = source / "nested/payload-copy.txt"
                    copy.unlink()
                    os.link(source / "nested/payload.txt", copy)
                elif mutation == "hardlink-repoint":
                    hardlink = source / "nested/payload-hardlink.txt"
                    hardlink.unlink()
                    os.link(source / "nested/payload-copy.txt", hardlink)
                elif mutation == "added-entry":
                    (source / "nested/added.txt").write_text(
                        "added\n", encoding="utf-8", newline="\n"
                    )
                elif mutation == "deleted-entry":
                    (source / "nested/payload.txt").unlink()
                elif mutation == "source-root-mode":
                    source.chmod(0o700)
                else:  # pragma: no cover - 保持测试表完整性
                    self.fail(f"未知 mutation：{mutation}")

                forced = self.fixture._run_fixture_toolchain(
                    fixture_root, "--force", env=env
                )
                self.assertNotEqual(0, forced.returncode)
                self.assertNotIn("toolchain_status=built", forced.stdout)
                self.assertEqual(log_before, log.read_bytes())
                self.assertEqual(marker_before, marker.read_bytes())
                self.assertFalse(executed.exists(), "执行了被篡改的 configure")


if __name__ == "__main__":
    unittest.main()
