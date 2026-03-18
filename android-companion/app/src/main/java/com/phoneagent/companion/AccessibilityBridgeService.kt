package com.phoneagent.companion

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class AccessibilityBridgeService : AccessibilityService() {
    data class UiSnapshot(
        val xml: String,
        val packageName: String,
        val activityName: String,
        val nodeCount: Int,
        val focusedElement: String,
        val summary: String,
    )

    override fun onServiceConnected() {
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        if (instance === this) {
            instance = null
        }
        super.onDestroy()
    }

    fun currentSnapshot(): UiSnapshot? {
        val root = rootInActiveWindow ?: return null
        val builder = StringBuilder()
        var nodeCount = 0
        val visibleTexts = mutableListOf<String>()
        val focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        builder.append("<hierarchy>")
        fun walk(node: AccessibilityNodeInfo?) {
            if (node == null) return
            nodeCount += 1
            val bounds = Rect()
            node.getBoundsInScreen(bounds)
            val text = escape(node.text?.toString().orEmpty())
            val contentDesc = escape(node.contentDescription?.toString().orEmpty())
            val resourceId = escape(node.viewIdResourceName.orEmpty())
            val className = escape(node.className?.toString().orEmpty())
            val packageName = escape(node.packageName?.toString().orEmpty())
            if (visibleTexts.size < 25) {
                val display = when {
                    text.isNotBlank() -> text
                    contentDesc.isNotBlank() -> contentDesc
                    else -> ""
                }
                if (display.isNotBlank()) visibleTexts += display
            }
            builder.append("<node")
            builder.append(" text=\"").append(text).append("\"")
            builder.append(" resource-id=\"").append(resourceId).append("\"")
            builder.append(" class=\"").append(className).append("\"")
            builder.append(" package=\"").append(packageName).append("\"")
            builder.append(" content-desc=\"").append(contentDesc).append("\"")
            builder.append(" clickable=\"").append(node.isClickable).append("\"")
            builder.append(" enabled=\"").append(node.isEnabled).append("\"")
            builder.append(" focusable=\"").append(node.isFocusable).append("\"")
            builder.append(" focused=\"").append(node.isFocused).append("\"")
            builder.append(" scrollable=\"").append(node.isScrollable).append("\"")
            builder.append(" long-clickable=\"").append(node.isLongClickable).append("\"")
            builder.append(" checkable=\"").append(node.isCheckable).append("\"")
            builder.append(" checked=\"").append(node.isChecked).append("\"")
            builder.append(" selected=\"").append(node.isSelected).append("\"")
            builder.append(" password=\"").append(node.isPassword).append("\"")
            builder.append(" bounds=\"[").append(bounds.left).append(",").append(bounds.top)
                .append("][").append(bounds.right).append(",").append(bounds.bottom).append("]\"")
            if (node.childCount == 0) {
                builder.append(" />")
            } else {
                builder.append(">")
                for (index in 0 until node.childCount) {
                    walk(node.getChild(index))
                }
                builder.append("</node>")
            }
        }
        walk(root)
        builder.append("</hierarchy>")
        val packageName = root.packageName?.toString().orEmpty()
        val activityName = root.className?.toString().orEmpty()
        val focusedElement = focused?.text?.toString()
            ?: focused?.contentDescription?.toString()
            ?: ""
        return UiSnapshot(
            xml = builder.toString(),
            packageName = packageName,
            activityName = activityName,
            nodeCount = nodeCount,
            focusedElement = focusedElement,
            summary = visibleTexts.joinToString(" | "),
        )
    }

    fun performTap(x: Int, y: Int): Boolean {
        return dispatchPointGesture(x, y, 1L)
    }

    fun performLongPress(x: Int, y: Int, durationMs: Long): Boolean {
        return dispatchPointGesture(x, y, durationMs)
    }

    fun performSwipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long): Boolean {
        val path = Path().apply {
            moveTo(x1.toFloat(), y1.toFloat())
            lineTo(x2.toFloat(), y2.toFloat())
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    fun setText(text: String): Boolean {
        val root = rootInActiveWindow ?: return false
        val target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: findEditableNode(root)
        if (target != null) {
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
            }
            if (target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                return true
            }
        }
        return false
    }

    fun performGlobalActionNamed(action: String): Boolean {
        return when (action) {
            "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
            "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
            "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
            "notifications" -> performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)
            "collapse_notifications" -> performGlobalAction(GLOBAL_ACTION_BACK)
            else -> false
        }
    }

    private fun dispatchPointGesture(x: Int, y: Int, durationMs: Long): Boolean {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    private fun findEditableNode(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        node ?: return null
        if (node.isEditable) return node
        for (index in 0 until node.childCount) {
            val editable = findEditableNode(node.getChild(index))
            if (editable != null) return editable
        }
        return null
    }

    private fun escape(value: String): String {
        return value
            .replace("&", "&amp;")
            .replace("\"", "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    }

    companion object {
        @Volatile
        var instance: AccessibilityBridgeService? = null
    }
}
