package com.kangle.app;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.List;

/**
 * SharedPreferences 持久化 —— 契约 §4.2 + §5。
 *
 * 原生侧是闹钟唯一的可读真值：App 被杀后 WebView 连同 localStorage 一起消失，
 * AlarmManager 到点拉起的是全新进程，那里只有 Context + 应用私有存储。
 *
 * 不做单例：SharedPreferences 本身是进程级单例，多个包装实例读写同一份文件，安全。
 */
public class ReminderStore {

    public static final String PREFS_NAME    = "kangle_reminders";
    public static final String KEY_ITEMS     = "items_json";
    public static final String KEY_SYNCED_AT = "synced_at_ms";

    private final SharedPreferences mPrefs;

    public ReminderStore(Context ctx) {
        mPrefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    /** 读 items_json 并解析；空 / 坏数据返回空 List（不抛）。 */
    public List<Reminder> load() {
        String json;
        try {
            json = mPrefs.getString(KEY_ITEMS, "");
        } catch (Throwable t) {
            return new ArrayList<Reminder>();
        }
        if (json == null || json.trim().length() == 0) return new ArrayList<Reminder>();
        try {
            return Reminder.listFromJson(json, new ArrayList<String>());
        } catch (Throwable t) {
            // 顶层 JSON 坏掉（含 listFromJson 抛出的 RuntimeException）→ 空表，绝不外抛：
            // BootReceiver / ReminderReceiver 崩掉会让「重启后再也不响」。
            return new ArrayList<Reminder>();
        }
    }

    /** 覆盖写：全量快照一次 putString 原子替换，不会出现「一半新一半旧」。 */
    public void save(List<Reminder> list) {
        String json = Reminder.listToJson(list);
        try {
            // 用 commit() 而不是 apply()：receiver 的 onReceive 一返回，进程随时可能被回收，
            // apply() 的异步落盘有机会赶不上，下一次冷启动就读不到这份副本。
            mPrefs.edit().putString(KEY_ITEMS, json).commit();
        } catch (Throwable t) {
            // 落盘失败只影响下次冷启动，不该拖垮当前这次同步
        }
    }

    /** 按 id 取单条，用于 receiver 自排下一次。找不到返回 null。 */
    public Reminder find(String id) {
        if (id == null) return null;
        List<Reminder> items = load();
        for (int i = 0; i < items.size(); i++) {
            Reminder r = items.get(i);
            if (r != null && id.equals(r.id)) return r;
        }
        return null;
    }

    public void clear() {
        try {
            mPrefs.edit().remove(KEY_ITEMS).remove(KEY_SYNCED_AT).commit();
        } catch (Throwable t) {
            // 同上：清不干净也不崩
        }
    }

    public void setSyncedAt(long ms) {
        try {
            mPrefs.edit().putLong(KEY_SYNCED_AT, ms).commit();
        } catch (Throwable t) {
        }
    }

    public long syncedAt() {
        try {
            return mPrefs.getLong(KEY_SYNCED_AT, 0L);
        } catch (Throwable t) {
            return 0L;
        }
    }
}
