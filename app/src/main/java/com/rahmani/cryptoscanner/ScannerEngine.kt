package com.rahmani.cryptoscanner

import android.content.Context
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import kotlin.math.max

object ScannerEngine {
    private const val TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
    private const val KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
    private val timeframes = listOf("15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d")
    private const val MAX_DEEP_SCAN = 10
    private const val MAX_RESULTS = 3
    private const val MIN_BULLISH_TIMEFRAMES = 5

    private data class Candidate(val symbol: String, val price: Double, val change: Double, val volume: Double)
    private data class Trend(
        val direction: String,
        val changePct: Double,
        val atr: Double,
        val recentResistance: Double,
        val breakoutConfirmed: Boolean,
        val lastClosedPrice: Double,
        val fibAvailable: Boolean,
        val fibNearestName: String,
        val fibNearestPrice: Double,
        val fibDistancePct: Double,
        val fib618Price: Double,
        val fib1272Price: Double,
        val fib1618Price: Double,
        val goldenRatioConfluence: Boolean,
        val fibNearLevel: Boolean
    )

    fun scan(context: Context): ScanReport {
        val now = System.currentTimeMillis()
        return try {
            val minVolume = AppPrefs.minVolumeMillions(context) * 1_000_000.0
            val minChange = AppPrefs.minChangePct(context).toDouble()
            val tickers = JSONArray(getText(TICKER_URL))
            val candidates = mutableListOf<Candidate>()
            for (i in 0 until tickers.length()) {
                val item = tickers.optJSONObject(i) ?: continue
                val symbol = item.optString("symbol")
                if (!symbol.matches(Regex("[A-Z0-9]+USDT"))) continue
                val price = item.optString("lastPrice").toDoubleOrNull() ?: continue
                val change = item.optString("priceChangePercent").toDoubleOrNull() ?: continue
                val volume = item.optString("quoteVolume").toDoubleOrNull() ?: continue
                if (price <= 0.0 || volume < minVolume || change < minChange || change > 18.0) continue
                candidates.add(Candidate(symbol, price, change, volume))
            }

            val ordered = candidates.sortedWith(compareByDescending<Candidate> { it.volume }.thenByDescending { it.change })
            val ranked = mutableListOf<Pair<Double, SpotSignal>>()
            val rejectionCounts = linkedMapOf<String, Int>()
            var checked = 0
            fun reject(reason: String) { rejectionCounts[reason] = (rejectionCounts[reason] ?: 0) + 1 }

            for (candidate in ordered.take(MAX_DEEP_SCAN)) {
                checked++
                try {
                    val trends = multiTimeframeTrends(candidate.symbol)
                    if (listOf("15m", "30m", "1h").any { trends[it]?.direction != "BULLISH" }) {
                        reject("تأیید هم‌زمان ۱۵ دقیقه، ۳۰ دقیقه و ۱ ساعت انجام نشد")
                        continue
                    }
                    val bullishCount = trends.values.count { it.direction == "BULLISH" }
                    val higherBearish = listOf("4h", "8h", "12h", "1d").count { trends[it]?.direction == "BEARISH" }
                    if (bullishCount < MIN_BULLISH_TIMEFRAMES || higherBearish > 1) {
                        reject("هم‌جهتی حداقل پنج تایم‌فریم تأیید نشد")
                        continue
                    }

                    val short = trends.getValue("15m")
                    val hourly = trends.getValue("1h")
                    if (candidate.change > 18.0 || short.changePct > 3.5 || hourly.changePct > 7.0) {
                        reject("حرکت بیش‌ازحد کشیده")
                        continue
                    }

                    val resistanceDistance = if (short.recentResistance > 0.0) {
                        (short.recentResistance / candidate.price - 1.0) * 100.0
                    } else 0.0
                    if (resistanceDistance > 0.0 && resistanceDistance < 0.75) {
                        reject("مقاومت خیلی نزدیک")
                        continue
                    }

                    val risk = max(short.atr * 1.5, candidate.price * 0.005)
                    val tp1DistancePct = (risk * 1.5 / candidate.price) * 100.0
                    if (resistanceDistance > 0.0 && resistanceDistance <= tp1DistancePct * 1.15) {
                        reject("فضای ناکافی تا مقاومت برای هدف اول")
                        continue
                    }
                    if (short.recentResistance > 0.0 && resistanceDistance <= 0.0 && !short.breakoutConfirmed) {
                        reject("شکست مقاومت تأیید نشده")
                        continue
                    }
                    if (short.lastClosedPrice > 0.0 && candidate.price > short.lastClosedPrice * 1.01) {
                        reject("قیمت زنده بیش از یک درصد بالاتر از کندل بسته‌شده است")
                        continue
                    }

                    val stop = max(candidate.price - risk, candidate.price * 0.5)
                    val tp1 = candidate.price + risk * 1.5
                    val tp2 = candidate.price + risk * 2.0
                    val weights = mapOf("15m" to 1.5, "30m" to 1.5, "1h" to 1.5, "2h" to 1.25,
                        "4h" to 1.0, "8h" to 0.75, "12h" to 0.5, "1d" to 0.5)
                    val trendScore = trends.entries.sumOf { (interval, trend) ->
                        weights.getValue(interval) * trend.changePct.coerceIn(-2.0, 2.0)
                    }
                    val volumeScore = minOf(Math.sqrt(Math.sqrt(candidate.volume / 1_000_000.0)), 3.0) * 5.0
                    val momentumScore = candidate.change.coerceIn(0.0, 15.0) * 0.5
                    val resistancePenalty = if (resistanceDistance > 0.0 && resistanceDistance < 1.0) {
                        (1.0 - resistanceDistance) * 8.0
                    } else 0.0
                    val fibonacciBonus = (if (short.fibNearLevel) 4.0 else 0.0) +
                        (if (short.goldenRatioConfluence) 3.0 else 0.0)
                    val score = volumeScore + momentumScore + trendScore + bullishCount * 1.5 -
                        resistancePenalty + fibonacciBonus
                    val summary = timeframes.joinToString(" | ") { interval -> "${interval}:${trends.getValue(interval).direction}" }

                    ranked.add(score to SpotSignal(
                        symbol = candidate.symbol, price = candidate.price, change24h = candidate.change,
                        volumeUsdt = candidate.volume, direction = "BULLISH", entry = candidate.price,
                        stopLoss = stop, takeProfit1 = tp1, takeProfit2 = tp2,
                        trend15mPct = short.changePct, trend1hPct = hourly.changePct,
                        createdAt = now, expiresAt = now + 15 * 60 * 1000L,
                        timeframeSummary = summary,
                        fibAvailable = short.fibAvailable,
                        fibNearestName = short.fibNearestName,
                        fibNearestPrice = short.fibNearestPrice,
                        fibDistancePct = short.fibDistancePct,
                        fib618Price = short.fib618Price,
                        fib1272Price = short.fib1272Price,
                        fib1618Price = short.fib1618Price,
                        goldenRatioConfluence = short.goldenRatioConfluence
                    ))
                } catch (_: Exception) {
                    reject("دادهٔ یکی از تایم‌فریم‌ها در دسترس نبود")
                }
            }

            val diagnostics = buildString {
                append("نامزدهای واجد فیلتر اولیه: ${candidates.size}؛ ")
                append("بررسی عمیق‌شده در هشت تایم‌فریم: $checked از حداکثر $MAX_DEEP_SCAN؛ ")
                append("فرصت‌های تأییدشده پیش از رتبه‌بندی: ${ranked.size}؛ ")
                append("خروجی نهایی: ${minOf(ranked.size, MAX_RESULTS)}.")
                if (rejectionCounts.isNotEmpty()) {
                    append("\nدلایل رد: ")
                    append(rejectionCounts.entries.sortedWith(
                        compareByDescending<Map.Entry<String, Int>> { it.value }.thenBy { it.key }
                    ).joinToString("؛ ") { "${it.key}: ${it.value}" })
                }
            }
            ScanReport(
                success = true, scannedAt = now, candidateCount = candidates.size,
                signals = ranked.sortedByDescending { it.first }.take(MAX_RESULTS).map { it.second },
                diagnostics = diagnostics
            )
        } catch (error: Exception) {
            ScanReport(
                success = false, scannedAt = now, candidateCount = 0, signals = emptyList(),
                error = if (error is java.net.SocketTimeoutException) "اتصال کند است؛ دوباره تلاش کن."
                else "دریافت اطلاعات بازار ناموفق بود. اینترنت یا دسترسی به Binance را بررسی کن."
            )
        }
    }

    private fun multiTimeframeTrends(symbol: String): Map<String, Trend> {
        val executor = Executors.newFixedThreadPool(timeframes.size)
        try {
            val futures = timeframes.associateWith { interval -> executor.submit<Trend> { trend(symbol, interval) } }
            return futures.mapValues { (_, future) -> future.get(10, TimeUnit.SECONDS) }
        } finally {
            executor.shutdownNow()
        }
    }

    private fun trend(symbol: String, interval: String): Trend {
        val encoded = URLEncoder.encode(symbol, "UTF-8")
        val candles = JSONArray(getText("$KLINES_URL?symbol=$encoded&interval=$interval&limit=32"))
        val closedCount = candles.length() - 1
        if (closedCount < 15) throw IllegalStateException("Not enough closed candles: $interval")
        fun candle(index: Int) = candles.getJSONArray(index)
        fun closeAt(index: Int) = candle(index).getString(4).toDouble()

        val oldClose = closeAt(closedCount - 4)
        val previousClose = closeAt(closedCount - 2)
        val lastClose = closeAt(closedCount - 1)
        if (oldClose <= 0.0 || previousClose <= 0.0 || lastClose <= 0.0) throw IllegalStateException("Invalid candle close")
        val changePct = (lastClose / oldClose - 1.0) * 100.0
        val direction = when {
            lastClose > previousClose && changePct > 0.0 -> "BULLISH"
            lastClose < previousClose && changePct < 0.0 -> "BEARISH"
            else -> "NEUTRAL"
        }

        val ranges = mutableListOf<Double>()
        for (i in 1 until closedCount) {
            val current = candle(i)
            val high = current.getString(2).toDouble()
            val low = current.getString(3).toDouble()
            val previous = closeAt(i - 1)
            if (high <= 0.0 || low <= 0.0 || high < low) throw IllegalStateException("Invalid candle range")
            ranges.add(max(high - low, max(abs(high - previous), abs(low - previous))))
        }
        val atrValues = ranges.takeLast(14)
        val atr = if (atrValues.isEmpty()) 0.0 else atrValues.average()

        // Fibonacci analysis uses only closed candles from the latest 24-candle swing.
        val fibStart = max(0, closedCount - 24)
        var swingLow = Double.POSITIVE_INFINITY
        var swingHigh = 0.0
        var swingLowIndex = -1
        var swingHighIndex = -1
        for (i in fibStart until closedCount) {
            val low = candle(i).getString(3).toDouble()
            val high = candle(i).getString(2).toDouble()
            if (low < swingLow) { swingLow = low; swingLowIndex = i }
            if (high > swingHigh) { swingHigh = high; swingHighIndex = i }
        }
        val fibRange = swingHigh - swingLow
        val fibAvailable = swingLowIndex >= 0 && swingHighIndex > swingLowIndex && fibRange > 0.0
        val fibLevels = if (fibAvailable) mapOf(
            "23.6%" to swingHigh - fibRange * 0.236,
            "38.2%" to swingHigh - fibRange * 0.382,
            "50.0%" to swingHigh - fibRange * 0.500,
            "61.8%" to swingHigh - fibRange * 0.618,
            "78.6%" to swingHigh - fibRange * 0.786
        ) else emptyMap()
        val nearestFib = fibLevels.minByOrNull { abs(lastClose - it.value) }
        val fibTolerance = max(atr * 0.25, lastClose * 0.0025)
        val fibNearLevel = nearestFib != null && abs(lastClose - nearestFib.value) <= fibTolerance
        val fib618Price = fibLevels["61.8%"] ?: 0.0
        val goldenRatioConfluence = fibAvailable && abs(lastClose - fib618Price) <= fibTolerance
        val fibDistancePct = if (nearestFib != null && lastClose > 0.0)
            abs(lastClose - nearestFib.value) / lastClose * 100.0 else 0.0
        val fib1272Price = if (fibAvailable) swingLow + fibRange * 1.272 else 0.0
        val fib1618Price = if (fibAvailable) swingLow + fibRange * 1.618 else 0.0

        val resistanceStart = max(0, closedCount - 13)
        var resistance = 0.0
        for (i in resistanceStart until (closedCount - 1)) {
            resistance = max(resistance, candle(i).getString(2).toDouble())
        }
        val latest = candle(closedCount - 1)
        val latestVolume = latest.optString(7).toDoubleOrNull() ?: 0.0
        val previousVolumes = (max(0, closedCount - 11) until (closedCount - 1))
            .mapNotNull { candle(it).optString(7).toDoubleOrNull()?.takeIf { value -> value > 0.0 } }
        val averageVolume = if (previousVolumes.isEmpty()) 0.0 else previousVolumes.average()
        val breakout = resistance > 0.0 && lastClose > resistance * 1.001 &&
            averageVolume > 0.0 && latestVolume >= averageVolume * 1.2
        return Trend(
            direction, changePct, atr, resistance, breakout, lastClose,
            fibAvailable, nearestFib?.key.orEmpty(), nearestFib?.value ?: 0.0,
            fibDistancePct, fib618Price, fib1272Price, fib1618Price,
            goldenRatioConfluence, fibNearLevel
        )
    }

    private fun getText(address: String): String {
        val connection = (URL(address).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 6000
            readTimeout = 6000
            useCaches = false
            setRequestProperty("Accept", "application/json")
            setRequestProperty("User-Agent", "RahmaniCryptoScanner/1.0 Android")
        }
        try {
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IllegalStateException("Market API HTTP $code")
            if (body.isBlank()) throw IllegalStateException("Empty market response")
            return body
        } finally {
            connection.disconnect()
        }
    }
}
