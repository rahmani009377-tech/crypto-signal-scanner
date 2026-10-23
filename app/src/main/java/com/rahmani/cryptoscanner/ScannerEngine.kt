package com.rahmani.cryptoscanner

import android.content.Context
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.pow

object ScannerEngine {
    private const val TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
    private const val KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

    private data class Candidate(
        val symbol: String,
        val price: Double,
        val change: Double,
        val volume: Double
    )

    private data class Trend(val direction: String, val changePct: Double, val atr: Double, val recentResistance: Double)

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
                candidates.add(Candidate(symbol, price, change, volume))
            }

            val ordered = candidates.sortedWith(
                compareByDescending<Candidate> { it.change }
                    .thenByDescending { it.volume }
            )
            val ranked = mutableListOf<Pair<Double, SpotSignal>>()

            // Check up to 30 leading candidates; mobile data use will increase.
            for (candidate in ordered.take(30)) {
                // Avoid spending API calls on an already extreme 24h pump.
                if (candidate.change > 30.0) continue
                try {
                    val shortTrend = trend(candidate.symbol, "15m")
                    val longTrend = trend(candidate.symbol, "1h")
                    if (shortTrend.direction != "BULLISH" || longTrend.direction != "BULLISH") continue
                    if (shortTrend.changePct <= 0.0 || longTrend.changePct <= 0.0) continue
                    // Avoid chasing a near-vertical move that is more likely to mean-revert.
                    if (shortTrend.changePct > 8.0 || longTrend.changePct > 15.0) continue

                    val resistanceDistance = (shortTrend.recentResistance / candidate.price - 1.0) * 100.0
                    if (resistanceDistance in 0.0..0.5) continue

                    val risk = max(shortTrend.atr * 1.5, candidate.price * 0.005)
                    val signal = SpotSignal(
                            symbol = candidate.symbol,
                            price = candidate.price,
                            change24h = candidate.change,
                            volumeUsdt = candidate.volume,
                            direction = "BULLISH",
                            entry = candidate.price,
                            stopLoss = max(candidate.price - risk, candidate.price * 0.5),
                            takeProfit1 = candidate.price + risk * 1.5,
                            takeProfit2 = candidate.price + risk * 2.0,
                            trend15mPct = shortTrend.changePct,
                            trend1hPct = longTrend.changePct,
                            createdAt = now,
                            expiresAt = now + 15 * 60 * 1000L
                        )
                    val volumeScore = minOf((candidate.volume / 1_000_000.0).pow(0.25), 3.0) * 5.0
                    val momentumScore = minOf(candidate.change, 15.0) * 0.8
                    val shortTrendScore = minOf(shortTrend.changePct, 3.0) * 4.0
                    val hourlyTrendScore = minOf(longTrend.changePct, 8.0) * 1.5
                    val resistancePenalty = if (resistanceDistance > 0.0 && resistanceDistance < 1.0) {
                        (1.0 - resistanceDistance) * 8.0
                    } else 0.0
                    val qualityScore = volumeScore + momentumScore + shortTrendScore + hourlyTrendScore - resistancePenalty
                    ranked.add(qualityScore to signal)
                } catch (_: Exception) {
                    // A single unavailable pair must not cancel the rest of the scan.
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
        val candles = JSONArray(
            getText("$KLINES_URL?symbol=$encodedSymbol&interval=$interval&limit=16")
        )
        val closedCount = candles.length() - 1 // Ignore the candle that is still forming.
        if (closedCount < 6) throw IllegalStateException("Not enough candles")

        fun closeAt(index: Int): Double =
            candles.getJSONArray(index).getString(4).toDouble()

        val oldClose = closeAt(closedCount - 4)
        val previousClose = closeAt(closedCount - 2)
        val lastClose = closeAt(closedCount - 1)
        if (oldClose <= 0 || previousClose <= 0 || lastClose <= 0) {
            throw IllegalStateException("Invalid candle price")
        }

        val changePct = (lastClose / oldClose - 1.0) * 100.0
        val direction = if (lastClose > previousClose && changePct > 0) "BULLISH" else "OTHER"

        val ranges = mutableListOf<Double>()
        for (i in 1 until closedCount) {
            val candle = candles.getJSONArray(i)
            val high = candle.getString(2).toDouble()
            val low = candle.getString(3).toDouble()
            val previous = closeAt(i - 1)
            ranges.add(max(high - low, max(abs(high - previous), abs(low - previous))))
        }
        val recentRanges = ranges.takeLast(14)
        val atr = if (recentRanges.isEmpty()) 0.0 else recentRanges.average()
        val recentStart = max(0, closedCount - 12)
        var recentResistance = 0.0
        for (i in recentStart until closedCount) {
            val high = candles.getJSONArray(i).getString(2).toDouble()
            if (high > recentResistance) recentResistance = high
        }
        return Trend(direction, changePct, atr, recentResistance)
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
