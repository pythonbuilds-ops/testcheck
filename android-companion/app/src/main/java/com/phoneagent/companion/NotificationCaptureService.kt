package com.phoneagent.companion

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class NotificationCaptureService : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        refreshSnapshot()
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        refreshSnapshot()
    }

    private fun refreshSnapshot() {
        lastNotifications = activeNotifications?.mapNotNull { sbn ->
            val extras = sbn.notification.extras
            val title = extras.getCharSequence("android.title")?.toString().orEmpty()
            val text = extras.getCharSequence("android.text")?.toString().orEmpty()
            val combined = listOf(title, text).filter { it.isNotBlank() }.joinToString(" - ")
            combined.ifBlank { null }
        } ?: emptyList()
    }

    companion object {
        @Volatile
        private var lastNotifications: List<String> = emptyList()

        fun snapshotText(): String {
            return if (lastNotifications.isEmpty()) "" else lastNotifications.joinToString("\n")
        }
    }
}
