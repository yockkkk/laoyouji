package com.kangle.app;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import java.lang.reflect.Method;
import java.util.Calendar;
import java.util.List;

/**
 * 排期 —— 契约 §4.3 + §6。
 *
 * 唯一的排期入口是 apply()（声明式全量覆盖）；到点自排下一次走 arm()。
 * 两级降级：精确拿不到就退不精确，两条路都必须能跑通、且都不许崩（§6.3）。
 */
public class AlarmScheduler {

    public static final String MODE_EXACT   = "exact";
    public static final String MODE_INEXACT = "inexact";

    private final Context      mContext;
    private final AlarmManager mAlarmManager;
    private final ReminderStore mStore;

    public AlarmScheduler(Context ctx) {
        mContext = ctx;
        mAlarmManager = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        mStore = new ReminderStore(ctx);
    }

    /**
     * 声明式全量覆盖，顺序写死：cancelAll → save → setSyncedAt → 对每条 enabled 的 arm。
     * 顺序不能换：反过来 cancelAll() 会把刚写进去的副本一起清掉。
     * 返回值即 syncReminders 的 mode 字段。
     */
    public String apply(List<Reminder> list) {
        cancelAll();
        mStore.save(list);
        mStore.setSyncedAt(System.currentTimeMillis());
        if (list != null) {
            for (int i = 0; i < list.size(); i++) {
                Reminder r = list.get(i);
                if (r != null && r.enabled) arm(r);
            }
        }
        return mode();
    }

    /** 单条武装。先算 nextTriggerMillis（严格 > now），再到点自排也走这条。 */
    public void arm(Reminder r) {
        if (r == null || !r.isValid() || mAlarmManager == null) return;

        long t = nextTriggerMillis(r.hour, r.minute);
        PendingIntent pi = broadcast(r, PendingIntent.FLAG_UPDATE_CURRENT);
        if (pi == null) return;

        int sdk = Build.VERSION.SDK_INT;
        try {
            if (canScheduleExact()) {
                setExact(sdk, t, pi);
            } else {
                setInexact(sdk, t, pi);
            }
        } catch (Throwable first) {
            // 精确权限被 ROM 临时收回 / 系统拒绝 —— 退到不精确，绝不崩（§3.5 的降级精神）
            try {
                setInexact(sdk, t, pi);
            } catch (Throwable second) {
                // 连降级都被拒：放弃这一条，也不让异常冒到 receiver 外面
            }
        }
    }

    /** 单条取消。Intent 必须与武装时逐字一致，否则静默失败、积出幽灵闹钟。 */
    public void cancel(Reminder r) {
        if (r == null || mAlarmManager == null) return;
        PendingIntent pi = broadcast(r, PendingIntent.FLAG_NO_CREATE);
        if (pi != null) mAlarmManager.cancel(pi);
    }

    /** 取消全部：对 store.load() 里每条 cancel()，再清空 store。 */
    public void cancelAll() {
        List<Reminder> existing = mStore.load();
        for (int i = 0; i < existing.size(); i++) {
            cancel(existing.get(i));
        }
        mStore.clear();
    }

    /**
     * API 30 的 android.jar 里没有 canScheduleExactAlarms 符号（API 31 才有），只能反射。
     * 拿不准就返回 false 走降级 —— 宁可漂几分钟也不能崩。
     */
    public boolean canScheduleExact() {
        if (Build.VERSION.SDK_INT < 31) return true;   // 31 之前没有这道限制
        try {
            Method m = AlarmManager.class.getMethod("canScheduleExactAlarms");
            Object r = m.invoke(mAlarmManager);
            return Boolean.TRUE.equals(r);
        } catch (Throwable t) {
            return false;
        }
    }

    public String mode() {
        return canScheduleExact() ? MODE_EXACT : MODE_INEXACT;
    }

    /** 下一次触发毫秒数：设备本地时区，今天该时刻已过则顺延一天。 */
    public static long nextTriggerMillis(int hour, int minute) {
        Calendar c = Calendar.getInstance();
        c.set(Calendar.HOUR_OF_DAY, hour);
        c.set(Calendar.MINUTE, minute);
        c.set(Calendar.SECOND, 0);
        c.set(Calendar.MILLISECOND, 0);
        long t = c.getTimeInMillis();
        if (t <= System.currentTimeMillis()) {
            // 用 Calendar.add 而不是 +24h：跨夏令时那天才不会偏一小时
            c.add(Calendar.DAY_OF_YEAR, 1);
            t = c.getTimeInMillis();
        }
        return t;
    }

    // ---- 内部：三条 SDK 分支对应 §6.3 的表 ----

    private void setExact(int sdk, long t, PendingIntent pi) {
        if (sdk >= 23) {
            mAlarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, t, pi);
        } else {
            mAlarmManager.setExact(AlarmManager.RTC_WAKEUP, t, pi);       // setExact 是 API 19 起
        }
    }

    private void setInexact(int sdk, long t, PendingIntent pi) {
        if (sdk >= 23) {
            mAlarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, t, pi);   // API 23 起才有
        } else {
            mAlarmManager.set(AlarmManager.RTC_WAKEUP, t, pi);
        }
    }

    /**
     * PendingIntent 身份 = 显式组件 + action + requestCode，三者少一个 cancel 就失败。
     * flags 固定 FLAG_UPDATE_CURRENT | (SDK>=23 ? FLAG_IMMUTABLE : 0)（API 31+ 强制 IMMUTABLE）。
     */
    private PendingIntent broadcast(Reminder r, int baseFlags) {
        Intent i = new Intent(mContext, ReminderReceiver.class);
        i.setAction(ReminderReceiver.ACTION_REMIND);
        i.putExtra(ReminderReceiver.EXTRA_ID, r.id);
        int flags = baseFlags;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
        return PendingIntent.getBroadcast(mContext, r.requestCode(), i, flags);
    }
}
