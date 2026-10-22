package com.rahmani.cryptoscanner

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

private const val UNIQUE_SCAN_WORK = "rahmani_crypto_periodic_scan"
private const val CHANNEL_ID = "fresh_spot_signals"

object ScanScheduler {
    fun setEnabled(context: Context, enabled: Boolean) {
        AppPrefs.setAutoScan(context, enabled)
        val manager = WorkManager.getInstance(context)
        if (!enabled) {
            manager.cancelUniqueWork(UNIQUE_SCAN_WORK)
            return
        }
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<ScanWorker>(AppPrefs.scanIntervalMinutes(context).toLong(), TimeUnit.MINUTES)
            .setConstraints(constraints)
            .build()
        manager.enqueueUniquePeriodicWork(
            UNIQUE_SCAN_WORK,
            ExistingPeriodicWorkPolicy.UPDATE,
            request
        )
    }
}

class ScanWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (!AppPrefs.autoScan(applicationContext)) return Result.success()
        val previous = AppPrefs.loadReport(applicationContext)
        val current = ScannerEngine.scan(applicationContext)
        AppPrefs.saveReport(applicationContext, current)

        if (current.success && AppPrefs.notifications(applicationContext)) {
            val previousSymbols = previous.signals.map { it.symbol }.toSet()
            val fresh = current.signals.filter { it.symbol !in previousSymbols && it.expiresAt > System.currentTimeMillis() }
            if (fresh.isNotEmpty()) SignalNotifications.show(applicationContext, fresh)
        }
        return Result.success()
    }
}

object SignalNotifications {
    fun show(context: Context, signals: List<SpotSignal>) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID,
                    "هشدار سیگنال‌های اسپات",
                    NotificationManager.IMPORTANCE_DEFAULT
                ).apply { description = "اعلان سیگنال‌های تازه و تأییدشده" }
            )
        }

        val message = signals.take(2).joinToString("\n") { signal ->
            "${signal.symbol} | ورود ${formatPrice(signal.entry)} | حدضرر ${formatPrice(signal.stopLoss)}"
        }
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pending = PendingIntent.getActivity(
            context, 1001, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("سیگنال تازهٔ Binance Spot")
            .setContentText(message)
            .setStyle(NotificationCompat.BigTextStyle().bigText(message))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        manager.notify(1001, notification)
    }
}

fun formatPrice(value: Double): String = when {
    value >= 1000 -> String.format(java.util.Locale.US, "%.2f", value)
    value >= 1 -> String.format(java.util.Locale.US, "%.4f", value)
    value >= 0.01 -> String.format(java.util.Locale.US, "%.5f", value)
    else -> String.format(java.util.Locale.US, "%.8f", value)
}
