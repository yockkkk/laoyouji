"""数据隐私分级 —— 位置与健康数据的越级防线（架构第 3 条第 3 点、红线 R6）。

以前这块只有一个 ``routes_privacy.py`` 在**存**授权等级，没有任何地方**用**它：
子女端看板照样把实时坐标、用药明细、体检解读原文一并端出去。存了不用的开关
比没有开关更糟 —— 它让人以为已经管住了。

这里补的就是"用"的那一半。三条设计：

1. **降级是数据变形，不是报错**。老人把位置降到 ``city`` 档，子女不该看到
   "无权限"的红叉，而该看到"在北京"——粗到该有的粒度就停。功能不消失，
   精度消失。这样老人才敢真去调这个开关。
2. **fail-closed 在身份那一层**：没有 ``family_bindings``（老人没认这个子女）
   → 全部 off，一个字段都不给。授权行缺失只是"没细调过"，取**粗档**默认；
   身份缺失是"没这层关系"，直接不给。两者不能混为一谈。
3. **只出不进**：过滤发生在数据离开后端的那一刻（API 响应组装处），
   不在写入端。库里存的始终是全量事实，老人把开关调回去，历史照样看得见。

等级词表（由细到粗，顺序即权限强弱）：

- 位置 ``realtime`` ⊃ ``city`` ⊃ ``off``
- 健康 ``full`` ⊃ ``summary`` ⊃ ``off``
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 由细到粗。索引即"粒度序"，比较大小就是比较权限强弱。
LOCATION_LEVELS = ("realtime", "city", "off")
HEALTH_LEVELS = ("full", "summary", "off")

# 授权行缺失时的默认档：不是 off（那绑定就没意义了），也不是最细档
# （那等于默认全开）—— 取中间档。方向只有一个：没明说，就只给粗粒度。
DEFAULT_LOCATION_LEVEL = "city"
DEFAULT_HEALTH_LEVEL = "summary"

MASKED = "老人未开放此项"

# 行政区划后缀：粗化时截到最先出现的那一级。
_DISTRICT_SUFFIXES = ("区", "县", "旗")
_CITY_SUFFIXES = ("市", "自治州", "地区", "盟")

# city 档的备注**重建**（而不是去洗原文）。洗自由文本是漏的：
# "位置偏离规划路线：XX路8号" 这种句子里地址就藏在冒号后面。
_CITY_NOTE = {
    "normal": "在路上，一切正常。",
    "arrived": "已经到地方了。",
    "off_route": "位置和计划路线不一样，请留意。（老人只开放到城市级，具体地点未共享）",
}


@dataclass(frozen=True)
class PrivacyGrant:
    """一对（老人, 子女）此刻的可见范围。不可变：一次响应用同一份判断。"""

    elder_id: str
    child_id: str
    location_level: str = DEFAULT_LOCATION_LEVEL
    health_level: str = DEFAULT_HEALTH_LEVEL
    bound: bool = True

    @property
    def location_off(self) -> bool:
        return not self.bound or self.location_level == "off"

    @property
    def health_off(self) -> bool:
        return not self.bound or self.health_level == "off"

    def allows_location(self, need: str = "realtime") -> bool:
        """需要 ``need`` 这么细的位置，当前授权够不够。

        两侧都宁可少给：**存储侧**的生词由 ``_rank`` 按最粗算（授权只会更小），
        **需求侧**的生词直接不给 —— 调用点哪天写成 ``allows_location("gps")``，
        那是笔误，不该让它悄悄把闸门打开。
        """
        if self.location_off or need not in LOCATION_LEVELS:
            return False
        return _rank(LOCATION_LEVELS, self.location_level) <= _rank(
            LOCATION_LEVELS, need)

    def allows_health(self, need: str = "full") -> bool:
        if self.health_off or need not in HEALTH_LEVELS:
            return False
        return _rank(HEALTH_LEVELS, self.health_level) <= _rank(HEALTH_LEVELS, need)

    def to_dict(self) -> dict:
        return {"elder_id": self.elder_id, "child_id": self.child_id,
                "location_level": "off" if not self.bound else self.location_level,
                "health_level": "off" if not self.bound else self.health_level,
                "bound": self.bound}


def denied(elder_id: str = "", child_id: str = "") -> PrivacyGrant:
    """没有绑定关系时的空授权：什么都不给。"""
    return PrivacyGrant(elder_id=elder_id, child_id=child_id,
                        location_level="off", health_level="off", bound=False)


class PrivacyService:
    """``ctx.privacy``：查授权 + 按档裁剪出库数据 + 记审计。"""

    def __init__(self, repo: Any):
        self._repo = repo

    # ------------------------------------------------------------------ 查授权
    async def grant_for(self, elder_id: str, child_id: str) -> PrivacyGrant:
        """先验身份，再看细档。身份不成立就是 ``denied()``（fail-closed）。"""
        binding = await self._repo.find_one(
            "family_bindings", {"elder_id": elder_id, "child_id": child_id})
        if not binding:
            logger.info("隐私：%s 与 %s 无绑定关系，按最严处理", child_id, elder_id)
            return denied(elder_id, child_id)

        row = await self._repo.find_one(
            "privacy_permissions", {"elder_id": elder_id, "child_id": child_id})
        return PrivacyGrant(
            elder_id=elder_id, child_id=child_id,
            location_level=_normalize(LOCATION_LEVELS,
                                      (row or {}).get("location_level"),
                                      DEFAULT_LOCATION_LEVEL),
            health_level=_normalize(HEALTH_LEVELS,
                                    (row or {}).get("health_level"),
                                    DEFAULT_HEALTH_LEVEL),
        )

    # ------------------------------------------------------------------ 审计
    async def audit(self, grant: PrivacyGrant, scope: str, *,
                    action: str = "privacy_read") -> None:
        """谁在什么档位下读了什么，落 audit_log。老人端"谁看过我"要用它。"""
        try:
            await self._repo.insert("audit_log", {
                "actor_id": grant.child_id,
                "action": action,
                "target": grant.elder_id,
                "detail": {"scope": scope,
                           "location_level": grant.location_level,
                           "health_level": grant.health_level,
                           "bound": grant.bound},
            })
        except Exception as exc:  # noqa: BLE001 —— 审计失败不该让子女端白屏
            logger.warning("隐私审计写入失败: %s", exc)


# ---------------------------------------------------------------- 纯函数：裁剪
# 都是纯函数（不碰库、不碰 ctx），所以能直接断言"这一档到底给了什么"。

def coarse_place(place: str) -> str:
    """地名粗化到"市/区"。取不出行政区划就只留前 3 个字，绝不原样透出。

    ``"北京市海淀区新街口外大街31号"`` → ``"北京市海淀区"``
    ``"积水潭医院骨科门诊楼"``        → ``"积水潭"``（够子女知道"在哪一片"）
    """
    text = (place or "").strip()
    if not text:
        return ""
    for suffix in (*_DISTRICT_SUFFIXES, *_CITY_SUFFIXES):
        index = text.find(suffix)
        if index >= 0:
            return text[: index + len(suffix)]
    return text[:3]


def filter_checkpoint(grant: PrivacyGrant, checkpoint: dict) -> dict | None:
    """一条位置上报按档裁剪。``off`` 返回 None（整条不出库）。

    ``city`` 档砍掉经纬度 —— 留着坐标就等于没降级，地图上一样能戳到门牌号。
    """
    if grant.location_off:
        return None
    out = dict(checkpoint)
    if grant.allows_location("realtime"):
        out["precision"] = "realtime"
        return out
    out["location"] = coarse_place(out.get("location", ""))
    out["lng"] = None
    out["lat"] = None
    out["precision"] = "city"
    if out.get("note"):
        out["note"] = _CITY_NOTE.get(str(out.get("status") or ""),
                                     "有一条位置更新。")
    return out


def filter_alert(grant: PrivacyGrant, alert: dict) -> dict | None:
    """守护告警：位置关了也要给"有异常"这件事，只是不给在哪。

    这是刻意的取舍 —— 把告警本身也藏掉，守护功能就等于没有；
    而"有异常"不含位置信息，不构成越级。
    """
    if not grant.bound:
        return None
    if grant.location_off:
        out = {k: v for k, v in alert.items() if k not in ("location", "lng", "lat")}
        out["location"] = MASKED
        out["note"] = "有一次行程异常。老人没开放位置共享，具体地点看不到。"
        out["precision"] = "off"
        return out
    return filter_checkpoint(grant, alert)


def filter_medication(grant: PrivacyGrant, medication: dict) -> dict | None:
    """用药条目：``full`` 给药名剂量，``summary`` 只给"吃了没"，``off`` 不给。

    ``summary`` 档为什么还留服药情况：子女最需要的是"我妈今天按时吃药了吗"，
    这一条不涉及"吃的什么病的药"。药名才是敏感的那一半。
    """
    if grant.health_off:
        return None
    if grant.allows_health("full"):
        return dict(medication)
    taken = medication.get("taken_today") or {}
    return {
        "drug": MASKED,
        "dose": "",
        "times": list((medication.get("times") or [])),
        "taken_today": dict(taken),
        "precision": "summary",
    }


def filter_health_text(grant: PrivacyGrant, text: str) -> str:
    """体检解读这类**原文**：只有 ``full`` 档能看。``summary`` 只知道"有一份"。"""
    if grant.health_off:
        return ""
    if grant.allows_health("full"):
        return text
    return "老人有一份体检解读记录，具体内容未开放。"


def _rank(levels: tuple[str, ...], value: str | None) -> int:
    """粒度序：越细越小。不认识的值按最粗算（宁可少给）。"""
    try:
        return levels.index(str(value))
    except ValueError:
        return len(levels) - 1


def _normalize(levels: tuple[str, ...], value: Any, default: str) -> str:
    return str(value) if value in levels else default
