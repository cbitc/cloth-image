"""ComfyUI 生图适配器（自建服务，HTTP API）。

为什么单独一个 provider：ComfyUI 不是「OpenAI 兼容端点」，它是一套**工作流执行服务**：

    POST /upload/image   multipart 上传参考图 → 返回输入目录里的文件名
    POST /prompt         {"prompt": <API 格式图>, "client_id": ...} → {"prompt_id": ...}
    GET  /history/{id}   轮询执行结果 → outputs[<node>].images[].{filename,subfolder,type}
    GET  /view           ?filename=&subfolder=&type= → 图片字节

实测要点（2026-10-15，ComfyUI 0.36.0 / AMD ROCm，http://192.168.0.102:8188）：
  - `/prompt` 校验失败返回 **HTTP 400 + node_errors**（模型名写错、节点缺输入都在这暴露）
    所以异常信息里必须带响应体片段，否则用户只看到「400」无从下手
  - `/history/{id}` 在任务结束前返回 **空对象**（不是 404）→ 只能轮询
  - 执行失败时 `status.status_str == "error"`，详情在 `status.messages` 里
  - 参考图必须是 ComfyUI **能读到的文件名**：我们存在本机 /media，它取不到
    （与 OpenAI 兼容端点同理）→ 一律先 `POST /upload/image`
  - `SaveImage` 落 `type=output`，`PreviewImage` 落 `type=temp`，两者都用 `/view` 取

生成结果直接是**图片字节**，因此不需要 `mirror_image()`（编排器优先用 image_bytes 落盘）。
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from app.abilities.base import DesignImageResult, MaterialImageResult, ReferenceImage
from app.abilities.design_generate.comfyui_workflows import (
    PRESET_DEFAULT_UNET,
    PRESET_SAMPLING,
    PRESETS,
    QWEN_IMAGE_CLIP,
    QWEN_IMAGE_VAE,
    Z_IMAGE_CLIP,
    Z_IMAGE_VAE,
    build_qwen_image_edit,
    build_z_image_turbo,
    inject_custom_workflow,
    parse_size,
    parse_workflow,
    validate_custom_workflow,
)
from app.abilities.http import ProviderError, ProviderTimeoutError, RetryingHttpClient
from app.abilities.image_ops import encode_image
from app.abilities.prompting import NEGATIVE_PROMPT, build_design_prompt

logger = logging.getLogger(__name__)

#: 上传前的参考图上限（编码为 JPEG，比视觉输入更宽松地限制体积）
UPLOAD_MAX_BYTES = 4_000_000

#: qwen_image_edit 预设能吃的参考图张数（TextEncodeQwenImageEditPlus 只有 image1..3）
QWEN_EDIT_MAX_REFS = 3


def _extract_images(
    entry: dict[str, Any], output_nodes: list[str]
) -> list[dict[str, Any]]:
    """从 history 条目里按出图节点顺序取出图片描述符。"""
    outputs = entry.get("outputs") or {}
    if not isinstance(outputs, dict):
        return []

    ordered = [node for node in output_nodes if node in outputs]
    if not ordered:
        ordered = list(outputs)

    images: list[dict[str, Any]] = []
    for node_id in ordered:
        payload = outputs.get(node_id) or {}
        for image in payload.get("images") or []:
            if isinstance(image, dict) and image.get("filename"):
                images.append(image)
    return images


def _status_summary(status: dict[str, Any]) -> str:
    """把 ComfyUI 的 execution_error 消息压成一行可读文本。"""
    for message in status.get("messages") or []:
        if not isinstance(message, (list, tuple)) or len(message) < 2:
            continue
        kind, payload = message[0], message[1]
        if kind in {"execution_error", "execution_interrupted"} and isinstance(
            payload, dict
        ):
            detail = (
                payload.get("exception_message") or payload.get("exception_type") or ""
            )
            node = payload.get("node_type") or payload.get("node_id") or ""
            return f"{kind}（节点 {node}）：{detail}" if node else f"{kind}：{detail}"
    return str(status)[:300]


def _has_execution_error(status: dict[str, Any]) -> bool:
    for message in status.get("messages") or []:
        if (
            isinstance(message, (list, tuple))
            and message
            and message[0]
            in {
                "execution_error",
                "execution_interrupted",
            }
        ):
            return True
    return False


class ComfyUIImageGenerator:
    """把「材质图 + 设计想法 + 原服装图」翻译成一次 ComfyUI 工作流执行。"""

    name = "comfyui"

    def __init__(
        self,
        base_url: str,
        model: str = "",
        *,
        preset: str = "qwen_image_edit",
        workflow_json: str = "",
        lora: str = "",
        size: str = "1024x1024",
        steps: int = 0,
        cfg: float = 0.0,
        max_refs: int = 3,
        reference_max_side: int = 1024,
        poll_timeout_s: float = 600.0,
        poll_interval_s: float = 1.0,
        download_max_bytes: int | None = None,
        timeout_s: float = 180.0,
        max_retries: int = 2,
        http_client: RetryingHttpClient | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        seed_fn: Callable[[], int] | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.preset = (preset or "").strip().lower() or "qwen_image_edit"
        if self.preset not in PRESETS:
            raise ValueError(
                f"未知的 ComfyUI 预设：{preset!r}，可选：{', '.join(PRESETS)}"
            )

        self._workflow_json = (workflow_json or "").strip()
        self._custom_graph: dict[str, Any] = {}
        self.lora = (lora or "").strip()
        self.width, self.height = parse_size(size)
        self.max_refs = max(1, max_refs)
        self.reference_max_side = reference_max_side
        self.poll_timeout_s = poll_timeout_s
        self.poll_interval_s = poll_interval_s
        self.download_max_bytes = download_max_bytes

        self._unet = (model or "").strip()
        self.model = (
            self._unet or PRESET_DEFAULT_UNET.get(self.preset) or "custom-workflow"
        )

        default_steps, default_cfg, self.sampler, self.scheduler = PRESET_SAMPLING.get(
            self.preset, PRESET_SAMPLING["qwen_image_edit"]
        )
        if self.preset == "qwen_image_edit" and self.lora:
            # Lightning 4 步 LoRA 必须配 steps=4 / cfg=1.0，否则出图糊掉
            default_steps, default_cfg = 4, 1.0
        steps = int(steps or 0)
        cfg = float(cfg or 0.0)
        self.steps = steps if steps > 0 else default_steps
        self.cfg = cfg if cfg > 0 else default_cfg

        self._sleep_fn = sleep_fn
        self._seed_fn = seed_fn or (lambda: random.randrange(0, 2**31))
        self._client_id = uuid4().hex
        self._uploads: dict[str, str] = {}
        #: ComfyUI 不返回 token 用量；编排器读不到就不打成本后缀
        self.last_usage: dict[str, Any] | None = None
        #: 本次 generate 里被丢弃的参考图（无字节/超上限）→ 编排器转成任务事件
        self.last_skipped_refs: list[str] = []

        self._http = http_client or RetryingHttpClient(
            provider=self._provider,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )

        #: 配置问题不抛异常（避免设置页保存后就 500），改为在 generate() 时明确报错
        self._config_error = ""
        if self.preset == "custom":
            if not self._workflow_json:
                self._config_error = "ComfyUI 预设为 custom，但没有填自定义工作流 JSON"
            else:
                try:
                    self._custom_graph = parse_workflow(self._workflow_json)
                    inject_custom_workflow(
                        self._custom_graph,
                        prompt="probe",
                        negative_prompt="probe",
                        reference_names=[],
                        width=self.width,
                        height=self.height,
                        seed=1,
                        steps=self.steps,
                        cfg=self.cfg,
                    )
                except ValueError as exc:
                    self._config_error = f"自定义工作流不可用：{exc}"

    # ------------------------------------------------------------------ #
    # DesignImageGenerator 协议
    # ------------------------------------------------------------------ #
    def generate(
        self,
        material_images: list[MaterialImageResult],
        design_idea: str,
        reference: ReferenceImage | None = None,
        num_candidates: int = 3,
    ) -> list[DesignImageResult]:
        if self._config_error:
            raise ProviderError(self._config_error, provider=self._provider)

        self.last_skipped_refs = []

        # 先挑出**实际**参与生图的参考图，再据此组装 prompt：
        # 候选材质图可达十几个，但参考图上限只有 max_refs 张，
        # 按候选数写 prompt 会声称存在并不存在的「参考图N」。
        if self.uses_references:
            payloads, material_tags = self._select_reference_payloads(
                material_images, reference
            )
            has_reference = any(label == "原服装图" for _, label in payloads)
            material_ref_count = len(payloads) - (1 if has_reference else 0)
            if not material_tags:  # 材质图一张都没用上 → 退回纯文字要求
                material_tags = [m.tag for m in material_images]
        else:
            # 文生图预设（z_image_turbo）不吃参考图：材质只能作为文字提示
            payloads = []
            material_tags = [m.tag for m in material_images]
            has_reference = False
            material_ref_count = 0

        prompt = build_design_prompt(
            material_tags=material_tags,
            material_images_count=material_ref_count,
            design_idea=design_idea,
            has_reference=has_reference,
        )

        # 参考图对所有候选相同 → 只上传一次（按内容哈希去重）
        names = [self._upload(data, label) for data, label in payloads]

        results: list[DesignImageResult] = []
        for index in range(max(1, num_candidates)):
            seed = self._seed_fn()
            graph, output_nodes = self._build_graph(prompt, names, seed)
            prompt_id = self._submit(graph)
            image = self._wait_for_image(prompt_id, output_nodes)
            data, content_type = self._download(image)
            results.append(
                DesignImageResult(
                    content_type=content_type,
                    image_bytes=data,
                    prompt=prompt,
                    negative_prompt=NEGATIVE_PROMPT,
                    model=self.model,
                    seed=seed,
                    rank=index,
                    used_reference=has_reference,
                )
            )
        return results

    # ------------------------------------------------------------------ #
    # 自检（供 python -m app.tools.probe --comfyui-check 使用）
    # ------------------------------------------------------------------ #
    def check_setup(self) -> list[str]:
        """联网自检：服务可达性 + 预设引用的模型文件名是否存在。返回问题清单。"""
        if self._config_error:
            return [self._config_error]

        try:
            stats = self._http.get_json(f"{self.base_url}/system_stats")
        except ProviderError as exc:
            return [f"无法连接 ComfyUI（{self.base_url}）：{exc}"]

        system = stats.get("system") or {}
        logger.info("ComfyUI 可达：version=%s", system.get("comfyui_version") or "?")

        if self.preset == "custom":
            return validate_custom_workflow(self._workflow_json)

        qwen = self.preset == "qwen_image_edit"

        wants: list[tuple[str, str, str]] = [
            ("UNETLoader", "unet_name", self._unet or PRESET_DEFAULT_UNET[self.preset]),
            (
                "CLIPLoader",
                "clip_name",
                QWEN_IMAGE_CLIP if qwen else Z_IMAGE_CLIP,
            ),
            ("VAELoader", "vae_name", QWEN_IMAGE_VAE if qwen else Z_IMAGE_VAE),
        ]
        if qwen and self.lora:
            wants.append(("LoraLoaderModelOnly", "lora_name", self.lora))

        problems: list[str] = []
        for node, field, name in wants:
            options = self._node_options(node, field)
            if options is None:
                problems.append(f"ComfyUI 缺少节点 {node}（版本过旧？）")
            elif name not in options:
                problems.append(
                    f"{node}.{field} 里没有 {name}，请检查模型文件名或改用 custom 预设"
                )
        return problems

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @property
    def _provider(self) -> str:
        return f"ComfyUI({self.preset})"

    @property
    def uses_references(self) -> bool:
        """该预设是否真的吃参考图（文生图预设不必白传一遍）。"""
        return self.preset != "z_image_turbo"

    @property
    def config_notes(self) -> list[str]:
        """provider 自报的配置问题（供 registry.config_warnings 汇总到设置页）。

        自定义工作流无法在 PUT 时校验（它只是段文本），所以把「不可用」提前到
        设置页警告里，而不是等第一次跑任务才 500。
        """
        return [self._config_error] if self._config_error else []

    def _node_options(self, node: str, field: str) -> list[str] | None:
        """读 /object_info/<node> 里某个输入的可选值；节点不存在返回 None。"""
        info = self._http.get_json(f"{self.base_url}/object_info/{node}")
        spec = (info.get(node) or {}).get("input") or {}
        raw = (spec.get("required") or {}).get(field)
        if raw is None:
            raw = (spec.get("optional") or {}).get(field)
        if not isinstance(raw, list) or not raw:
            return []
        if isinstance(raw[0], list):  # 旧格式：[[选项...], {配置}]
            return [str(item) for item in raw[0]]
        if raw[0] == "COMBO" and len(raw) > 1 and isinstance(raw[1], dict):
            return [str(item) for item in (raw[1].get("options") or [])]
        return []

    @staticmethod
    def _pick_material_refs(
        material_images: list[MaterialImageResult],
    ) -> list[MaterialImageResult]:
        """每个材质 tag 只留相似度最高的一张，再按相似度降序。

        与 openai_compatible_image 的取舍一致：否则同一个 tag 的多张图会占满
        有限的参考位，其它材质反而进不来。
        """
        best_per_tag: dict[str, MaterialImageResult] = {}
        for image in material_images:
            current = best_per_tag.get(image.tag)
            if current is None or image.similarity > current.similarity:
                best_per_tag[image.tag] = image
        return sorted(
            best_per_tag.values(), key=lambda item: item.similarity, reverse=True
        )

    def _select_reference_payloads(
        self,
        material_images: list[MaterialImageResult],
        reference: ReferenceImage | None,
    ) -> tuple[list[tuple[bytes, str]], list[str]]:
        """挑出**实际可用**的参考图，返回 (待上传项, 入选的材质 tag)。

        与「上传」分离，是为了在组装 prompt 时就知道真实的参考图张数/材质 ——
        否则 prompt 会声称存在并不存在的「参考图N」（候选数远大于实际上限）。

        任何被丢弃的参考图（无字节 / 超出上限）都记进 `last_skipped_refs`，
        由编排器转成任务事件 —— 否则用户只看到「成功」，材质参考其实没生效。
        """
        payloads: list[tuple[bytes, str]] = []
        material_tags: list[str] = []
        has_garment = False

        if reference is not None:
            if reference.image_bytes:
                payloads.append((reference.image_bytes, "原服装图"))
                has_garment = True
            else:
                logger.warning("原服装图没有字节，ComfyUI 取不到本机地址，已跳过")
                self.last_skipped_refs.append(
                    "原服装图（无本地字节，ComfyUI 无法读取外链）"
                )

        for image in self._pick_material_refs(material_images):
            if image.image_bytes:
                payloads.append((image.image_bytes, f"材质图({image.tag})"))
                material_tags.append(image.tag)
            else:
                logger.warning("材质图 %s 没有字节，已跳过", image.tag)
                self.last_skipped_refs.append(
                    f"材质图({image.tag})（无本地字节，ComfyUI 无法读取外链）"
                )

        if len(payloads) > self.max_refs:
            logger.warning(
                "参考图 %d 张超过上限 %d，已截断（优先保留原服装图与高相似度材质图）",
                len(payloads),
                self.max_refs,
            )
            self.last_skipped_refs.extend(
                f"{label}（超出参考图上限 {self.max_refs}）"
                for _, label in payloads[self.max_refs :]
            )
            payloads = payloads[: self.max_refs]
            # 被截断的材质图不能再出现在 prompt 里
            material_tags = material_tags[: len(payloads) - (1 if has_garment else 0)]

        return payloads, material_tags

    def _upload(self, data: bytes, label: str) -> str:
        digest = hashlib.sha256(data).hexdigest()[:16]
        cached = self._uploads.get(digest)
        if cached:
            return cached

        encoded, mime = encode_image(
            data, max_side=self.reference_max_side, max_bytes=UPLOAD_MAX_BYTES
        )
        filename = f"cloth_ref_{digest}.jpg"
        response = self._http.post_multipart(
            f"{self.base_url}/upload/image",
            files={"image": (filename, encoded, mime)},
            form={"overwrite": "true", "type": "input"},
        )

        name = str(response.get("name") or filename)
        subfolder = str(response.get("subfolder") or "").strip("/")
        uploaded = f"{subfolder}/{name}" if subfolder else name
        self._uploads[digest] = uploaded
        logger.info(
            "ComfyUI 上传参考图 %s（%s，%d bytes）", uploaded, label, len(encoded)
        )
        return uploaded

    def _build_graph(
        self, prompt: str, reference_names: list[str], seed: int
    ) -> tuple[dict[str, Any], list[str]]:
        if self.preset == "qwen_image_edit":
            graph = build_qwen_image_edit(
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                reference_names=reference_names[:QWEN_EDIT_MAX_REFS],
                width=self.width,
                height=self.height,
                seed=seed,
                steps=self.steps,
                cfg=self.cfg,
                unet=self._unet,
                lora=self.lora,
                sampler=self.sampler,
                scheduler=self.scheduler,
            )
            return graph, ["16"]

        if self.preset == "z_image_turbo":
            graph = build_z_image_turbo(
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                width=self.width,
                height=self.height,
                seed=seed,
                steps=self.steps,
                cfg=self.cfg,
                unet=self._unet,
                sampler=self.sampler,
                scheduler=self.scheduler,
            )
            return graph, ["9"]

        graph, output_nodes = inject_custom_workflow(
            self._custom_graph,
            prompt=prompt,
            negative_prompt=NEGATIVE_PROMPT,
            reference_names=reference_names,
            width=self.width,
            height=self.height,
            seed=seed,
            steps=self.steps,
            cfg=self.cfg,
        )
        return graph, output_nodes

    def _submit(self, graph: dict[str, Any]) -> str:
        response = self._http.post_json(
            f"{self.base_url}/prompt",
            {"prompt": graph, "client_id": self._client_id},
        )
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ProviderError(
                f"{self._provider} 未返回 prompt_id：{str(response)[:200]}",
                provider=self._provider,
            )
        logger.info("ComfyUI 已排队：%s", prompt_id)
        return str(prompt_id)

    def _wait_for_image(
        self, prompt_id: str, output_nodes: list[str]
    ) -> dict[str, Any]:
        """轮询 /history 直到出图；执行失败 / 超时抛具名异常。

        轮询期间的**网络抖动不会中止任务**：任务已经排在 ComfyUI 队列里，
        放弃只会白等一次生成（重发还会变成两次）。所以只记日志继续轮询，
        到 deadline 才报超时。
        """
        deadline = time.monotonic() + self.poll_timeout_s
        while True:
            try:
                history = self._http.get_json(f"{self.base_url}/history/{prompt_id}")
            except ProviderError as exc:
                logger.warning("%s 轮询失败，继续重试：%s", self._provider, exc)
                history = None

            entry = history.get(prompt_id) if isinstance(history, dict) else None

            if isinstance(entry, dict):
                status = entry.get("status") or {}
                if status.get("status_str") == "error" or _has_execution_error(status):
                    raise ProviderError(
                        f"{self._provider} 执行失败：{_status_summary(status)}",
                        provider=self._provider,
                    )
                if status.get("completed") or status.get("status_str") == "success":
                    images = _extract_images(entry, output_nodes)
                    if images:
                        return images[0]
                    raise ProviderError(
                        f"{self._provider} 执行完成但没有输出图片（请检查工作流是否有出图节点）",
                        provider=self._provider,
                    )

            if time.monotonic() >= deadline:
                raise ProviderTimeoutError(
                    f"{self._provider} 生成超时（{self.poll_timeout_s:.0f}s）",
                    provider=self._provider,
                )
            self._sleep_fn(self.poll_interval_s)

    def _download(self, image: dict[str, Any]) -> tuple[bytes, str]:
        query = urlencode(
            {
                "filename": str(image.get("filename") or ""),
                "subfolder": str(image.get("subfolder") or ""),
                "type": str(image.get("type") or "output"),
            }
        )
        data, content_type = self._http.get_bytes(
            f"{self.base_url}/view?{query}", max_bytes=self.download_max_bytes
        )
        if not data:
            raise ProviderError(
                f"{self._provider} 返回了空图片", provider=self._provider
            )
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return data, content_type
