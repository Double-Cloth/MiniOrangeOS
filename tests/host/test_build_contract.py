"""定义 T02 最小构建系统的静态契约。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_BUILD_FILES = (
    "Makefile",
    "config/image-layout.json",
    "tools/make_image.py",
    "boot/stage1/boot.asm",
    "boot/stage2/entry.asm",
    "boot/stage2/linker.ld",
    "kernel/arch/x86/entry.asm",
    "kernel/core/kernel.c",
    "kernel/linker.ld",
)

GENERATED_SUFFIXES = {
    ".o",
    ".d",
    ".elf",
    ".bin",
    ".map",
    ".sym",
    ".img",
}

EXPECTED_COMPONENTS = {
    "stage1": ("boot/stage1.bin", 0, 1),
    "stage2": ("boot/stage2.bin", 1, 127),
    "kernel": ("kernel/kernel.elf", 128, 1920),
}


class BuildContractTests(unittest.TestCase):
    def _read_layout(self) -> dict[str, object]:
        path = ROOT / "config/image-layout.json"
        self.assertTrue(path.is_file(), "缺少镜像布局：config/image-layout.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.fail(f"镜像布局不是有效 UTF-8 JSON：{error}")
        self.assertIsInstance(value, dict, "镜像布局顶层必须是 object")
        return value

    def test_required_build_inputs_exist(self) -> None:
        missing = [path for path in REQUIRED_BUILD_FILES if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"缺少 T02 构建输入：{missing}")

    def test_source_tree_contains_no_generated_artifacts(self) -> None:
        generated: list[str] = []
        for directory in ("boot", "kernel", "config", "tools"):
            root = ROOT / directory
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in GENERATED_SUFFIXES:
                    generated.append(path.relative_to(ROOT).as_posix())
        self.assertEqual([], generated, f"源码树出现构建产物：{generated}")

    def test_image_layout_has_one_unambiguous_source_of_truth(self) -> None:
        layout = self._read_layout()
        self.assertEqual(1, layout.get("format_version"))
        self.assertEqual(512, layout.get("sector_size"))
        self.assertEqual(64 * 1024 * 1024, layout.get("image_size_bytes"))

        components = layout.get("components")
        self.assertIsInstance(components, list, "components 必须是数组")
        assert isinstance(components, list)

        normalized: dict[str, tuple[str, int, int]] = {}
        for index, component in enumerate(components):
            self.assertIsInstance(component, dict, f"components[{index}] 必须是 object")
            assert isinstance(component, dict)
            self.assertEqual(
                {"name", "artifact", "lba", "max_sectors"},
                set(component),
                f"components[{index}] 字段不稳定",
            )
            name = component.get("name")
            artifact = component.get("artifact")
            lba = component.get("lba")
            max_sectors = component.get("max_sectors")
            self.assertIsInstance(name, str)
            self.assertIsInstance(artifact, str)
            self.assertIsInstance(lba, int)
            self.assertIsInstance(max_sectors, int)
            assert isinstance(name, str)
            assert isinstance(artifact, str)
            assert isinstance(lba, int)
            assert isinstance(max_sectors, int)
            self.assertNotIn(name, normalized, f"重复组件：{name}")
            self.assertFalse(Path(artifact).is_absolute(), f"artifact 必须相对 BUILD_DIR：{artifact}")
            self.assertNotIn("..", Path(artifact).parts, f"artifact 不得逃逸 BUILD_DIR：{artifact}")
            self.assertGreaterEqual(lba, 0)
            self.assertGreater(max_sectors, 0)
            normalized[name] = (artifact, lba, max_sectors)

        self.assertEqual(EXPECTED_COMPONENTS, normalized)

        image_sectors = int(layout["image_size_bytes"]) // int(layout["sector_size"])
        regions = sorted(
            (lba, lba + max_sectors, name)
            for name, (_, lba, max_sectors) in normalized.items()
        )
        for index, (start, end, name) in enumerate(regions):
            self.assertLessEqual(end, image_sectors, f"组件越过镜像边界：{name}")
            if index:
                self.assertGreaterEqual(
                    start,
                    regions[index - 1][1],
                    f"组件区域重叠：{regions[index - 1][2]} 与 {name}",
                )


if __name__ == "__main__":
    unittest.main()
