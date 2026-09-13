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


# 分诊概览的字段表。**每档都要把这份键集完整交出去**：响应形状随档位变，前端
# 就得为"这个键这次有没有"写分支，漏一个分支就是白屏。少给靠值空，不靠键缺。
def _empty_overview() -> dict:
    """各键的"空"值，键集与 ``health_tools.triage_overview`` 的返回一致。
    列表/字典都新建一份 —— 响应组装处还会往上面加 disclaimer，共用同一个对象
    会让下一个请求读到上一条改过的内容。"""
    return {"level": "", "advice": "", "headline": "", "drivers": [],
            "readings": [], "latest": {}, "trends": {}, "conditions": [],
            "symptom": ""}


# "一条读数都没有"时给子女看的两句。说的必须是**"没有数据"这件事本身**，
# 不能顺着那个兜底的"保健"档编一句"平稳"出来。这一屏上档位留空，前端
# dashboard.vue 见到空档位会显示它自己的中性文案（"暂未算出"），这两句是
# headline 与 advice 位上的如实交代 —— 不写的话前端会退回"档位细节未共享"
# "哪条指标把它抬上去的"这类话，对一个从没记过数的老人同样是编。
_NO_DATA_HEADLINE = "老人还没记过指标，这边暂时看不出身体情况。"
_NO_DATA_ADVICE = "等老人记过一次血压或血糖，这里就会显示分诊档位。"


def _known_advice() -> frozenset[str]:
    """分诊引擎那张**按档位写死**的建议表（``health_rules._ADVICE``）的全部取值。

    这是 summary 档 advice 的**放行名单**：只有恰好等于表里某一句的才原样给子女。

    为什么不用"扫数字"（上一版就是 ``any(ch.isdigit() for ch in advice)``）：那张表里
    "紧急"那一句写着"拨打 120"，而 **120 是急救电话、不是任何健康读数**，``isdigit()``
    分不出这两种数字 —— 结果是家属在最需要动作指引的那一档上，唯一那句"打 120"被
    整句砍掉，前端只好退回一句"具体是哪条指标把它抬上去的"（对一个危急情况，这是最
    不该出现的搪塞）。判据不该是"句子里有没有数字"，而是"这句话是不是**原样出自那张
    固定表**"——固定表本身不含任何读数，这一点由
    ``test_every_fixed_advice_is_free_of_health_readings`` 逐句钉住。

    "看来源"还顺手堵掉了另一半：哪天有人把 ``driver.reason`` 拼进 advice（那里面
    就是"血压 178/105"，数字长在自由文本里，正则抠是抠不干净的），这条路会在名单
    外被拦下。这正是"把那条路单独堵掉"，而不是用 digit-scan 一刀切误伤 120。
    """
    from app.safety.health_rules import _ADVICE
    return frozenset(_ADVICE.values())


def _summary_headline(level: str) -> str:
    """summary 档的 headline：**重建**一句，而不是去洗 ``health_rules._headline``。

    洗是洗不干净的：那一句现在拼的是 driver.reason（"血压 178/105，中重度偏高"），
    数值长在自由文本里，靠正则抠等于赌它以后的措辞不变。按档位重写一句，天然不含
    任何数字 —— 这也正是老人端报症状时"不改原文"、这里"换一句话"的分界。
    """
    if level == "保健":
        # 与 full 档同一句，本身不含数，且它说的是"这个档位"而不是"哪个数"。
        # 只有**真有读数**（都落在保健区间）且没报症状时才走到这里 ——
        # "一条读数都没有"那一支在 filter_health_overview 里提前拦走了。
        return "各项指标平稳，注意日常保健即可。"
    return f"有需要留意的地方。分诊结论：{level}。"


def filter_health_overview(grant: PrivacyGrant, overview: dict) -> dict:
    """分诊概览按档裁剪。``full`` 原样；``summary`` 只留档位；``off`` 全空。

    这一条是"子女端嘴上说看不到数、屏幕上却印着 178/105"那件事的正解。默认档
    （``DEFAULT_HEALTH_LEVEL``）就是 summary，演示台上走的正是它，所以 summary
    这一支必须**自己**保证不含数值，而不是指望调用方记得别渲染某个字段。
    """
    if grant.allows_health("full"):
        return dict(overview)          # 一个字段都不动
    if grant.health_off:
        # 没绑定的子女走到这里。**不要**编一句"各项正常"之类的话来填空 ——
        # 把"没数据"说成"没事"，方向错了不可逆。子女端自己有中性文案。
        return _empty_overview()

    if not overview.get("latest") and not overview.get("symptom"):
        # 一条读数都没有。分诊引擎对空输入落"保健"（``overall = … if drivers else "保健"``，
        # 那是"保健优先"的兜底：**没有哪条读数越界**，不是"一切平稳"）。顺着档位重写一句
        # "平稳"，就是拿兜底当结论 —— 把"没数据"说成"没事"，方向错了不可逆，也正是
        # dashboard.vue 那段中性文案要防的事。所以这里不报档位、不报建议，如实说没数据。
        # 症状那份驱动不算数：真有症状时 level 不会是"保健"，走不到这一支。
        return {**_empty_overview(),
                "headline": _NO_DATA_HEADLINE,
                "advice": _NO_DATA_ADVICE}

    level = str(overview.get("level") or "")
    advice = str(overview.get("advice") or "")
    if advice not in _known_advice():
        # 只放行固定表里的原句（见 _known_advice 的注释：为什么不用扫数字、为什么
        # 保留 advice）。子女要的不只是"建议就医"四个字，还有"该怎么办" —— 知会子女
        # 本来就是这一档的目的（就医本身不需要子女审批），最重的那一档尤其如此。
        advice = ""
    return {
        "level": level,                # 子女该知道是"建议就医"还是"紧急"
        "advice": advice,
        "headline": _summary_headline(level),
        # drivers 整个去空，而不是只清 reason：``label`` 是"血压/血糖"，
        # 哪一类指标越的界属于明细，和 level 一起给出去就等于把 level 拆开讲了。
        "drivers": [],
        # 下面四项都是明细/原文：readings 每条带着 "178/105 mmHg"，latest 是原始
        # 数据行，trends 说"上升"等于承认有个数在涨，conditions 是病历。
        "readings": [],
        "latest": {},
        "trends": {},
        "conditions": [],
        "symptom": "",                 # 症状原文同样属明细
    }


def _rank(levels: tuple[str, ...], value: str | None) -> int:
    """粒度序：越细越小。不认识的值按最粗算（宁可少给）。"""
    try:
        return levels.index(str(value))
    except ValueError:
        return len(levels) - 1


def _normalize(levels: tuple[str, ...], value: Any, default: str) -> str:
    return str(value) if value in levels else default
