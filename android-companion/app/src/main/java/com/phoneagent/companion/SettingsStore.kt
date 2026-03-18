package com.phoneagent.companion

import android.content.Context
import androidx.core.content.edit

data class CompanionSettings(
    val backendUrl: String,
    val deviceId: String,
    val token: String,
)

object SettingsStore {
    private const val PREFS = "phoneagent_companion"
    private const val KEY_BACKEND_URL = "backend_url"
    private const val KEY_DEVICE_ID = "device_id"
    private const val KEY_TOKEN = "token"

    fun load(context: Context): CompanionSettings {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return CompanionSettings(
            backendUrl = prefs.getString(KEY_BACKEND_URL, "") ?: "",
            deviceId = prefs.getString(KEY_DEVICE_ID, "phoneagent-device") ?: "phoneagent-device",
            token = prefs.getString(KEY_TOKEN, "") ?: "",
        )
    }

    fun save(context: Context, settings: CompanionSettings) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.edit {
            putString(KEY_BACKEND_URL, settings.backendUrl)
            putString(KEY_DEVICE_ID, settings.deviceId)
            putString(KEY_TOKEN, settings.token)
        }
    }
}
