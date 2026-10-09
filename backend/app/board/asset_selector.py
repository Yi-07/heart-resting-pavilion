"""黑板选材:LLM 顺带选图标 + 白名单校验 + 熔断降级(architecture-spec §5.2 素材层)。

extract 提取调用顺带产出 assets(字段→图标 id)——不加 LLM 调用次数;
白名单校验在本模块发送前(asset_fallback WARN),连续多轮全失败走熔断
(asset_fuse_trip WARN)直接全默认图标。目录单源=前端 manifests.ts,
本包 asset_catalog.json 由 gen_catalog.py 投影,不手工编辑。
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app import logger as app_logger

logger = app_logger.logger.bind(service=app_logger.SERVICE, module="board_asset")

FieldKeyT = Literal["situation", "emotion", "thought", "behavior", "subject"]
"""可选材键:四字段槽位 + subject=板式骨架主体图标;
信念两字段留白不选材(spec 信念留白同构)"""

_ASSET_FIELDS: tuple[str, ...] = ("situation", "emotion", "thought", "behavior", "subject")
CATALOG_PATH = Path(__file__).resolve().parent / "asset_catalog.json"

FUSE_THRESHOLD = 3
"""连续 N 轮选材无效(空/全拒)→ 熔断,本轮直接全默认图标(asset_fuse_trip)"""


class _AssetChoice(BaseModel):
    assets: dict[str, str] = Field(default_factory=dict)


def load_catalog() -> dict[str, list[str]]:
    """素材目录(id→语义标签);缺文件=空目录(全走默认图标,不炸链路)。"""
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        assets: dict[str, list[str]] = data.get("assets", {})
        return {str(k): [str(t) for t in v] for k, v in assets.items()}
    except (OSError, json.JSONDecodeError):
        logger.warning("asset_catalog_missing", detail=str(CATALOG_PATH))
        return {}


def catalog_brief(catalog: dict[str, list[str]]) -> str:
    """目录 → prompt 枚举文本:id(标签1/标签2) 一行一个。"""
    return "\n".join(f"{aid} ({'/'.join(tags[:3])})" for aid, tags in catalog.items())


def asset_system(catalog: dict[str, list[str]]) -> str:
    """选材 system 段(拼进 extract 提取调用,不加调用次数)。"""
    return (
        "同时为黑板场景选图标,只从下面清单选,输出 JSON 键 assets:"
        '{"assets":{"键":"图标id"}}。'
        "键取 situation/emotion/thought/behavior 中已有信息的字段,"
        "以及 subject(画面主体:概括用户处境的核心意象,如书桌前的人/开裂的心);"
        "所有键彼此平等,有贴切图标才输出该键,没有就不输出(主体宁缺毋滥,"
        "没有合适主体就不要硬选);不同键尽量选不同图标,同一图标不要重复用在多个键上。图标清单:\n" + catalog_brief(catalog)
    )


class AssetSelector:
    """选材状态机:白名单校验 + 连续失败熔断( CollectState 挂连接,本类挂其上)。"""

    def __init__(self, catalog: dict[str, list[str]] | None = None) -> None:
        self.catalog = catalog if catalog is not None else load_catalog()
        self._fused = False
        self._streak = 0

    def validate(self, chosen: dict[str, str]) -> dict[str, str]:
        """白名单校验:非法 id 落默认(调用方兜底),合法保留;记 asset_fallback。"""
        valid: dict[str, str] = {}
        for field, asset_id in chosen.items():
            if field not in _ASSET_FIELDS:
                continue
            if asset_id in self.catalog:
                valid[field] = asset_id
            else:
                logger.warning(
                    "asset_fallback",
                    level="WARN",
                    field=field,
                    asset_id=asset_id,
                    reason="not_in_catalog",
                )
        return valid

    def apply(self, chosen: dict[str, str]) -> dict[str, str] | None:
        """LLM 选材 → 校验 → 熔断判定。返回有效选材(可空 dict=全默认);
        None=熔断生效(直接全默认图标,LLM 输出不看)。"""
        if self._fused:
            return None
        valid = self.validate(chosen)
        if not valid:
            self._streak += 1
            if self._streak >= FUSE_THRESHOLD:
                self._fused = True
                logger.warning(
                    "asset_fuse_trip",
                    level="WARN",
                    streak=self._streak,
                    threshold=FUSE_THRESHOLD,
                )
        else:
            self._streak = 0
        return valid
