package com.rahmani.cryptoscanner

import android.content.Context
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max

object ScannerEngine {
    private const val TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
    private const val KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

    private data class Candidate(
        val symbol: String,
        val price: Double,
        val change: Double,
        val volume: Double
    )

    private data class Trend(val direction: String, val changePct: Double, val atr: Double)

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
            val confirmed = mutableListOf<SpotSignal>()

            // Limit candle checks to the strongest eight candidates to reduce mobile data use.
            for (candidate in ordered.take(8)) {
                try {
                    val shortTrend = trend(candidate.symbol, "15m")
                    val longTrend = trend(candidate.symbol, "1h")
                    if (shortTrend.direction != "BULLISH" || longTrend.direction != "BULLISH") continue

                    val risk = max(shortTrend.atr * 1.5, candidate.price * 0.005)
                    confirmed.add(
                        SpotSignal(
                            symbol = candidate.symbol,
                            price = candidate.price,
                            change24h = candidate.change,
                            volumeUsdt = candidate.volume,
                            direction = "BULLISH",
                            entry = candidate.price,
                            stopLoss = max(candidate.price - risk, candidate.price * 0.5),
                            takeProfit1 = candidate.price + risk * 1.5,
                            takeProfit2 = candidate.price + risk * 2.0,
                            createdAt = now,
                            expiresAt = now + 15 * 60 * 1000L
                        )
                    )
                } catch (_: Exception) {
                    // A single unavailable pair must not cancel the rest of the scan.
                }
            }

            ScanReport(
                success = true,
                scannedAt = now,
                candidateCount = candidates.size,
                signals = confirmed.sortedByDescending { it.change24h }.take(2)
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
        return Trend(direction, changePct, atr)
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
