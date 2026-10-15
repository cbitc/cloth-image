"""Fake 材质识别：基于图片内容哈希确定性输出「材质卡片」（仅供测试）。

输出结构与真实 VLM 适配器一致：逐区域的 A 层视觉属性 + B/C 层字段 +
逐字段置信度 + 真实裁剪出的材质小样（用 `image_ops.crop_normalized`）。
"""

from __future__ import annotations

import hashlib
import random

from app.abilities.base import (
    BehaviorInfo,
    ColorInfo,
    FabricInfo,
    MaterialCardResult,
    MaterialRegionResult,
    OpticalInfo,
    PatternInfo,
    RegionConfidence,
)
from app.abilities.image_ops import crop_normalized
from app.taxonomy import CATEGORY_OPTIONS, GLOSS_LEVELS, PATTERN_TYPES, load_taxonomy

GLOSS_TEXT = {
    "哑光": "表面哑光、无明显反射",
    "微光": "表面有柔和光泽",
    "缎面": "表面光泽强、有大面积反光",
    "金属光": "表面呈金属质感高光",
}
DRAPE_TEXT = {
    "挺括": "挺括有骨感、不易变形",
    "适中": "软硬均衡",
    "垂坠": "垂坠感强、悬垂自然",
}
PATTERN_TEXT = {
    "纯色": "未见图案、颜色均匀",
    "条纹": "可见平行条纹",
    "格纹": "可见十字交织格纹",
    "碎花": "可见散布小花图案",
    "定位印花": "可见成组定位印花",
}
#: 确定性的色板池（避开纯黑纯白，便于 UI 断言）
PALETTE_POOL: tuple[tuple[str, str], ...] = (
    ("#2B3A4A", "深灰蓝"),
    ("#C8C2B8", "米灰"),
    ("#7A4B3A", "棕红"),
    ("#3E6B57", "墨绿"),
    ("#D9C6A5", "浅卡其"),
    ("#8E5C8A", "紫红"),
)


class FakeMaterialIdentifier:
    name = "fake"

    def identify(
        self,
        image_bytes: bytes | None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> MaterialCardResult:
        seed_src = image_bytes if image_bytes else image_url.encode("utf-8")
        digest = hashlib.sha256(seed_src or b"fake-seed").hexdigest()
        rng = random.Random(int(digest[:16], 16))

        item = rng.choice(load_taxonomy())
        gloss = rng.choice(list(GLOSS_LEVELS))
        pattern = rng.choice(list(PATTERN_TYPES))
        dominant_hex, dominant_name = rng.choice(PALETTE_POOL)
        other_hex, _ = rng.choice(PALETTE_POOL)
        ratio = round(rng.uniform(0.55, 0.85), 2)

        region = MaterialRegionResult(
            region_id="body",
            region_type="身片",
            color=ColorInfo(
                dominant_hex=dominant_hex,
                dominant_name=dominant_name,
                lab=[
                    round(rng.uniform(20, 80), 1),
                    round(rng.uniform(-40, 40), 1),
                    round(rng.uniform(-40, 40), 1),
                ],
                palette=[
                    {"hex": dominant_hex, "ratio": ratio},
                    {"hex": other_hex, "ratio": round(1 - ratio, 2)},
                ],
                distribution="整体均匀",
            ),
            pattern=PatternInfo(
                type=pattern,
                scale="条宽约 0.8cm" if pattern == "条纹" else "",
                direction="竖向" if pattern == "条纹" else "",
                layout="全身",
            ),
            optical=OpticalInfo(gloss=gloss, transparency="不透明"),
            fabric=FabricInfo(
                material=item["material"],
                material_en=item["material_en"],
                category=item["category"],
                confidence=round(rng.uniform(0.45, 0.93), 2),
            ),
            # C 层：MVP 期不做推断，一律填默认值
            behavior=BehaviorInfo(
                weight="中等", drape="适中", confidence=0.0, is_default=True
            ),
            confidence=RegionConfidence(
                color=round(rng.uniform(0.4, 0.98), 2),
                pattern=round(rng.uniform(0.4, 0.98), 2),
                gloss=round(rng.uniform(0.4, 0.98), 2),
            ),
            swatch_content_type="image/jpeg",
        )

        if image_bytes:
            cropped = crop_normalized(image_bytes, self._box(rng))
            if cropped is not None:
                region.swatch_bytes, region.swatch_crop_box = cropped

        confidences = [
            region.confidence.color,
            region.confidence.pattern,
            region.confidence.gloss,
        ]
        return MaterialCardResult(
            category=rng.choice(list(CATEGORY_OPTIONS)),
            regions=[region],
            evidence=self._evidence(item, gloss, pattern, rng),
            note="",
            overall_confidence=round(sum(confidences) / len(confidences), 4),
        )

    @staticmethod
    def _box(rng: random.Random) -> list[float]:
        """一块合法（不越界、不小于 5%）的确定性裁剪框。"""
        left = round(rng.uniform(0.10, 0.35), 2)
        top = round(rng.uniform(0.10, 0.35), 2)
        return [left, top, round(left + 0.4, 2), round(top + 0.4, 2)]

    @staticmethod
    def _evidence(item: dict, gloss: str, pattern: str, rng: random.Random) -> str:
        return (
            f"{GLOSS_TEXT.get(gloss, '表面质感适中')}；"
            f"{PATTERN_TEXT.get(pattern, '图案待确认')}；"
            f"{DRAPE_TEXT['适中']}，与「{item.get('category', '面料')}」特征一致。"
        )


class FakeMaterialIdentifier:
    name = "fake"

    def identify(
        self,
        image_bytes: bytes | None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> MaterialCardResult:
        seed_src = image_bytes if image_bytes else image_url.encode("utf-8")
        digest = hashlib.sha256(seed_src or b"fake-seed").hexdigest()
        rng = random.Random(int(digest[:16], 16))

        item = rng.choice(load_taxonomy())
        gloss = rng.choice(list(GLOSS_LEVELS))
        pattern = rng.choice(list(PATTERN_TYPES))
        dominant_hex, dominant_name = rng.choice(PALETTE_POOL)
        other_hex, _ = rng.choice(PALETTE_POOL)
        ratio = round(rng.uniform(0.55, 0.85), 2)

        region = MaterialRegionResult(
            region_id="body",
            region_type="身片",
            color=ColorInfo(
                dominant_hex=dominant_hex,
                dominant_name=dominant_name,
                lab=[
                    round(rng.uniform(20, 80), 1),
                    round(rng.uniform(-40, 40), 1),
                    round(rng.uniform(-40, 40), 1),
                ],
                palette=[
                    {"hex": dominant_hex, "ratio": ratio},
                    {"hex": other_hex, "ratio": round(1 - ratio, 2)},
                ],
                distribution="整体均匀",
            ),
            pattern=PatternInfo(
                type=pattern,
                scale="条宽约 0.8cm" if pattern == "条纹" else "",
                direction="竖向" if pattern == "条纹" else "",
                layout="全身",
            ),
            optical=OpticalInfo(gloss=gloss, transparency="不透明"),
            fabric=FabricInfo(
                material=item["material"],
                material_en=item["material_en"],
                category=item["category"],
                confidence=round(rng.uniform(0.45, 0.93), 2),
            ),
            # C 层：MVP 期不做推断，一律填默认值
            behavior=BehaviorInfo(
                weight="中等", drape="适中", confidence=0.0, is_default=True
            ),
            confidence=RegionConfidence(
                color=round(rng.uniform(0.4, 0.98), 2),
                pattern=round(rng.uniform(0.4, 0.98), 2),
                gloss=round(rng.uniform(0.4, 0.98), 2),
            ),
            swatch_content_type="image/jpeg",
        )

        if image_bytes:
            cropped = crop_normalized(image_bytes, self._box(rng))
            if cropped is not None:
                region.swatch_bytes, region.swatch_crop_box = cropped

        confidences = [
            region.confidence.color,
            region.confidence.pattern,
            region.confidence.gloss,
        ]
        return MaterialCardResult(
            category=rng.choice(list(CATEGORY_OPTIONS)),
            regions=[region],
            evidence=self._evidence(item, gloss, pattern),
            note="",
            overall_confidence=round(sum(confidences) / len(confidences), 4),
        )

    @staticmethod
    def _box(rng: random.Random) -> list[float]:
        """一块合法（不越界、不小于 5%）的确定性裁剪框。"""
        left = round(rng.uniform(0.10, 0.35), 2)
        top = round(rng.uniform(0.10, 0.35), 2)
        return [left, top, round(left + 0.4, 2), round(top + 0.4, 2)]

    @staticmethod
    def _evidence(item: dict, gloss: str, pattern: str) -> str:
        return (
            f"{GLOSS_TEXT.get(gloss, '表面质感适中')}；"
            f"{PATTERN_TEXT.get(pattern, '图案待确认')}；"
            f"{DRAPE_TEXT['适中']}，与「{item.get('category', '面料')}」特征一致。"
        )
