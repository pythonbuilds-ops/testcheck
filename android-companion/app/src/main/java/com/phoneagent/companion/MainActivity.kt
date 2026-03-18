package com.phoneagent.companion

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {
    private lateinit var backendUrlInput: EditText
    private lateinit var deviceIdInput: EditText
    private lateinit var deviceTokenInput: EditText
    private lateinit var statusText: TextView

    private val screenshotPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK && result.data != null) {
            ScreenCaptureManager.storePermission(this, result.resultCode, result.data!!)
            setStatus("Screenshot permission granted")
        } else {
            setStatus("Screenshot permission not granted")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        backendUrlInput = findViewById(R.id.backendUrlInput)
        deviceIdInput = findViewById(R.id.deviceIdInput)
        deviceTokenInput = findViewById(R.id.deviceTokenInput)
        statusText = findViewById(R.id.statusText)

        val settings = SettingsStore.load(this)
        backendUrlInput.setText(settings.backendUrl)
        deviceIdInput.setText(settings.deviceId)
        deviceTokenInput.setText(settings.token)

        findViewById<Button>(R.id.saveButton).setOnClickListener {
            saveSettings()
        }
        findViewById<Button>(R.id.startServiceButton).setOnClickListener {
            saveSettings()
            val intent = Intent(this, BridgeForegroundService::class.java)
            ContextCompat.startForegroundService(this, intent)
            setStatus("Bridge service starting")
        }
        findViewById<Button>(R.id.accessibilityButton).setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<Button>(R.id.notificationButton).setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
        findViewById<Button>(R.id.screenshotButton).setOnClickListener {
            screenshotPermissionLauncher.launch(ScreenCaptureManager.createCaptureIntent(this))
        }
    }

    private fun saveSettings() {
        val settings = CompanionSettings(
            backendUrl = backendUrlInput.text.toString().trim(),
            deviceId = deviceIdInput.text.toString().trim(),
            token = deviceTokenInput.text.toString().trim(),
        )
        SettingsStore.save(this, settings)
        Toast.makeText(this, "Settings saved", Toast.LENGTH_SHORT).show()
        setStatus("Settings saved")
    }

    private fun setStatus(message: String) {
        statusText.text = message
    }
}
