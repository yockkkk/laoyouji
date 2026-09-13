package com.kangle.app;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 提醒模型 —— 契约 §3.6（JSON 形状）+ §4.1（公开签名）。
 *
 * 纯数据对象 + org.json 编解码，不持有任何 Android 上下文：
 * ReminderReceiver 在冷启动进程里（没有 Activity、没有 WebView）也要能构造它。
 *
 * 只用 java.* / android.* 框架 API，禁止 AndroidX（契约 §4 前言）。
 * 注意：D8 只脱糖语言特性，不脱糖 Java 8 的库 API —— 不要用 String.join /
 * java.util.stream / java.time / Objects.requireNonNull 之类。
 */
public class Reminder {

    public static final String KIND_MEDICATION = "medication";
    public static final String KIND_GREETING   = "greeting";

    /** 本轮唯一支持的重复形态。模型不持有该字段，序列化时恒写此值（契约 §3.6）。 */
    public static final String REPEAT_DAILY = "daily";

    private static final int MAX_ID_LENGTH    = 128;
    private static final int MAX_TITLE_LENGTH = 64;

    public final String  id;
    public final String  kind;
    public final String  title;
    public final String  body;
    public final int     hour;
    public final int     minute;
    public final boolean enabled;
    public final String  planId;    // 可为 null
    public final String  elderId;   // 可为 null

    public Reminder(String id, String kind, String title, String body,
                    int hour, int minute, boolean enabled,
                    String planId, String elderId) {
        // 必填串字段归一化为 ""（绝不存 null），requestCode()/toJson() 才不可能 NPE
        this.id     = (id    == null) ? "" : id;
        this.kind   = (kind  == null) ? "" : kind;
        this.title  = (title == null) ? "" : title;
        this.body   = (body  == null) ? "" : body;
        this.hour   = hour;
        this.minute = minute;
        this.enabled = enabled;
        this.planId  = planId;
        this.elderId = elderId;
    }

    /** 校验 §3.6 的丢弃条件：id 空/超长、kind 不在枚举、title 空/超长、hour/minute 越界。 */
    public boolean isValid() {
        if (id.length() == 0 || id.length() > MAX_ID_LENGTH) return false;
        if (!KIND_MEDICATION.equals(kind) && !KIND_GREETING.equals(kind)) return false;
        if (title.length() == 0 || title.length() > MAX_TITLE_LENGTH) return false;
        if (hour < 0 || hour > 23) return false;
        if (minute < 0 || minute > 59) return false;
        return true;
    }

    /** PendingIntent / 通知 id。String.hashCode 跨进程稳定，重启后仍能取消掉自己排的闹钟。 */
    public int requestCode() {
        return id.hashCode() & 0x7fffffff;
    }

    /** 单个对象；字段缺失用默认值，不抛异常（除非调用方传进坏 JSONObject）。 */
    public static Reminder fromJson(JSONObject o) throws JSONException {
        if (o == null) return null;
        String  id      = optString(o, "id", "");
        String  kind    = optString(o, "kind", "");
        String  title   = optString(o, "title", "");
        String  body    = optString(o, "body", "");
        // hour/minute 缺失用 -1 —— 直接落进 isValid() 的越界分支被丢弃，
        // 而不是默认 0 点整，把一条坏数据变成凌晨闹钟。
        int     hour    = o.optInt("hour", -1);
        int     minute  = o.optInt("minute", -1);
        boolean enabled = o.optBoolean("enabled", true);
        String  planId  = optString(o, "planId", null);
        String  elderId = optString(o, "elderId", null);
        return new Reminder(id, kind, title, body, hour, minute, enabled, planId, elderId);
    }

    /** JSONObject.isNull(key) 对「键缺失」和「显式 JSON null」都返回 true（AOSP 行为），正是我们要的。 */
    private static String optString(JSONObject o, String key, String fallback) {
        if (o.isNull(key)) return fallback;
        return o.optString(key, fallback);
    }

    public JSONObject toJson() throws JSONException {
        JSONObject o = new JSONObject();
        o.put("id", id);
        o.put("kind", kind);
        o.put("title", title);
        o.put("body", body);
        o.put("hour", hour);
        o.put("minute", minute);
        o.put("enabled", enabled);
        // planId/elderId 显式为 null 时写 JSONObject.NULL（put 传 null 会「删键」，不是写 null）
        o.put("planId",  (planId  == null) ? JSONObject.NULL : planId);
        o.put("elderId", (elderId == null) ? JSONObject.NULL : elderId);
        o.put("repeat", REPEAT_DAILY);
        return o;
    }

    /**
     * 解析数组：非法条目丢弃并把标识记进 skipped（非对象用 "#<下标>"，非法 id 用 id 原文）。
     * 同 id 后者覆盖前者、保留首次出现顺序。永不返回 null。
     *
     * 顶层不是合法 JSON 数组时抛未受检异常（签名无 throws，只能是 RuntimeException）：
     * 调用方两条路都处理得掉 —— NativeBridge 的 catch(Throwable) 落成 bad_json 且不会
     * 误执行 apply() 清空闹钟；ReminderStore.load() 吞掉后返回空表。
     */
    public static List<Reminder> listFromJson(String arrayJson, List<String> skipped) {
        List<String> sk = (skipped != null) ? skipped : new ArrayList<String>();
        Map<String, Reminder> byId = new LinkedHashMap<String, Reminder>();

        if (arrayJson == null) return new ArrayList<Reminder>();
        String text = arrayJson.trim();
        if (text.length() == 0) return new ArrayList<Reminder>();

        JSONArray arr;
        try {
            arr = new JSONArray(text);
        } catch (JSONException e) {
            throw new RuntimeException("reminders json is not a valid array", e);
        }

        for (int i = 0; i < arr.length(); i++) {
            Object raw = arr.opt(i);
            if (!(raw instanceof JSONObject)) {       // 字符串/数字/显式 null 都是「非法对象」
                sk.add("#" + i);
                continue;
            }
            JSONObject o = (JSONObject) raw;
            Reminder r = null;
            try {
                r = fromJson(o);
            } catch (Throwable t) {
                r = null;                              // 坏对象按非法条目处理，不中断整批
            }
            if (r == null || !r.isValid()) {
                String sid = o.isNull("id") ? "" : o.optString("id", "");
                sk.add(sid.length() == 0 ? ("#" + i) : sid);
                continue;
            }
            byId.put(r.id, r);                         // 后者覆盖前者，保留首次出现顺序
        }
        return new ArrayList<Reminder>(byId.values());
    }

    /** 序列化，输出 §3.6 的规范形态。键顺序不敏感；脏条目跳过，绝不抛。 */
    public static String listToJson(List<Reminder> list) {
        JSONArray arr = new JSONArray();
        if (list != null) {
            for (int i = 0; i < list.size(); i++) {
                Reminder r = list.get(i);
                if (r == null) continue;
                try {
                    arr.put(r.toJson());
                } catch (JSONException e) {
                    // 忽略：宁可少一条副本，也不能让整次 save 失败
                }
            }
        }
        return arr.toString();
    }
}
