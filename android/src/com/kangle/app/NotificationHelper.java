package com.kangle.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * 通知 —— 契约 §4.8 + §7。
 *
 * 只用框架 Notification.Builder（无 AndroidX，NotificationCompat 不存在），
 * 按 Build.VERSION.SDK_INT 分支区分 26 前后的构造方式。
 * 小图标用工程自带的 res/drawable/ic_notify.xml（VectorDrawable，API 21+ 原生支持）。
 * 启动图标是 res/mipmap-{mdpi..xxxhdpi} 下的 ic_launcher.png 与 mipmap-anydpi-v26/ic_launcher.xml
 * （tools/make_icons.py 生成）；PNG 密度目录在本工具链上实测可正常打包（见 CONTRACT.md §7.3），
 * 要避开的只是 @android: 框架资源引用。
 * 注意：这行别写成 "mipmap-星号斜杠" 的形式 —— 那串字符会提前闭合本注释。
 */
public class NotificationHelper {

    public static final String CHANNEL_ID   = "kangle_reminders";
    public static final CharSequence CHANNEL_NAME = "用药与问候提醒";
    public static final int    CHANNEL_IMPORTANCE = 4;   // = NotificationManager.IMPORTANCE_HIGH

    private static final String ROUTE_MEDICATIONS = "/pages/elder/medications";
    private static final String ROUTE_HOME        = "/pages/elder/home";

    /**
     * 幂等；SDK>=26 才真正建 channel。必须在主线程调用 ——
     * Android 13 上 targetSdk<33 的应用，通知权限框就是「第一次建 channel」触发的。
     */
    public static void ensureChannel(Context ctx) {
        if (ctx == null) return;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm =
                    (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;
            if (nm.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel ch = new NotificationChannel(CHANNEL_ID, CHANNEL_NAME, CHANNEL_IMPORTANCE);
                ch.setDescription("康乐的用药与晨间问候提醒");
                ch.enableVibration(true);
                ch.setShowBadge(true);
                // 不 setSound → 走 IMPORTANCE_HIGH 的默认提示音（只有 HIGH 才弹横幅）
                nm.createNotificationChannel(ch);
            }
        }
    }

    /** 构造并 notify(r.requestCode(), n)。同一条提醒重复触发是替换，不是堆叠。 */
    public static void show(Context ctx, Reminder r) {
        if (ctx == null || r == null) return;
        NotificationManager nm =
                (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;

        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            b = new Notification.Builder(ctx, CHANNEL_ID);
        } else {
            b = new Notification.Builder(ctx);
            b.setPriority(Notification.PRIORITY_HIGH);
            b.setDefaults(Notification.DEFAULT_ALL);
        }
        b.setSmallIcon(R.drawable.ic_notify)   // 工程自带的 VectorDrawable（纯白+透明底，API 21+ 原生支持）
         .setContentTitle(r.title)
         .setContentText(r.body)
         .setTicker(r.title)
         .setCategory(Notification.CATEGORY_REMINDER)
         .setVisibility(Notification.VISIBILITY_PUBLIC)
         .setShowWhen(true)
         .setWhen(System.currentTimeMillis())
         .setAutoCancel(true)
         .setOnlyAlertOnce(false)
         .setContentIntent(contentIntent(ctx, r));

        try {
            nm.notify(r.requestCode(), b.build());
        } catch (Throwable t) {
            // 通知发不出去不该变成异常：ReminderReceiver 里 show() 之后还有 arm(r)，
            // 那一步「自排下一次」漏掉 = 从此再也不响。
        }
    }

    /** 点击通知的 PendingIntent，见 §7.2。 */
    public static PendingIntent contentIntent(Context ctx, Reminder r) {
        Intent i = new Intent(ctx, MainActivity.class);
        i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        i.putExtra(MainActivity.EXTRA_ACTION, "open");
        i.putExtra(MainActivity.EXTRA_REMINDER_ID, r.id);
        i.putExtra(MainActivity.EXTRA_ROUTE, route(r));
        i.putExtra(MainActivity.EXTRA_PAYLOAD, payloadJson(r));
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;  // API 31+ 强制
        return PendingIntent.getActivity(ctx, r.requestCode(), i, flags);
    }

    public static void cancel(Context ctx, int requestCode) {
        if (ctx == null) return;
        NotificationManager nm =
                (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm != null) nm.cancel(requestCode);
    }

    /** §3.7 的 route 映射（冻结）：medication → 吃药页，其余 → 首页。 */
    private static String route(Reminder r) {
        return Reminder.KIND_MEDICATION.equals(r.kind) ? ROUTE_MEDICATIONS : ROUTE_HOME;
    }

    /** §3.7 的完整 payload，作为 EXTRA_PAYLOAD 交给 MainActivity（H5 侧不自己拼）。 */
    private static String payloadJson(Reminder r) {
        try {
            JSONObject o = new JSONObject();
            o.put("action", "open");
            o.put("route", route(r));
            o.put("reminderId", r.id);
            o.put("kind", r.kind);
            return o.toString();
        } catch (JSONException e) {
            return "";
        }
    }
}
