package com.rahmani.signalscanner

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject
import org.json.JSONArray
import kotlin.concurrent.thread

class SignalService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val intervalMs = 5 * 60 * 1000L
    private val reportUrl = "https://raw.githubusercontent.com/rahmani009377-tech/crypto-signal-scanner/main/signals.json"
    private val channelId = "fresh_crypto_signals"
    private val prefs by lazy { getSharedPreferences("signal_monitor", MODE_PRIVATE) }
    @Volatile private var checking = false

    private val poll = object : Runnable {
        override fun run() {
            checkReport()
            handler.postDelayed(this, intervalMs)
        }
    }

    override fun onCreate() {
        super.onCreate()
        createChannel()
        startForeground(101, serviceNotification("پایش سیگنال‌ها فعال است"))
        handler.post(poll)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    private fun checkReport() {
        if (checking) return
        checking = true
        thread(name = "signal-report-check") {
            try {
                val connection = (URL(reportUrl).openConnection() as HttpURLConnection).apply {
                    connectTimeout = 12000
                    readTimeout = 12000
                    setRequestProperty("Cache-Control", "no-cache")
                    setRequestProperty("User-Agent", "SignalScannerAndroid/1.0")
                }
                val body = try {
                    if (connection.responseCode !in 200..299) return@thread
                    connection.inputStream.bufferedReader().use { it.readText() }
                } finally {
                    connection.disconnect()
                }
                val root = JSONObject(body)
                if (root.optString("scanner_status") != "SUCCESS") return@thread
                val scanTime = root.optString("scan_time_utc")
                val scanMillis = parseTime(scanTime)
                val now = System.currentTimeMillis()
                if (scanMillis <= 0L || now - scanMillis > 35 * 60 * 1000L || scanMillis > now + 2 * 60 * 1000L) {
                    updateServiceNotification("گزارش قدیمی است؛ منتظر اسکن تازه")
                    return@thread
                }

                val signals = root.optJSONArray("spot_confirmed_signals") ?: JSONArray()
                val fresh = ArrayList<JSONObject>()
                for (i in 0 until signals.length()) {
                    val signal = signals.optJSONObject(i) ?: continue
                    if (signal.optString("status") != "CONFIRMED_15M_1H") continue
                    if (signal.optString("market_type") != "SPOT") continue
                    val expiry = parseTime(signal.optString("expires_at"))
                    if (expiry <= now) continue
                    fresh.add(signal)
                }

                val signature = fresh.joinToString("|") {
                    it.optString("symbol") + ":" + it.optString("direction") + ":" + it.optString("created_at")
                }
                val initialized = prefs.getBoolean("initialized", false)
                val previous = prefs.getString("last_signature", "") ?: ""
                if (!initialized) {
                    prefs.edit().putBoolean("initialized", true).putString("last_signature", signature).apply()
                } else if (signature.isNotBlank() && signature != previous) {
                    prefs.edit().putString("last_signature", signature).apply()
                    fresh.forEach { signal -> sendSignalNotification(signal) }
                }
                updateServiceNotification("آخرین گزارش تازه است؛ سیگنال تأییدشده: ${fresh.size}")
            } catch (_: Exception) {
                updateServiceNotification("بررسی ناموفق بود؛ دوباره تلاش می‌کنم")
            } finally {
                checking = false
            }
        }
    }

    private fun parseTime(value: String): Long = try {
        java.time.Instant.parse(value).toEpochMilli()
    } catch (_: Exception) { -1L }

    private fun sendSignalNotification(signal: JSONObject) {
        val symbol = signal.optString("symbol", "نامشخص")
        val direction = signal.optString("direction", "")
        val isBull = direction == "BULLISH"
        val label = if (isBull) "صعودی" else "نزولی"
        val price = signal.optString("price", "")
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        val notification = Notification.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("سیگنال تازه: $symbol")
            .setContentText("$label | قیمت گزارش‌شده: $price")
            .setStyle(Notification.BigTextStyle().bigText("$symbol — جهت $label. قیمت هنگام اسکن: $price. این فقط هشدار تحلیلی است؛ پیش از تصمیم قیمت فعلی و ریسک را بررسی کن."))
            .setAutoCancel(true)
            .build()
        manager.notify((symbol + signal.optString("created_at")).hashCode(), notification)
    }

    private fun serviceNotification(message: String): Notification =
        Notification.Builder(this, channelId)
            .setSmallIcon(android.R.drawable.ic_popup_sync)
            .setContentTitle("هشدار سیگنال بایننس")
            .setContentText(message)
            .setOngoing(true)
            .setContentIntent(PendingIntent.getActivity(
                this, 0, Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or if (Build.VERSION.SDK_INT >= 23) PendingIntent.FLAG_IMMUTABLE else 0
            ))
            .build()

    private fun updateServiceNotification(message: String) {
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(101, serviceNotification(message))
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(channelId, "هشدار سیگنال‌های تازه", NotificationManager.IMPORTANCE_HIGH)
            channel.description = "هشدار فقط برای سیگنال‌های اسپات تأییدشده و تازه"
            (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacks(poll)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
