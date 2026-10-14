"""Fake 材质识别：基于图片内容哈希确定性输出 tag + 可能度分析（仅供测试）。"""

from __future__ import annotations

import hashlib
import random

from app.abilities.base import MaterialTagResult
from app.taxonomy import load_taxonomy

GLOSS_TEXT = {
    "高": "表面光泽强、反射明显",
    "中": "表面有柔和光泽",
    "低": "表面哑光、无明显反射",
}
DRAPE_TEXT = {
    "高": "垂坠感强、悬垂自然",
    "中": "垂坠适中、软硬均衡",
    "低": "挺括有骨感、不易变形",
}
EVIDENCE_TEMPLATES = [
    "{gloss}，{drape}，符合该材质的典型外观。",
    "从织纹与反光判断：{gloss}，{drape}。",
    "面料表现{gloss}，{drape}，与「{category}」特征一致。",
]


class FakeMaterialIdentifier:
    name = "fake"

    def identify(
        self,
        image_bytes: bytes | None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> list[MaterialTagResult]:
        seed_src = image_bytes if image_bytes else image_url.encode("utf-8")
        digest = hashlib.sha256(seed_src or b"fake-seed").hexdigest()
        rng = random.Random(int(digest[:16], 16))

        taxonomy = load_taxonomy()
        k = rng.choice([2, 2, 3, 3, 4])
        picked = rng.sample(taxonomy, min(k, len(taxonomy)))

        confidences = sorted(
            (round(rng.uniform(0.45, 0.93), 2) for _ in range(len(picked))),
            reverse=True,
        )

        results: list[MaterialTagResult] = []
        for rank, (item, confidence) in enumerate(zip(picked, confidences)):
            results.append(
                MaterialTagResult(
                    material=item["material"],
                    material_en=item["material_en"],
                    confidence=confidence,
                    evidence=self._evidence(item, rng),
                    category=item["category"],
                    rank=rank,
                )
            )
        return results

    @staticmethod
    def _evidence(item: dict, rng: random.Random) -> str:
        template = rng.choice(EVIDENCE_TEMPLATES)
        return template.format(
            gloss=GLOSS_TEXT.get(item.get("gloss", ""), "表面质感适中"),
            drape=DRAPE_TEXT.get(item.get("drape", ""), "垂坠与挺括适中"),
            category=item.get("category", "面料"),
        )
