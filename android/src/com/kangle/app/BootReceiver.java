package com.kangle.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * 开机 / 换包 / 改时区 / 改时间 → 从本地副本重新武装 —— 契约 §4.7 + §6.2。
 *
 * 这几件事都会清空或错位系统的闹钟表：
 *  - BOOT_COMPLETED：重启后 AlarmManager 里什么都不剩
 *  - MY_PACKAGE_REPLACED：应用升级会把已排闹钟全部清掉，不重排就从此不响
 *  - TIMEZONE_CHANGED / TIME_SET：RTC 闹钟记的是绝对时刻，墙钟变了必须重算
 *
 * 四条广播都是系统保护广播，第三方应用伪造不了（所以 exported="true" 是安全的）。
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        try {
            String action = intent.getAction();
            if (action == null) return;
            if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                    && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                    && !Intent.ACTION_TIMEZONE_CHANGED.equals(action)
                    && !Intent.ACTION_TIME_CHANGED.equals(action)) {
                return;
            }
            // apply() 本身就是幂等的「取消全部 + 重新武装」，直接复用，不要另写一份循环
            new AlarmScheduler(context).apply(new ReminderStore(context).load());
        } catch (Throwable t) {
            // 监听器里崩溃既保不住闹钟，还会弹崩溃框
        }
    }
}
