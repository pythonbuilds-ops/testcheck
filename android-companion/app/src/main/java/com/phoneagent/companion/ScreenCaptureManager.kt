package com.phoneagent.companion

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object ScreenCaptureManager {
    private var resultCode: Int? = null
    private var resultData: android.content.Intent? = null
    private var mediaProjection: MediaProjection? = null
    private val handlerThread = HandlerThread("phoneagent-capture").apply { start() }
    private val handler = Handler(handlerThread.looper)

    fun createCaptureIntent(context: Context): android.content.Intent {
        val manager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        return manager.createScreenCaptureIntent()
    }

    fun storePermission(context: Context, resultCode: Int, data: android.content.Intent) {
        this.resultCode = resultCode
        this.resultData = data
        val manager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection?.stop()
        mediaProjection = manager.getMediaProjection(resultCode, data)
    }

    fun hasPermission(): Boolean = mediaProjection != null

    fun captureJpegBase64(context: Context, maxWidth: Int, quality: Int): Result<String> {
        val projection = mediaProjection ?: return Result.failure(IllegalStateException("Screenshot permission not granted"))
        val metrics = context.resources.displayMetrics
        val width = metrics.widthPixels
        val height = metrics.heightPixels
        val density = metrics.densityDpi
        val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        val latch = CountDownLatch(1)
        var imageBytes: ByteArray? = null
        var virtualDisplay: VirtualDisplay? = null
        try {
            reader.setOnImageAvailableListener({ r ->
                val image = r.acquireLatestImage() ?: return@setOnImageAvailableListener
                val plane = image.planes[0]
                val buffer: ByteBuffer = plane.buffer
                val pixelStride = plane.pixelStride
                val rowStride = plane.rowStride
                val rowPadding = rowStride - pixelStride * width
                val bitmap = Bitmap.createBitmap(width + rowPadding / pixelStride, height, Bitmap.Config.ARGB_8888)
                bitmap.copyPixelsFromBuffer(buffer)
                image.close()
                val cropped = Bitmap.createBitmap(bitmap, 0, 0, width, height)
                val scaled = if (cropped.width > maxWidth) {
                    val ratio = maxWidth.toFloat() / cropped.width.toFloat()
                    Bitmap.createScaledBitmap(cropped, maxWidth, (cropped.height * ratio).toInt(), true)
                } else {
                    cropped
                }
                val stream = ByteArrayOutputStream()
                scaled.compress(Bitmap.CompressFormat.JPEG, quality, stream)
                imageBytes = stream.toByteArray()
                latch.countDown()
            }, handler)

            virtualDisplay = projection.createVirtualDisplay(
                "phoneagent-capture",
                width,
                height,
                density,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.surface,
                null,
                handler,
            )

            if (!latch.await(1200, TimeUnit.MILLISECONDS) || imageBytes == null) {
                return Result.failure(IllegalStateException("Timed out waiting for screen capture"))
            }
            val encoded = Base64.encodeToString(imageBytes, Base64.NO_WRAP)
            return Result.success(encoded)
        } finally {
            virtualDisplay?.release()
            reader.close()
        }
    }
}
