package com.kangle.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * 到点 —— 契约 §4.6 + §6.1。
 *
 * 由 AlarmScheduler 排下的 PendingIntent 触发（显式组件 + ACTION_REMIND + EXTRA_ID）。
 * 这里可能运行在一个全新的、没有 WebView 的冷启动进程里，所以真值只能从
 * ReminderStore（SharedPreferences）读。
 */
public class ReminderReceiver extends BroadcastReceiver {

    public static final String ACTION_REMIND = "com.kangle.app.ACTION_REMIND";
    public static final String EXTRA_ID      = "kangle.reminder_id";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        try {
            // 全部是同步的轻量操作（读一次 prefs + 发通知 + 排一个闹钟），
            // 远在广播的 10 秒预算内，不需要 goAsync()。
            String id = intent.getStringExtra(EXTRA_ID);
            if (id == null) return;

            Reminder r = new ReminderStore(context).find(id);
            if (r == null || !r.enabled) return;

            NotificationHelper.show(context, r);

            // 自排下一次：AlarmManager 没有正确的「每天重复」，靠这一步接成「同步一次 → 天天响」。
            // 这条不能漏 —— 漏了就是响一次之后永远沉默。
            new AlarmScheduler(context).arm(r);
        } catch (Throwable t) {
            // 兜底：receiver 抛异常在 MIUI 上会直接弹崩溃框，且会连带丢掉后面的自排
        }
    }
}
