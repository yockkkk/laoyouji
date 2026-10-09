"""天气 / 地图 / 叫车 / 支付 Provider（全部 Mock + Real 空壳）。

康乐收敛为本地就近就医后，城际酒店整条砍掉（与"就近"矛盾），HotelProvider
连同 hotels.json 一并移除。这里只留下本地就医出行真正要用的四类：天气穿衣、
本地路线（高德真接口 + Mock 兜底）、叫车 ETA、模拟支付。
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import random
from datetime import date

from app.providers.external.base import derive_no, load_fixture, resolve_date

logger = logging.getLogger(__name__)

# 跨城长途是明确砍掉的方向。这几个词一旦出现在**已经规划出来的**路线里，
# 说明选错了 provider 或上游降级兜底把它放了出来 —— 本层只放行本地出行方式。
_INTERCITY_HINTS = ("高铁", "动车", "城际", "航班", "飞机", "机票", "机场")

# 本市出行只认这三种走法（"打车"走 hail_ride 那条路，不出现在路线工具里）
_LOCAL_MODES = ("公交", "地铁", "步行")


# ---------------------------------------------------------------- 天气

class WeatherProvider:
    async def get(self, city: str, date_offset: str | int | None = None) -> dict:
        raise NotImplementedError


class MockWeatherProvider(WeatherProvider):
    name = "mock_weather"

    async def get(self, city: str, date_offset: str | int | None = None) -> dict:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        data = load_fixture("weather")
        key = f"{city}|{resolve_date(date_offset)}"
        idx = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:6], 16) % len(data["templates"])
        t = data["templates"][idx]
        bias = data["city_bias"].get(city, 0)
        return {
            "ok": True, "city": city, "date": resolve_date(date_offset),
            "condition": t["condition"],
            "temp_low": t["temp_low"] + bias, "temp_high": t["temp_high"] + bias,
            # 计划书第五页直接印这一行，省得渲染器再拼一次
            "temp_range": f"{t['temp_low'] + bias}~{t['temp_high'] + bias} ℃",
            "advice": t["advice"], "umbrella": t["umbrella"],
        }


# ---------------------------------------------------------------- 地图 / 路线


def _mentions(text: str, name: str) -> bool:
    """"南京"、"南京南站"、"家（南京鼓楼区）" 指的可能是同一段路的同一头。

    地名的粒度是**模型说出口时才定的**：老人说"去北京"，模型可能填 ``北京``、
    ``北京南站``，也可能照抄上一步查到的 ``北京积水潭医院``。fixture 里只能写一种
    写法，按等号比对的话绝大多数说法都对不上 —— 对不上就没有路线，
    子智能体拿不到任何点位，子女端守护地图上是一条空线。
    """
    text, name = (text or "").strip(), (name or "").strip()
    if not text or not name:
        return False
    return name in text or text in name


# "家"是个**称呼**，不是地名：它落在哪座城，取决于老人此刻在哪座城。
_HOME_ALIAS = "家"


def _is_home(text: str) -> bool:
    """这句话说的是不是"家"这个称呼。

    只认 ``家`` 本身和 ``家（北京西城区）`` 这种"家+括号"的写法 —— 不认
    "国家大剧院""老家"这类只是碰巧含"家"字的地名，否则它们会被接到老人住址上，
    画出一个跟这句话毫不相干的起点。
    """
    return (text == _HOME_ALIAS
            or text.startswith(f"{_HOME_ALIAS}（")
            or text.startswith(f"{_HOME_ALIAS}("))


def _home_point(city: str) -> dict | None:
    """按城市取"家"的坐标；认不出的城返回 None（不编一个）。

    坐标**只有一份**，写在 hospitals.json 的 ``elder_homes`` 里 —— 医院 provider
    算"离家多远"（"离家约 1.3 公里"）用的是同一份。再抄一张表出来，两边迟早会飘：
    地图上画的家门口，和那句"离家 1.3 公里"里的家，就成了两个地方。
    """
    home = (load_fixture("hospitals").get("elder_homes") or {}).get(city or "")
    if not home:
        return None
    return {"location": home.get("name") or f"{_HOME_ALIAS}（{city}）",
            "lng": home["lng"], "lat": home["lat"]}


def _landmark(landmarks: dict, text: str, city: str = "") -> dict | None:
    """把一个说法落到一个坐标点上。没有对应地标就返回 None（不编坐标）。

    挑选顺序是"越具体越优先"：``南京南站`` 里同时含着 ``南京``，
    此时该认站不该认市；反过来只说 ``南京`` 时，就退回市中心那个点。

    ``city`` 是老人此刻所在的城（调用方从出发地文本或老人档案里认出来的）。
    "家"先按它落到 elder_homes：三座城各有一个家，而 landmarks 里只写得出一个。
    不按城市解析的话，北京的行程起点会被画到南京 —— 子女端地图上就是一条
    南京到积水潭的线，差 900 公里，老人一句"我从家出发"屏幕上就是错的。
    认不出城市就返回 None，与"查不到就说查不到"同一条口径：宁可只给大致方向，
    也不默默退回南京。
    """
    text = (text or "").strip()
    if not text:
        return None
    if _is_home(text):
        home = _home_point(city) if city else None
        if home:
            return home
        # 认不出城名：landmarks 里那个扁平的"家"已经删了，这里也没有可退的 ——
        # 落到下面的常规查表。若这句话里带着城名（"家（北京西城区）"），
        # 就退到那座城的市中心当大致方向，绝不同错到另一座城去。
    exact = [n for n in landmarks if n == text]
    inside = sorted((n for n in landmarks if n in text), key=len, reverse=True)
    outside = sorted((n for n in landmarks if text in n), key=len)
    picks = exact or inside or outside
    if not picks:
        return None
    name = picks[0]
    return {"location": name, **landmarks[name]}


def _city_of(data: dict, text: str) -> str:
    """从自由文本里认出城市（``家（南京鼓楼区）`` → 南京）；认不出返回空串。

    **认不出不等于跨城**：模型填的出发地常常就是一个"家"，里面本来就没有城名，
    拿它当"另一座城"会把每一条市内路线都误判掉。只有两端都认得出、而且不是
    同一座城，才叫跨城长途。
    """
    text = (text or "").strip()
    if not text:
        return ""
    for city in sorted(data.get("cities") or [], key=len, reverse=True):
        if city in text:
            return city
    return ""


def _announce(pick: dict) -> str:
    """给老人听的那一句：先说怎么走（分步原话），末尾再报总时长。"""
    text = (pick.get("announce") or "").strip()
    if text and not text.endswith("。"):
        text += "。"
    return f"{text}全程{pick['duration']}。"


def _end_cities(data: dict, origin: str, destination: str,
                city: str = "") -> tuple[str, str]:
    """出发地 / 目的地各自的城名，认不出给空串。

    出发地常常只写一个"家"，正文里根本没有城名 —— 这时用老人档案里的常住城市
    ``city`` 顶上。**目的地的城名不借档案里的**：借了，"家 → 外地的医院"就变成
    同一座城，再也认不出那是跨城长途。
    """
    return (_city_of(data, origin) or _city_of(data, city),
            _city_of(data, destination))


def _cross_city(data: dict, origin: str, destination: str, city: str = "") -> bool:
    """出发地与目的地不在同一座城 —— 跨城长途，康乐不做。

    两头都要认得出城市名才算数：模型填的出发地常常就是一个"家"（正文里没有城名），
    那时候看的是老人档案里的常住城市；连城市都认不出（"拉萨"）就不下定论，
    让"查不到"那条路去说实话。
    """
    o_city, d_city = _end_cities(data, origin, destination, city)
    return bool(o_city and d_city and o_city != d_city)


class MapProvider:
    async def plan_route(self, origin: str, destination: str, mode: str = "",
                         city: str = "") -> dict:
        """``city`` = 老人档案里的常住城市。出发地写"家"时正文里没有城名，
        光靠地名看不出这是在哪个城市走动，所以要由调用方把老人的城带进来。"""
        raise NotImplementedError


class MockMapProvider(MapProvider):
    """演示路线库（data/routes.json）：家 → 同城 5 家医院，每种都有三种走法。

    每条路线自带 ``alternatives``（地铁/步行），``mode`` 参数用来选其中一种；
    不选就走主路线（公交）。**库外的路一律不编**：跨城说"康乐只陪您在本市走动"，
    不认识的线路只报大致方向，时长留空 —— 编一个时间出来，老人会照着出门。
    """

    name = "mock_map"

    async def plan_route(self, origin: str, destination: str, mode: str = "",
                         city: str = "") -> dict:
        await asyncio.sleep(random.uniform(0.2, 0.4))
        data = load_fixture("routes")
        if _cross_city(data, origin, destination, city):
            return self._no_route(data, origin, destination,
                                  cross_city=True, city=city)
        o_city, d_city = _end_cities(data, origin, destination, city)

        for route in data["routes"]:
            if not (_mentions(origin, route["from"])
                    and _mentions(destination, route["to"])):
                continue
            # 同城判定：认得出的那一头如果和这条路线的城市对不上，它就**不是老人
            # 脚下这段**，跳过继续找 —— 不能让"家"这个称呼把人接到别的城市去。
            known = {c for c in (o_city, d_city) if c}
            route_city = route.get("city", "")
            if route_city and known and route_city not in known:
                continue
            options = [route] + list(route.get("alternatives") or [])
            pick = next((o for o in options if o["mode"] == mode), None) if mode else None
            pick = pick or options[0]
            return {
                "ok": True, "matched": True,
                "origin": origin, "destination": destination,
                "mode": pick["mode"], "duration": pick["duration"],
                "distance_km": route.get("distance_km"),
                "polyline": route.get("polyline") or route["points"],
                "steps": pick["steps"],
                # 三种方式一起给出去：老人可以在页面上换，模型也可以改口
                "options": [{"mode": o["mode"], "duration": o["duration"],
                             "announce": o.get("announce", ""),
                             "steps": o["steps"]} for o in options],
                "announce": _announce(pick),
                "summary": (f"从{origin}到{destination}：{pick['mode']}，"
                            f"全程{pick['duration']}。"
                            + "".join(pick["steps"])),
            }
        return self._no_route(data, origin, destination, city=city)

    @staticmethod
    def _no_route(data: dict, origin: str, destination: str,
                  cross_city: bool = False, city: str = "") -> dict:
        """查不到就说查不到：折线只画两头的直线（有坐标才画），时长留空。

        跨城那一支要额外把话说透 —— 老人问"怎么去北京"，答"只有大致方向"等于
        让他去车站碰运气；不如直接说康乐只做本市出行。

        ``city`` 是老人档案里的常住城市，用来把光秃秃的"家"归到对的那座城
        （两头的城名从这句话里能认出来时，以正文为准）。
        """
        o_city, d_city = _end_cities(data, origin, destination, city)
        ends = [pt for pt in (_landmark(data["landmarks"], origin, o_city),
                              _landmark(data["landmarks"], destination, d_city)) if pt]
        if cross_city:
            summary = (f"从{origin}到{destination}：这段路跨城了。康乐只陪您在本市"
                       f"走动，跨城的车票、机票我不查。真要去外地，让家里人陪您去。")
        else:
            summary = (f"从{origin}到{destination}：这条路线我这儿只有大致方向，"
                       f"具体怎么走、要多久，出门前问一下家里人或站里的工作人员。")
        return {
            "ok": True, "matched": False,
            "origin": origin, "destination": destination,
            "mode": "", "duration": "", "distance_km": None,
            "polyline": ends, "steps": [], "options": [],
            "announce": "", "out_of_city": cross_city,
            "summary": summary,
        }


class AmapMapProvider(MapProvider):
    """高德开放平台地图服务：联动真实 Web API 2.0 规划路线，全场景降级兜底。"""

    name = "amap_map"

    async def plan_route(self, origin: str, destination: str, mode: str = "",
                         city: str = "") -> dict:
        """优先走高德真接口；接口不认"公交/地铁/步行"、或规划出跨城长途时，落回演示库。

        ``mode`` 与 ``city`` 两个形参都要**往下传给真接口**。``city`` 是老人档案里的
        常住城市：出发地只写一个"家"时，正文里根本没有城名，真接口那一路全靠它才认得出
        "家"在哪座城（高德那边 ``AmapWebClient.plan_route`` 已经收了这个参数）。
        上一版只看了签名里有没有 mode，把 city 丢了 —— 于是裸"家"在真接口那条路上
        永远解析不出坐标，只是碰巧落回演示库才按 city 兜底成"家（南京鼓楼区）"，
        看着像对，其实老人的城根本没到过真高德层。签名先看一眼再传，调用点对签名
        保持兼容（测试里换一个两参/三参的替身也不用改这里）。
        """
        from app.providers.external.amap_service import amap_client
        # 跨城的判断要在**调用真接口之前**做：高德不认识老人，问它"家 → 外地的
        # 医院"，它照样会吐一条跨城线出来。该拦的拦在自家门口，别指望接口替我们守。
        if _cross_city(load_fixture("routes"), origin, destination, city):
            return await MockMapProvider().plan_route(origin, destination, mode, city)
        route = None
        try:
            params = inspect.signature(amap_client.plan_route).parameters
            if "city" in params:
                route = await amap_client.plan_route(origin, destination, mode, city)
            elif "mode" in params:
                route = await amap_client.plan_route(origin, destination, mode)
            else:
                route = await amap_client.plan_route(origin, destination)
        except Exception as err:                 # 真接口抖动不该让老人看见调用栈
            logger.warning("amap plan_route failed: %s", err)
        # 只认本地这三种走法。高德这边今天给的还是"市内打车/自驾"或跨城线；
        # 老人点名的和接口给的不一致时，宁可回演示库挑一条对得上的 —— 把
        # "我想走路去"翻译成"打车去"是另一种编造。等 amap_service 补上
        # 公交/步行规划，这个判断自然就放行了。
        if (route and route.get("ok") and route.get("matched")
                and not _is_intercity(route)
                and any(m in str(route.get("mode", "")) for m in _LOCAL_MODES)
                and (not mode or mode in str(route.get("mode", "")))):
            # 真接口这一条，演示库里也知道：把"念给老人听的那一句"和另外两种走法补上。
            # 高德不管老人听不听得懂，页面上要换方式（少走路/坐地铁）也总得有得换；
            # 库里不认识这段路就什么都不补，维持接口原样。
            local = await MockMapProvider().plan_route(origin, destination, mode, city)
            if local.get("matched"):
                route.setdefault("announce", local.get("announce", ""))
                route.setdefault("options", local.get("options", []))
            return route
        # 降级：演示路线库只出本地三种方式，查不到就如实说查不到
        return await MockMapProvider().plan_route(origin, destination, mode, city)


def _is_intercity(route: dict) -> bool:
    """规划结果里带着高铁/航班这类字样的，一律不算本地出行。

    amap_service 现在还会为跨城行程生成"高铁 + 市内接驳"整条线（那个文件的收敛
    是另一件事），这里先在本层把住出口：康乐不出城。
    """
    text = f"{route.get('mode', '')}{route.get('summary', '')}"
    return any(hint in text for hint in _INTERCITY_HINTS)



# ---------------------------------------------------------------- 叫车

class RideProvider:
    async def hail(self, origin: str, destination: str) -> dict:
        raise NotImplementedError


class MockRideProvider(RideProvider):
    """演示司机库（data/rides.json，3 位师傅）。"""

    name = "mock_ride"

    async def hail(self, origin: str, destination: str) -> dict:
        await asyncio.sleep(3.0)  # 模拟司机接单等待
        drivers = load_fixture("rides")["drivers"]
        # 派单按"这一趟"算，不只看出发地：老人多半都是从家出发，
        # 只用 origin 的话每次都派同一位师傅、同一块车牌，演示里一眼假。
        key = f"{origin}|{destination}"
        idx = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) % len(drivers)
        driver = drivers[idx]
        return {
            "ok": True,
            "order_no": derive_no("D", origin, destination, date.today()),
            "driver": driver["name"], "plate": driver["plate"],
            "car": driver.get("car", ""), "rating": driver["rating"],
            "eta_min": driver["eta_min"], "phone": driver.get("phone", ""),
            "note": driver.get("note", ""),
            "announce": (f"车叫好啦！{driver['name']}的车，{driver['car']}，"
                         f"车牌{driver['plate']}，{driver['eta_min']}分钟到，"
                         f"从{origin}去{destination}。到车了他会给您打电话。"),
        }


# ---------------------------------------------------------------- 支付

class PaymentProvider:
    async def pay(self, amount: float, subject: str, payer: str) -> dict:
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    name = "mock_payment"

    async def pay(self, amount: float, subject: str, payer: str) -> dict:
        await asyncio.sleep(random.uniform(0.5, 1.0))
        return {
            "ok": True,
            "transaction_no": derive_no("P", amount, subject, payer),
            "amount": amount, "subject": subject,
            "channel": "模拟支付（演示环境，未扣真实资金）",
        }
