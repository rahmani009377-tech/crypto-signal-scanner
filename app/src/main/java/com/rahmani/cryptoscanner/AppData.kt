package com.rahmani.cryptoscanner

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class SpotSignal(
    val symbol: String,
    val price: Double,
    val change24h: Double,
    val volumeUsdt: Double,
    val direction: String,
    val entry: Double,
    val stopLoss: Double,
    val takeProfit1: Double,
    val takeProfit2: Double,
    val trend15mPct: Double,
    val trend1hPct: Double,
    val createdAt: Long,
    val expiresAt: Long,
    val timeframeSummary: String = "",
    val fibAvailable: Boolean = false,
    val fibNearestName: String = "",
    val fibNearestPrice: Double = 0.0,
    val fibDistancePct: Double = 0.0,
    val fib618Price: Double = 0.0,
    val fib1272Price: Double = 0.0,
    val fib1618Price: Double = 0.0,
    val goldenRatioConfluence: Boolean = false
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("symbol", symbol)
        put("price", price)
        put("change24h", change24h)
        put("volumeUsdt", volumeUsdt)
        put("direction", direction)
        put("entry", entry)
        put("stopLoss", stopLoss)
        put("takeProfit1", takeProfit1)
        put("takeProfit2", takeProfit2)
        put("trend15mPct", trend15mPct)
        put("trend1hPct", trend1hPct)
        put("createdAt", createdAt)
        put("expiresAt", expiresAt)
        put("timeframeSummary", timeframeSummary)
        put("fibAvailable", fibAvailable)
        put("fibNearestName", fibNearestName)
        put("fibNearestPrice", fibNearestPrice)
        put("fibDistancePct", fibDistancePct)
        put("fib618Price", fib618Price)
        put("fib1272Price", fib1272Price)
        put("fib1618Price", fib1618Price)
        put("goldenRatioConfluence", goldenRatioConfluence)
    }

    companion object {
        fun fromJson(json: JSONObject) = SpotSignal(
            symbol = json.optString("symbol"),
            price = json.optDouble("price"),
            change24h = json.optDouble("change24h"),
            volumeUsdt = json.optDouble("volumeUsdt"),
            direction = json.optString("direction", "BULLISH"),
            entry = json.optDouble("entry"),
            stopLoss = json.optDouble("stopLoss"),
            takeProfit1 = json.optDouble("takeProfit1"),
            takeProfit2 = json.optDouble("takeProfit2"),
            trend15mPct = json.optDouble("trend15mPct", 0.0),
            trend1hPct = json.optDouble("trend1hPct", 0.0),
            createdAt = json.optLong("createdAt"),
            expiresAt = json.optLong("expiresAt"),
            timeframeSummary = json.optString("timeframeSummary", ""),
            fibAvailable = json.optBoolean("fibAvailable", false),
            fibNearestName = json.optString("fibNearestName", ""),
            fibNearestPrice = json.optDouble("fibNearestPrice", 0.0),
            fibDistancePct = json.optDouble("fibDistancePct", 0.0),
            fib618Price = json.optDouble("fib618Price", 0.0),
            fib1272Price = json.optDouble("fib1272Price", 0.0),
            fib1618Price = json.optDouble("fib1618Price", 0.0),
            goldenRatioConfluence = json.optBoolean("goldenRatioConfluence", false)
        )
    }
}

data class ScanReport(
    val success: Boolean,
    val scannedAt: Long,
    val candidateCount: Int,
    val signals: List<SpotSignal>,
    val error: String? = null,
    val diagnostics: String? = null
)

object AppPrefs {
    private const val FILE = "scanner_settings"
    private fun prefs(context: Context) = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun autoScan(context: Context) = prefs(context).getBoolean("auto_scan", false)
    fun setAutoScan(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean("auto_scan", enabled).apply()
    }
    fun notifications(context: Context) = prefs(context).getBoolean("notifications", false)
    fun setNotifications(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean("notifications", enabled).apply()
    }
    fun scanIntervalMinutes(context: Context) = prefs(context).getInt("scan_interval_minutes", 15).coerceIn(15, 60)
    fun setScanIntervalMinutes(context: Context, value: Int) {
        prefs(context).edit().putInt("scan_interval_minutes", value.coerceIn(15, 60)).apply()
    }
    fun minVolumeMillions(context: Context) = prefs(context).getFloat("min_volume", 1.0f)
    fun setMinVolumeMillions(context: Context, value: Float) {
        prefs(context).edit().putFloat("min_volume", value).apply()
    }
    fun minChangePct(context: Context) = prefs(context).getFloat("min_change", 5.0f)
    fun setMinChangePct(context: Context, value: Float) {
        prefs(context).edit().putFloat("min_change", value).apply()
    }

    fun saveReport(context: Context, report: ScanReport) {
        val array = JSONArray()
        report.signals.forEach { array.put(it.toJson()) }
        prefs(context).edit()
            .putLong("scanned_at", report.scannedAt)
            .putBoolean("scan_success", report.success)
            .putInt("candidate_count", report.candidateCount)
            .putString("signals", array.toString())
            .putString("scan_error", report.error.orEmpty())
            .putString("scan_diagnostics", report.diagnostics.orEmpty())
            .apply()
    }

    fun loadReport(context: Context): ScanReport {
        val p = prefs(context)
        val signals = mutableListOf<SpotSignal>()
        try {
            val array = JSONArray(p.getString("signals", "[]"))
            for (i in 0 until array.length()) signals.add(SpotSignal.fromJson(array.getJSONObject(i)))
        } catch (_: Exception) { }
        return ScanReport(
            success = p.getBoolean("scan_success", false),
            scannedAt = p.getLong("scanned_at", 0L),
            candidateCount = p.getInt("candidate_count", 0),
            signals = signals,
            error = p.getString("scan_error", "").takeIf { !it.isNullOrBlank() },
            diagnostics = p.getString("scan_diagnostics", "").takeIf { !it.isNullOrBlank() }
        )
    }

    fun newlyNotifiedSymbols(context: Context): Set<String> =
        prefs(context).getStringSet("notified_symbols", emptySet())?.toSet() ?: emptySet()

    fun setNotifiedSymbols(context: Context, symbols: Set<String>) {
        prefs(context).edit().putStringSet("notified_symbols", symbols).apply()
    }
}
