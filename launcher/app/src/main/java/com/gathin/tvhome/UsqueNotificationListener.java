package com.gathin.tvhome;

import android.app.Notification;
import android.app.PendingIntent;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

/** Uses only Usque's VPN notification; Android grants access to all notifications. */
public final class UsqueNotificationListener extends NotificationListenerService {
    private static volatile UsqueNotificationListener instance;

    @Override public void onListenerConnected() { instance = this; }
    @Override public void onListenerDisconnected() { instance = null; }
    @Override public void onDestroy() { if (instance == this) instance = null; super.onDestroy(); }

    private static Notification notification() {
        UsqueNotificationListener listener = instance;
        if (listener == null) return null;
        try {
            for (StatusBarNotification item : listener.getActiveNotifications()) {
                if ("io.github.georgexie2333.usque".equals(item.getPackageName()) && item.getId() == 1048)
                    return item.getNotification();
            }
        } catch (RuntimeException ignored) { }
        return null;
    }

    static boolean disconnect() {
        Notification n = notification();
        if (n == null || n.actions == null || n.actions.length != 1 || n.actions[0].actionIntent == null)
            return false;
        try { n.actions[0].actionIntent.send(); return true; }
        catch (PendingIntent.CanceledException | RuntimeException ignored) { return false; }
    }
}
