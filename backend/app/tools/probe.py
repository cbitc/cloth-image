"""真实 provider 联调探针。

用途：在不跑完整前端流水线的前提下，用一张占位服装图验证
「材质识别」与「生图」两个真实能力是否配置正确、能否调通。

用法：
    python -m app.tools.probe                    # 识别 + 生图
    python -m app.tools.probe --image x.jpg      # 指定输入图
    python -m app.tools.probe --skip-image       # 只探识别
    python -m app.tools.probe --skip-identify    # 只探生图

注意：会**真实调用外部 API 并消耗额度**，请确认 .env 已配好再运行。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

from app.ability_config import get_ability_settings
from app.abilities.base import ReferenceImage
from app.abilities.registry import config_warnings, get_abilities
from app.config import get_settings


def _load_probe_image(path: str | None) -> bytes:
    """输入图：给了路径就用它，否则用一张内置纯色小图（不依赖任何示例素材）。"""
    if path:
        return Path(path).read_bytes()

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), (140, 150, 165)).save(buffer, format="PNG")
    return buffer.getvalue()


def _dump_usage(label: str, usage: Any) -> None:
    if not usage:
        print(f"  {label} usage: <无>")
        return
    print(f"  {label} usage: {json.dumps(usage, ensure_ascii=False)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe", description="真实 provider 联调探针")
    parser.add_argument("--skip-identify", action="store_true", help="跳过材质识别")
    parser.add_argument("--skip-image", action="store_true", help="跳过生图")
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="用作输入图的本地文件路径；省略则用内置纯色小图",
    )
    args = parser.parse_args(argv)

    ability = get_ability_settings()
    settings = get_settings()
    abilities = get_abilities()

    print("=" * 68)
    print(f"能力提供方     : {abilities.summary()}")
    print(f"识别模型       : {ability.material_identifier_model or '<未配置>'}")
    print(
        f"生图模型       : {ability.design_generator_model or '<未配置>'}"
        f"（{settings.image_size}）"
    )
    for warning in config_warnings(abilities, ability):
        print(f"[配置提醒] {warning}")
    print("=" * 68)

    image = _load_probe_image(args.image)
    print(f"\n输入图: {len(image)} bytes\n")

    tags: list[Any] = []

    if not args.skip_identify:
        print(f"[1/2] 材质识别 · provider={abilities.providers['material_identifier']}")
        try:
            tags = abilities.material_identifier.identify(
                image, "image/png", context_title="探针输入图"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [失败] {type(exc).__name__}: {exc}")
            return 1

        if not tags:
            print("  [提醒] 未识别出任何材质")
        for tag in tags:
            print(
                f"  - {tag.material} / {tag.material_en}  {tag.confidence:.0%}"
                f"  [{tag.category}]"
            )
            if tag.evidence:
                print(f"      {tag.evidence}")
        _dump_usage("识别", getattr(abilities.material_identifier, "last_usage", None))
        print()

    if not args.skip_image:
        print(f"[2/2] 生图 · provider={abilities.providers['design_generator']}")
        try:
            materials = abilities.material_search.search(tags, per_tag=1)
            results = abilities.design_generator.generate(
                materials,
                "改成收腰版型，裙摆加长到脚踝，保留原立领",
                ReferenceImage(image_bytes=image, caption="探针输入图"),
                num_candidates=1,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [失败] {type(exc).__name__}: {exc}")
            return 1

        for result in results:
            print(f"  - {result.model}  {result.external_url[:120]}")
        _dump_usage("生图", getattr(abilities.design_generator, "last_usage", None))
        print(
            "\n  提示：生图返回的是临时地址；完整流水线里 orchestrator 会下载并镜像到自有存储。"
        )

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
