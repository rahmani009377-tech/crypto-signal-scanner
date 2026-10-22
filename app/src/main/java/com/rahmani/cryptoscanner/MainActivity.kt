package com.rahmani.cryptoscanner

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    ScannerHome()
                }
            }
        }
    }
}

@Composable
private fun ScannerHome() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var report by remember { mutableStateOf(AppPrefs.loadReport(context)) }
    var scanning by remember { mutableStateOf(false) }
    var autoScan by remember { mutableStateOf(AppPrefs.autoScan(context)) }
    var intervalMinutes by remember { mutableStateOf(AppPrefs.scanIntervalMinutes(context)) }
    var notifications by remember { mutableStateOf(AppPrefs.notifications(context)) }
    var minVolume by remember { mutableStateOf(AppPrefs.minVolumeMillions(context)) }
    var minChange by remember { mutableStateOf(AppPrefs.minChangePct(context)) }

    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        notifications = granted
        AppPrefs.setNotifications(context, granted)
    }

    LaunchedEffect(Unit) {
        report = AppPrefs.loadReport(context)
        autoScan = AppPrefs.autoScan(context)
        intervalMinutes = AppPrefs.scanIntervalMinutes(context)
        notifications = AppPrefs.notifications(context)
    }

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        report = AppPrefs.loadReport(context)
        autoScan = AppPrefs.autoScan(context)
        intervalMinutes = AppPrefs.scanIntervalMinutes(context)
        notifications = AppPrefs.notifications(context)
    }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("Rahmani Crypto Scanner", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("اسکنر بازار اسپات بایننس • فقط خواندن اطلاعات عمومی")
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("وضعیت اسکن", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text(if (report.success) "وضعیت: آماده" else if (report.scannedAt == 0L) "هنوز اسکن نشده" else "وضعیت: خطا")
                Text("آخرین اسکن: ${if (report.scannedAt > 0) formatKabulTime(report.scannedAt) else "—"}")
                Text("ارزهای دارای حرکت و حجم مناسب: ${report.candidateCount}")
                if (!report.success) {
                    report.error?.takeIf { it.isNotBlank() }?.let { errorMessage ->
                        Text(errorMessage, color = MaterialTheme.colorScheme.error)
                    }
                }
                Button(
                    onClick = {
                        scope.launch {
                            scanning = true
                            val freshReport = withContext(Dispatchers.IO) { ScannerEngine.scan(context) }
                            AppPrefs.saveReport(context, freshReport)
                            report = freshReport
                            scanning = false
                        }
                    },
                    enabled = !scanning,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    if (scanning) {
                        CircularProgressIndicator(modifier = Modifier.height(18.dp), strokeWidth = 2.dp)
                        Text("  در حال بررسی بازار...")
                    } else {
                        Text("اسکن همین حالا")
                    }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("کنترل‌های برنامه", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.weight(1f)) {
                        Text("اسکن خودکار")
                        Text("در پس‌زمینه؛ حداقل فاصلهٔ معمول اندروید ۱۵ دقیقه است.", style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = autoScan, onCheckedChange = {
                        autoScan = it
                        ScanScheduler.setEnabled(context, it)
                    })
                }
                Text("فاصلهٔ اسکن خودکار")
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
                    listOf(15, 30, 60).forEach { minutes ->
                        Button(
                            onClick = {
                                intervalMinutes = minutes
                                AppPrefs.setScanIntervalMinutes(context, minutes)
                                if (autoScan) ScanScheduler.setEnabled(context, true)
                            },
                            enabled = intervalMinutes != minutes,
                            modifier = Modifier.weight(1f)
                        ) {
                            Text("$minutes دقیقه")
                        }
                    }
                }
                Text("زمان‌بندی اندروید ممکن است با تأخیر اجرا شود.", style = MaterialTheme.typography.bodySmall)
                Divider()
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.weight(1f)) {
                        Text("هشدار روی گوشی")
                        Text("فقط برای سیگنال خرید تازه و تأییدشده.", style = MaterialTheme.typography.bodySmall)
                    }
                    Switch(checked = notifications, onCheckedChange = { enabled ->
                        if (!enabled) {
                            notifications = false
                            AppPrefs.setNotifications(context, false)
                        } else if (Build.VERSION.SDK_INT >= 33 &&
                            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                        ) {
                            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                        } else {
                            notifications = true
                            AppPrefs.setNotifications(context, true)
                        }
                    })
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("فیلترهای بازار", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Text("حداقل حجم معاملات ۲۴ ساعته: ${String.format(Locale.US, "%.1f", minVolume)} میلیون USDT")
                Slider(
                    value = minVolume,
                    onValueChange = { minVolume = it },
                    onValueChangeFinished = { AppPrefs.setMinVolumeMillions(context, minVolume) },
                    valueRange = 0.5f..5.0f,
                    steps = 8
                )
                Text("حداقل رشد ۲۴ ساعته: ${String.format(Locale.US, "%.1f", minChange)}٪")
                Slider(
                    value = minChange,
                    onValueChange = { minChange = it },
                    onValueChangeFinished = { AppPrefs.setMinChangePct(context, minChange) },
                    valueRange = 3.0f..10.0f,
                    steps = 6
                )
                Text("تغییر فیلترها از اسکن بعدی اعمال می‌شود.", style = MaterialTheme.typography.bodySmall)
            }
        }

        Text("فرصت‌های خرید تأییدشده", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("حداکثر ۲ ارز؛ تأیید روند در کندل‌های بسته‌شدهٔ ۱۵ دقیقه و ۱ ساعت.")
        val activeSignals = report.signals.filter { it.expiresAt > System.currentTimeMillis() }
        if (!report.success) {
            Text("تا دریافت موفق داده‌ها، سیگنال قبلی نمایش داده نمی‌شود.", color = MaterialTheme.colorScheme.error)
        } else if (activeSignals.isEmpty()) {
            Card(Modifier.fillMaxWidth()) {
                Text("فعلاً سیگنال خرید تأییدشده‌ای پیدا نشد. دوباره اسکن کن یا بعداً بررسی کن.", modifier = Modifier.padding(16.dp))
            }
        } else {
            activeSignals.forEach { signal -> SignalCard(signal) }
        }

        Text(
            "یادآوری: قیمت ورود، حد ضرر و حد سود تخمینی‌اند؛ پیش از معامله قیمت زنده و کارمزد را بررسی کن. این برنامه سفارش ثبت نمی‌کند.",
            style = MaterialTheme.typography.bodySmall
        )
        Spacer(Modifier.height(12.dp))
    }
}

@Composable
private fun SignalCard(signal: SpotSignal) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                Text(signal.symbol, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text("+${String.format(Locale.US, "%.2f", signal.change24h)}٪", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
            }
            Text("قیمت فعلی هنگام اسکن: ${formatPrice(signal.price)}")
            Text("ورود پیشنهادی: ${formatPrice(signal.entry)}")
            Divider()
            Text("حد ضرر: ${formatPrice(signal.stopLoss)}")
            Text("حد سود ۱: ${formatPrice(signal.takeProfit1)}")
            Text("حد سود ۲: ${formatPrice(signal.takeProfit2)}")
            Text("اعتبار تا: ${formatKabulTime(signal.expiresAt)}", style = MaterialTheme.typography.bodySmall)
        }
    }
}

private fun formatKabulTime(time: Long): String {
    val formatter = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US)
    formatter.timeZone = TimeZone.getTimeZone("Asia/Kabul")
    return formatter.format(Date(time))
}
