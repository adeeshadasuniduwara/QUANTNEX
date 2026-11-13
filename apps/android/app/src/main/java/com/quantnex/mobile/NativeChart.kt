package com.quantnex.mobile

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.font.FontWeight
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.text.NumberFormat
import java.util.Locale

private val ChartBg = Color(0xFF080D13)
private val ChartPanel = Color(0xFF111A25)
private val ChartGrid = Color(0xFF263343)
private val ChartGreen = Color(0xFF50D6B0)
private val ChartRed = Color(0xFFFF6878)
private val ChartMuted = Color(0xFF8FA0B5)
private val EmaColor = Color(0xFFFFC857)

private data class Candle(val openTime: Long, val open: Double, val high: Double, val low: Double, val close: Double, val volume: Double)
private data class ChartResult(val candles: List<Candle>, val error: String = "")

private fun loadCandles(symbol: String, interval: String): ChartResult = try {
    val connection = URL("https://api.binance.com/api/v3/klines?symbol=$symbol&interval=$interval&limit=100").openConnection() as HttpURLConnection
    connection.connectTimeout = 10000
    connection.readTimeout = 15000
    connection.setRequestProperty("User-Agent", "QUANTNEX-Android")
    val response = try { connection.inputStream.bufferedReader().use { it.readText() } } finally { connection.disconnect() }
    val array = JSONArray(response)
    val items = (0 until array.length()).mapNotNull { index ->
        val row = array.optJSONArray(index) ?: return@mapNotNull null
        if (row.length() < 6) return@mapNotNull null
        Candle(row.getLong(0), row.getString(1).toDouble(), row.getString(2).toDouble(), row.getString(3).toDouble(), row.getString(4).toDouble(), row.getString(5).toDouble())
    }
    if (items.isEmpty()) ChartResult(emptyList(), "The exchange returned no candles.") else ChartResult(items)
} catch (_: Exception) {
    ChartResult(emptyList(), "Market data unavailable. Check your connection and try again.")
}

private fun ema(values: List<Double>, period: Int): List<Double> {
    if (values.isEmpty()) return emptyList()
    val alpha = 2.0 / (period + 1.0)
    var current = values.first()
    return values.mapIndexed { index, value ->
        current = if (index == 0) value else value * alpha + current * (1.0 - alpha)
        current
    }
}

private fun priceText(value: Double): String = NumberFormat.getNumberInstance(Locale.US).apply {
    minimumFractionDigits = if (value < 1.0) 4 else 2
    maximumFractionDigits = if (value < 1.0) 6 else 2
}.format(value)

@Composable
fun NativeChartScreen() {
    var symbol by remember { mutableStateOf("BTCUSDT") }
    var interval by remember { mutableStateOf("15m") }
    var showEma by remember { mutableStateOf(true) }
    var result by remember { mutableStateOf(ChartResult(emptyList())) }
    var loading by remember { mutableStateOf(false) }
    var refreshKey by remember { mutableIntStateOf(0) }

    LaunchedEffect(symbol, interval, refreshKey) {
        loading = true
        result = withContext(Dispatchers.IO) { loadCandles(symbol, interval) }
        loading = false
    }

    val latest = result.candles.lastOrNull()
    val previous = result.candles.getOrNull(result.candles.lastIndex - 1)
    val change = if (latest != null && previous != null && previous.close != 0.0) (latest.close - previous.close) / previous.close * 100.0 else null

    Column(Modifier.fillMaxSize().background(ChartBg).verticalScroll(rememberScrollState()).padding(horizontal = 14.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("QUANTNEX VIEW", color = ChartMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.8.sp)
                Text("Market charts", color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.ExtraBold)
            }
            TextButton(onClick = { refreshKey++ }, enabled = !loading) { Text("REFRESH", color = ChartGreen) }
        }
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            listOf("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT").forEach { pair ->
                FilterChip(selected = symbol == pair, onClick = { symbol = pair }, label = { Text(pair) })
            }
        }
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            listOf("1m", "5m", "15m", "1h", "4h", "1d").forEach { frame ->
                FilterChip(selected = interval == frame, onClick = { interval = frame }, label = { Text(frame) })
            }
        }
        Card(colors = CardDefaults.cardColors(containerColor = ChartPanel), shape = RoundedCornerShape(18.dp)) {
            Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(symbol, color = ChartMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        Text(latest?.let { priceText(it.close) } ?: if (loading) "Loading…" else "—", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.ExtraBold)
                    }
                    if (change != null) Text(String.format(Locale.US, "%+.2f%%", change), color = if (change >= 0) ChartGreen else ChartRed, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("O \${latest?.let { priceText(it.open) } ?: "—"}", color = ChartMuted, fontSize = 10.sp)
                    Text("H \${latest?.let { priceText(it.high) } ?: "—"}", color = ChartGreen, fontSize = 10.sp)
                    Text("L \${latest?.let { priceText(it.low) } ?: "—"}", color = ChartRed, fontSize = 10.sp)
                    Text("C \${latest?.let { priceText(it.close) } ?: "—"}", color = Color.White, fontSize = 10.sp)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("CANDLES · $interval", color = ChartMuted, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.weight(1f))
                    FilterChip(selected = showEma, onClick = { showEma = !showEma }, label = { Text("EMA 20") })
                }
                if (result.candles.isNotEmpty()) {
                    CandlestickChart(result.candles, showEma, Modifier.fillMaxWidth().height(270.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("100 candles", color = ChartMuted, fontSize = 9.sp)
                        Text("Volume · \${result.candles.lastOrNull()?.let { priceText(it.volume) } ?: "—"}", color = ChartMuted, fontSize = 9.sp)
                    }
                } else {
                    Box(Modifier.fillMaxWidth().height(220.dp), contentAlignment = Alignment.Center) {
                        if (loading) CircularProgressIndicator(color = ChartGreen) else Text(result.error.ifBlank { "No chart data" }, color = ChartMuted, fontSize = 12.sp)
                    }
                }
            }
        }
        Card(colors = CardDefaults.cardColors(containerColor = ChartPanel), shape = RoundedCornerShape(16.dp)) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("CHART DATA", color = ChartMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
                Text("Source: Binance public spot klines · $symbol · $interval", color = Color.White, fontSize = 11.sp)
                Text("Read-only market data. This chart does not place orders or connect to a broker. Gold/Forex feeds, drawing tools, multi-timeframe analysis and advanced indicators are scheduled for later phases.", color = ChartMuted, fontSize = 10.sp, lineHeight = 15.sp)
            }
        }
    }
}

@Composable
private fun CandlestickChart(candles: List<Candle>, showEma: Boolean, modifier: Modifier = Modifier) {
    val average = remember(candles) { ema(candles.map { it.close }, 20) }
    Canvas(modifier.background(ChartBg, RoundedCornerShape(12.dp))) {
        val left = 8.dp.toPx()
        val right = 8.dp.toPx()
        val top = 12.dp.toPx()
        val bottom = 12.dp.toPx()
        val volumeHeight = size.height * 0.18f
        val priceBottom = size.height - volumeHeight - bottom
        val priceTop = top
        val minPrice = candles.minOf { it.low }
        val maxPrice = candles.maxOf { it.high }
        val range = (maxPrice - minPrice).takeIf { it > 0.0 } ?: (maxPrice * 0.001).coerceAtLeast(0.000001)
        val maxVolume = candles.maxOf { it.volume }.coerceAtLeast(0.000001)
        val plotWidth = size.width - left - right
        val step = plotWidth / candles.size
        val bodyWidth = (step * 0.62f).coerceAtLeast(1.5f)
        fun y(price: Double): Float = priceBottom - ((price - minPrice) / range).toFloat() * (priceBottom - priceTop)
        for (i in 0..4) {
            val gy = priceTop + (priceBottom - priceTop) * i / 4f
            drawLine(ChartGrid, Offset(left, gy), Offset(size.width - right, gy), strokeWidth = 1.dp.toPx())
        }
        candles.forEachIndexed { index, candle ->
            val x = left + step * (index + 0.5f)
            val rising = candle.close >= candle.open
            val color = if (rising) ChartGreen else ChartRed
            drawLine(color, Offset(x, y(candle.high)), Offset(x, y(candle.low)), strokeWidth = 1.dp.toPx(), cap = StrokeCap.Round)
            val bodyTop = y(maxOf(candle.open, candle.close))
            val bodyBottom = y(minOf(candle.open, candle.close))
            drawRect(color, topLeft = Offset(x - bodyWidth / 2f, bodyTop), size = Size(bodyWidth, (bodyBottom - bodyTop).coerceAtLeast(1.5f)))
            val vTop = size.height - bottom - (candle.volume / maxVolume).toFloat() * volumeHeight * 0.85f
            drawRect(color.copy(alpha = 0.35f), topLeft = Offset(x - bodyWidth / 2f, vTop), size = Size(bodyWidth, size.height - bottom - vTop))
        }
        if (showEma && average.size == candles.size) {
            val path = Path()
            average.forEachIndexed { index, value ->
                val point = Offset(left + step * (index + 0.5f), y(value))
                if (index == 0) path.moveTo(point.x, point.y) else path.lineTo(point.x, point.y)
            }
            drawPath(path, EmaColor, style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round))
        }
    }
}
