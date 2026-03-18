package com.phoneagent.companion

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class BridgeForegroundService : Service() {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var webSocket: WebSocket? = null
    private var reconnectScheduled = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(1001, NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("PhoneAgent Companion")
            .setContentText("Waiting for backend connection")
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .build())
        connect()
        scheduleHeartbeats()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        connect()
        return START_STICKY
    }

    override fun onDestroy() {
        webSocket?.close(1000, "service destroyed")
        mainHandler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    private fun connect() {
        val settings = SettingsStore.load(this)
        if (settings.backendUrl.isBlank()) {
            return
        }
        val wsUrl = settings.backendUrl
            .trimEnd('/')
            .replace("https://", "wss://")
            .replace("http://", "ws://") + "/ws/device/${settings.deviceId}"
        val request = Request.Builder().url(wsUrl).build()
        webSocket?.cancel()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                reconnectScheduled = false
                webSocket.send(helloPayload(settings).toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleIncoming(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                scheduleReconnect()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect() {
        if (reconnectScheduled) return
        reconnectScheduled = true
        mainHandler.postDelayed({ connect() }, 5000)
    }

    private fun scheduleHeartbeats() {
        mainHandler.postDelayed(object : Runnable {
            override fun run() {
                val payload = JSONObject()
                    .put("type", "heartbeat")
                    .put("capabilities", capabilitiesJson())
                    .put("device_info", deviceInfoJson())
                    .put("metadata", metadataJson())
                webSocket?.send(payload.toString())
                mainHandler.postDelayed(this, 15000)
            }
        }, 15000)
    }

    private fun handleIncoming(text: String) {
        val payload = JSONObject(text)
        if (payload.optString("type") != "rpc_request") return
        Thread {
            val id = payload.getString("id")
            val method = payload.getString("method")
            val params = payload.optJSONObject("params") ?: JSONObject()
            try {
                val result = handleRpc(method, params)
                val response = JSONObject()
                    .put("type", "rpc_response")
                    .put("id", id)
                    .put("ok", true)
                    .put("result", result)
                webSocket?.send(response.toString())
            } catch (t: Throwable) {
                val response = JSONObject()
                    .put("type", "rpc_response")
                    .put("id", id)
                    .put("ok", false)
                    .put("error", t.message ?: t.javaClass.simpleName)
                webSocket?.send(response.toString())
            }
        }.start()
    }

    private fun handleRpc(method: String, params: JSONObject): JSONObject {
        return when (method) {
            "health" -> JSONObject()
                .put("current_package", AccessibilityBridgeService.instance?.currentSnapshot()?.packageName ?: "unknown")
                .put("current_activity", AccessibilityBridgeService.instance?.currentSnapshot()?.activityName ?: "")
                .put("capabilities", capabilitiesJson())
                .put("device_info", deviceInfoJson())
                .put("metadata", metadataJson())
            "get_capabilities" -> JSONObject().put("capabilities", capabilitiesJson())
            "get_device_info" -> deviceInfoJson()
            "dump_ui_tree" -> {
                val snapshot = AccessibilityBridgeService.instance?.currentSnapshot()
                    ?: throw IllegalStateException("Accessibility service is not active")
                JSONObject()
                    .put("xml", snapshot.xml)
                    .put("package", snapshot.packageName)
                    .put("activity", snapshot.activityName)
                    .put("node_count", snapshot.nodeCount)
                    .put("focused_element", snapshot.focusedElement)
                    .put("summary", snapshot.summary)
                    .put("metadata", metadataJson())
            }
            "capture_screenshot" -> {
                val maxWidth = params.optInt("max_width", 720)
                val quality = params.optInt("quality", 60)
                val image = ScreenCaptureManager.captureJpegBase64(this, maxWidth, quality).getOrThrow()
                JSONObject().put("image_base64", image)
            }
            "tap" -> {
                requireAccessibility().performTap(params.getInt("x"), params.getInt("y"))
                JSONObject()
            }
            "long_press" -> {
                requireAccessibility().performLongPress(params.getInt("x"), params.getInt("y"), params.optLong("duration_ms", 1000L))
                JSONObject()
            }
            "swipe" -> {
                requireAccessibility().performSwipe(
                    params.getInt("x1"),
                    params.getInt("y1"),
                    params.getInt("x2"),
                    params.getInt("y2"),
                    params.optLong("duration_ms", 300L),
                )
                JSONObject()
            }
            "set_text" -> {
                if (!requireAccessibility().setText(params.getString("text"))) {
                    throw IllegalStateException("Could not set text on the current focused field")
                }
                JSONObject()
            }
            "global_action" -> {
                if (!requireAccessibility().performGlobalActionNamed(params.getString("action"))) {
                    throw IllegalStateException("Unsupported global action")
                }
                JSONObject()
            }
            "open_app" -> {
                openApp(params.getString("package"))
                JSONObject()
            }
            "open_url" -> {
                launchIntent(Intent(Intent.ACTION_VIEW, Uri.parse(params.getString("url"))))
                JSONObject()
            }
            "send_sms" -> {
                val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${params.getString("phone_number")}"))
                intent.putExtra("sms_body", params.getString("message"))
                launchIntent(intent)
                JSONObject()
            }
            "make_call" -> {
                launchIntent(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${params.getString("phone_number")}")))
                JSONObject()
            }
            "open_settings" -> {
                openSettings(params.optString("settings_page"))
                JSONObject()
            }
            "get_notifications" -> JSONObject().put("text", NotificationCaptureService.snapshotText())
            "set_clipboard" -> {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("phoneagent", params.getString("text")))
                JSONObject()
            }
            "list_packages" -> {
                val filter = params.optString("filter").lowercase()
                val packages = packageManager.getInstalledApplications(0)
                    .map { it.packageName }
                    .filter { filter.isBlank() || it.lowercase().contains(filter) }
                JSONObject().put("packages", JSONArray(packages))
            }
            else -> throw IllegalArgumentException("Unsupported rpc method: $method")
        }
    }

    private fun requireAccessibility(): AccessibilityBridgeService {
        return AccessibilityBridgeService.instance
            ?: throw IllegalStateException("Accessibility service is not active")
    }

    private fun helloPayload(settings: CompanionSettings): JSONObject {
        return JSONObject()
            .put("type", "hello")
            .put("token", settings.token)
            .put("capabilities", capabilitiesJson())
            .put("device_info", deviceInfoJson())
            .put("metadata", metadataJson())
    }

    private fun capabilitiesJson(): JSONObject {
        return JSONObject()
            .put("ui_tree", true)
            .put("screenshots", ScreenCaptureManager.hasPermission())
            .put("gestures", true)
            .put("text_input", true)
            .put("global_actions", true)
            .put("notifications", true)
            .put("open_url", true)
            .put("calls", true)
            .put("sms", true)
            .put("package_lookup", true)
            .put("clipboard", true)
            .put("can_force_stop", false)
            .put("can_install_apk", false)
            .put("can_file_transfer", false)
            .put("raw_shell", false)
            .put("metadata", metadataJson())
    }

    private fun deviceInfoJson(): JSONObject {
        val metrics = resources.displayMetrics
        return JSONObject()
            .put("model", Build.MODEL)
            .put("brand", Build.BRAND)
            .put("android_version", Build.VERSION.RELEASE)
            .put("sdk_version", Build.VERSION.SDK_INT)
            .put("screen_width", metrics.widthPixels)
            .put("screen_height", metrics.heightPixels)
    }

    private fun metadataJson(): JSONObject {
        return JSONObject()
            .put("accessibility_active", AccessibilityBridgeService.instance != null)
            .put("notification_access_active", NotificationCaptureService.snapshotText().isNotBlank())
            .put("screenshot_permission", ScreenCaptureManager.hasPermission())
    }

    private fun openApp(packageOrName: String) {
        val intent = packageManager.getLaunchIntentForPackage(packageOrName)
            ?: packageManager.getInstalledApplications(0)
                .firstOrNull { app ->
                    val label = packageManager.getApplicationLabel(app).toString()
                    app.packageName.equals(packageOrName, ignoreCase = true) || label.equals(packageOrName, ignoreCase = true)
                }
                ?.let { packageManager.getLaunchIntentForPackage(it.packageName) }
            ?: throw IllegalArgumentException("App not found: $packageOrName")
        launchIntent(intent)
    }

    private fun openSettings(page: String) {
        val action = when (page.lowercase()) {
            "wifi" -> Settings.ACTION_WIFI_SETTINGS
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
            "display" -> Settings.ACTION_DISPLAY_SETTINGS
            "sound" -> Settings.ACTION_SOUND_SETTINGS
            "apps" -> Settings.ACTION_APPLICATION_SETTINGS
            "battery" -> Settings.ACTION_BATTERY_SAVER_SETTINGS
            "storage" -> Settings.ACTION_INTERNAL_STORAGE_SETTINGS
            "location" -> Settings.ACTION_LOCATION_SOURCE_SETTINGS
            "security" -> Settings.ACTION_SECURITY_SETTINGS
            "accounts" -> Settings.ACTION_SYNC_SETTINGS
            "accessibility" -> Settings.ACTION_ACCESSIBILITY_SETTINGS
            "developer" -> Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS
            "about" -> Settings.ACTION_DEVICE_INFO_SETTINGS
            else -> Settings.ACTION_SETTINGS
        }
        launchIntent(Intent(action))
    }

    private fun launchIntent(intent: Intent) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(CHANNEL_ID, "PhoneAgent Companion", NotificationManager.IMPORTANCE_LOW)
            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        private const val CHANNEL_ID = "phoneagent_companion"
    }
}
