package com.rahmani.cryptoscanner

import android.content.Context
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.pow

object ScannerEngine {
    private const val TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
    private const val KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
    private val TIMEFRAMES = listOf("15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d")
    private const val MIN_BULLISH_TIMEFRAMES = 5
    private const val MAX_CANDIDATES_TO_ANALYZE = 15

    private data class Candidate(
        val symbol: String,
        val price: Double,
        val change: Double,
        val volume: Double
    )

    private data class Trend(
        val direction: String,
        val changePct: Double,
        val atr: Double,
        val recentResistance: Double,
        val recentSupport: Double
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
                if (price <= 0 || volume < minVolume || change < minChange) continue
                // Reject extreme pumps before spending mobile data on candle analysis.
                if (change > 18.0) continue
                candidates.add(Candidate(symbol, price, change, volume))
            }

            val ordered = candidates.sortedWith(
                compareByDescending<Candidate> { it.change }
                    .thenByDescending { it.volume }
            )
            val ranked = mutableListOf<Pair<Double, SpotSignal>>()

            // Analyze the most liquid/active candidates across all eight closed-candle timeframes.
            for (candidate in ordered.take(MAX_CANDIDATES_TO_ANALYZE)) {
                try {
                    val trends = linkedMapOf<String, Trend>()
                    for (interval in TIMEFRAMES) {
                        trends[interval] = trend(candidate.symbol, interval)
                    }

                    val directions = trends.mapValues { it.value.direction }
                    val bullishCount = directions.values.count { it == "BULLISH" }
                    if (listOf("15m", "30m", "1h").any { directions[it] != "BULLISH" }) continue
                    if (bullishCount < MIN_BULLISH_TIMEFRAMES) continue

                    val higher = listOf("4h", "8h", "12h", "1d")
                    val higherNotBearish = higher.count { directions[it] != "BEARISH" }
                    val strongHigherBearish = higher.any {
                        directions[it] == "BEARISH" && (trends[it]?.changePct ?: 0.0) <= -3.0
                    }
                    if (higherNotBearish < 2 || strongHigherBearish) continue

                    val shortTrend = trends.getValue("15m")
                    val hourlyTrend = trends.getValue("1h")
                    val resistanceDistance = if (candidate.price > 0) {
                        (shortTrend.recentResistance / candidate.price - 1.0) * 100.0
                    } else 0.0
                    if (resistanceDistance > 0.0 && resistanceDistance < 0.75) continue

                    val risk = max(shortTrend.atr * 1.5, candidate.price * 0.005)
                    val target1 = candidate.price + risk * 1.5
                    val target2 = candidate.price + risk * 2.0
                    val target1DistancePct = (target1 / candidate.price - 1.0) * 100.0
                    if (resistanceDistance > 0.0 && resistanceDistance <= target1DistancePct * 1.15) continue

                    val summary = linkedMapOf<String, String>()
                    for (interval in TIMEFRAMES) {
                        val item = trends.getValue(interval)
                        summary[interval] = "${item.direction} (${String.format(Locale.US, "%+.2f%%", item.changePct)})"
                    }
                    val signal = SpotSignal(
                        symbol = candidate.symbol,
                        price = candidate.price,
                        change24h = candidate.change,
                        volumeUsdt = candidate.volume,
                        direction = "BULLISH",
                        entry = candidate.price,
                        stopLoss = max(candidate.price - risk, candidate.price * 0.5),
                        takeProfit1 = target1,
                        takeProfit2 = target2,
                        trend15mPct = shortTrend.changePct,
                        trend1hPct = hourlyTrend.changePct,
                        timeframeSummary = summary,
                        createdAt = now,
                        expiresAt = now + 15 * 60 * 1000L
                    )

                    val volumeScore = minOf((candidate.volume / 1_000_000.0).pow(0.25), 3.0) * 5.0
                    val momentumScore = max(0.0, 12.0 - abs(candidate.change - 7.0)) * 0.65
                    val timeframeScore = bullishCount * 3.0
                    val shortScore = listOf("15m", "30m", "1h").sumOf {
                        (trends.getValue(it).changePct.coerceIn(-2.0, 2.0)) * 1.2
                    }
                    val resistancePenalty = if (resistanceDistance > 0.0 && resistanceDistance < 1.25) {
                        (1.25 - resistanceDistance) * 8.0
                    } else 0.0
                    ranked.add((volumeScore + momentumScore + timeframeScore + shortScore - resistancePenalty) to signal)
                } catch (_: Exception) {
                    // A single pair with missing candle data must not cancel the market scan.
                }
            }

            ScanReport(
                success = true,
                scannedAt = now,
                candidateCount = candidates.size,
                signals = ranked.sortedByDescending { it.first }.take(2).map { it.second }
            )
        } catch (error: Exception) {
            ScanReport(
                success = false,
                scannedAt = now,
                candidateCount = 0,
                signals = emptyList(),
                error = when (error) {
                    is java.net.SocketTimeoutException -> "اتصال کند است؛ دوباره تلاش کن."
                    else -> "دریافت اطلاعات بازار ناموفق بود. اینترنت یا دسترسی به Binance را بررسی کن."
                }
            )
        }
    }

    private fun trend(symbol: String, interval: String): Trend {
        val encodedSymbol = java.net.URLEncoder.encode(symbol, "UTF-8")
        val candles = JSONArray(getText("$KLINES_URL?symbol=$encodedSymbol&interval=$interval&limit=41"))
        val closedCount = candles.length() - 1 // Ignore the currently forming candle.
        if (closedCount < 22) throw IllegalStateException("Not enough $interval candles")

        fun openAt(index: Int): Double = candles.getJSONArray(index).getString(1).toDouble()
        fun highAt(index: Int): Double = candles.getJSONArray(index).getString(2).toDouble()
        fun lowAt(index: Int): Double = candles.getJSONArray(index).getString(3).toDouble()
        fun closeAt(index: Int): Double = candles.getJSONArray(index).getString(4).toDouble()

        val lastIndex = closedCount - 1
        val lastClose = closeAt(lastIndex)
        val previousClose = closeAt(lastIndex - 1)
        val oldClose = closeAt(lastIndex - 3)
        if (minOf(lastClose, previousClose, oldClose) <= 0.0) {
            throw IllegalStateException("Invalid candle price")
        }
        val changePct = (lastClose / oldClose - 1.0) * 100.0
        val direction = when {
            lastClose > previousClose && changePct > 0.0 -> "BULLISH"
            lastClose < previousClose && changePct < 0.0 -> "BEARISH"
            else -> "NEUTRAL"
        }

        val ranges = mutableListOf<Double>()
        for (i in 1..lastIndex) {
            val high = highAt(i)
            val low = lowAt(i)
            val previous = closeAt(i - 1)
            ranges.add(max(high - low, max(abs(high - previous), abs(low - previous))))
        }
        val recentRanges = ranges.takeLast(14)
        val atr = if (recentRanges.isEmpty()) 0.0 else recentRanges.average()

        // Resistance/support are based on the 20 closed candles before the latest closed candle.
        val rangeStart = max(0, lastIndex - 20)
        var resistance = 0.0
        var support = Double.MAX_VALUE
        for (i in rangeStart until lastIndex) {
            resistance = max(resistance, highAt(i))
            support = minOf(support, lowAt(i))
        }
        if (support == Double.MAX_VALUE) support = lastClose
        return Trend(direction, changePct, atr, resistance, support)
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
