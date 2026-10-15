"""真实 provider 联调探针。

用途：在不跑完整前端流水线的前提下，用一张占位服装图验证
「材质识别」与「生图」两个真实能力是否配置正确、能否调通。

用法：
    python -m app.tools.probe                    # 识别 + 生图
    python -m app.tools.probe --image x.jpg      # 指定输入图
    python -m app.tools.probe --skip-image       # 只探识别
    python -m app.tools.probe --skip-identify    # 只探生图
    python -m app.tools.probe --comfyui-check    # 只做 ComfyUI 自检（不生图，不消耗显存）

注意：会**真实调用外部 API 并消耗额度**（`--comfyui-check` 除外），请确认已配好再运行。
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
from app.abilities.prompting import build_material_summary
from app.abilities.registry import config_warnings, get_abilities
from app.config import get_settings
from app.tasks.orchestrator import material_queries


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


def _print_card(card: Any) -> None:
    """打印材质卡片（识别结果），供真机联调时肉眼看质量。"""
    if card is None or not card.regions:
        print("  [提醒] 未识别出任何材质区域")
        return

    print(f"  品类: {card.category or '<未定>'}")
    for region in card.regions:
        color = region.color
        print(
            f"  - [{region.region_type}] 主色 {color.dominant_name or '<未命名>'}"
            f" {color.dominant_hex}  图案 {region.pattern.type}"
            f"  光泽 {region.optical.gloss} / {region.optical.transparency}"
            f"  面料 {region.fabric.material or '<未定>'}（{region.fabric.category}）"
        )
        if color.palette:
            palette = "，".join(
                f"{item.get('hex')} {round(float(item.get('ratio', 0)) * 100)}%"
                for item in color.palette
                if isinstance(item, dict)
            )
            print(f"      色板: {palette}")
        print(
            f"      置信度: 颜色 {region.confidence.color:.0%}"
            f" / 图案 {region.confidence.pattern:.0%}"
            f" / 光泽 {region.confidence.gloss:.0%}"
        )
        swatch = region.swatch_bytes
        print(f"      小样: {len(swatch)} bytes" if swatch else "      小样: <无>")
        if region.swatch_crop_box:
            print(f"      裁剪框: {region.swatch_crop_box}")
        if card.evidence:
            print(f"      依据: {card.evidence}")
    summary = build_material_summary(card)
    if summary:
        print(f"  编译给生图的材质要求: {summary}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe", description="真实 provider 联调探针")
    parser.add_argument("--skip-identify", action="store_true", help="跳过材质识别")
    parser.add_argument("--skip-image", action="store_true", help="跳过生图")
    parser.add_argument(
        "--comfyui-check",
        action="store_true",
        help="只做 ComfyUI 自检（服务可达性 + 预设引用的模型文件是否存在），不生图",
    )
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

    preset_note = ""
    if abilities.providers.get("design_generator") == "comfyui":
        preset_note = f"，预设 {ability.design_generator_comfyui_preset}"

    print("=" * 68)
    print(f"能力提供方     : {abilities.summary()}")
    print(f"识别模型       : {ability.material_identifier_model or '<未配置>'}")
    print(
        f"生图模型       : {ability.design_generator_model or '<未配置>'}"
        f"（{settings.image_size}{preset_note}）"
    )
    for warning in config_warnings(abilities, ability):
        print(f"[配置提醒] {warning}")
    print("=" * 68)

    if args.comfyui_check:
        check = getattr(abilities.design_generator, "check_setup", None)
        if check is None:
            print("\n[跳过] 当前生图能力不是 comfyui，--comfyui-check 无意义")
            return 0
        print(f"\n[ComfyUI 自检] {ability.design_generator_base_url}")
        problems = check()
        if problems:
            for problem in problems:
                print(f"  [问题] {problem}")
            return 1
        print("  通过：服务可达，且预设引用的模型文件都存在")
        return 0

    image = _load_probe_image(args.image)
    print(f"\n输入图: {len(image)} bytes\n")

    card: Any = None

    if not args.skip_identify:
        print(f"[1/2] 材质识别 · provider={abilities.providers['material_identifier']}")
        try:
            card = abilities.material_identifier.identify(
                image, "image/png", context_title="探针输入图"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [失败] {type(exc).__name__}: {exc}")
            return 1

        _print_card(card)
        _dump_usage("识别", getattr(abilities.material_identifier, "last_usage", None))
        print()

    if not args.skip_image:
        print(f"[2/2] 生图 · provider={abilities.providers['design_generator']}")
        try:
            # 未识别出材质（如 --skip-identify）时不必去查面料图，直接文生图/参考图生图
            queries = material_queries(card) if card else []
            materials = (
                abilities.material_search.search(queries, per_tag=1) if queries else []
            )
            results = abilities.design_generator.generate(
                materials,
                "改成收腰版型，裙摆加长到脚踝，保留原立领",
                ReferenceImage(image_bytes=image, caption="探针输入图"),
                num_candidates=1,
                material_summary=build_material_summary(card) if card else "",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [失败] {type(exc).__name__}: {exc}")
            return 1

        for result in results:
            if result.external_url:
                origin = result.external_url[:120]
            else:
                origin = f"{len(result.image_bytes or b'')} bytes（已直接拿到字节，无需镜像）"
            print(f"  - {result.model}  {origin}")
        _dump_usage("生图", getattr(abilities.design_generator, "last_usage", None))
        print(
            "\n  提示：生图返回的是临时地址；完整流水线里 orchestrator 会下载并镜像到本地存储。"
        )

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
