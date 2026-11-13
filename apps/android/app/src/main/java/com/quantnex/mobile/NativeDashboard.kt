package com.quantnex.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.text.NumberFormat
import java.util.Locale

private val DashboardBg = Color(0xFF080D13)
private val DashboardPanel = Color(0xFF111A25)
private val DashboardAccent = Color(0xFF50D6B0)
private val DashboardMuted = Color(0xFF8FA0B5)

private data class NativeMarketSnapshot(
    val btcUsd: Double? = null,
    val goldUsd: Double? = null,
    val usdLkr: Double? = null,
    val updatedAt: String = "",
    val errors: List<String> = emptyList()
) {
    val goldLkrGram: Double?
        get() = if (goldUsd != null && usdLkr != null) goldUsd / 31.1034768 * usdLkr else null
}

private fun readJson(url: String): JSONObject {
    val connection = URL(url).openConnection() as HttpURLConnection
    connection.connectTimeout = 9000
    connection.readTimeout = 12000
    connection.setRequestProperty("User-Agent", "QUANTNEX-Android")
    return try {
        connection.inputStream.bufferedReader().use { JSONObject(it.readText()) }
    } finally {
        connection.disconnect()
    }
}

private fun readPrice(url: String): Double {
    val json = readJson(url)
    val price = json.optDouble("price", Double.NaN)
    if (!price.isFinite() || price <= 0.0) error("Invalid market price")
    return price
}

private fun loadNativeMarketSnapshot(): NativeMarketSnapshot {
    val errors = mutableListOf<String>()
    val btc = try {
        readPrice("https://api.gold-api.com/price/BTC")
    } catch (_: Exception) {
        try { readPrice("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT") }
        catch (_: Exception) { errors += "BTC feed unavailable"; null }
    }
    val gold = try {
        readPrice("https://api.gold-api.com/price/XAU")
    } catch (_: Exception) {
        errors += "Gold feed unavailable"
        null
    }
    val fx = try {
        val rates = readJson("https://open.er-api.com/v6/latest/USD").optJSONObject("rates")
        val value = rates?.optDouble("LKR", Double.NaN) ?: Double.NaN
        if (value.isFinite() && value > 0.0) value else null
    } catch (_: Exception) {
        errors += "USD/LKR reference unavailable"
        null
    }
    return NativeMarketSnapshot(btc, gold, fx, java.text.SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(java.util.Date()), errors)
}

private fun money(value: Double?, currency: String = "$"): String {
    if (value == null) return "Unavailable"
    return currency + NumberFormat.getNumberInstance(Locale.US).apply {
        minimumFractionDigits = 2
        maximumFractionDigits = 2
    }.format(value)
}

@Composable
fun NativeDashboardScreen(
    refreshKey: Int,
    onRefresh: () -> Unit,
    onOpenSettings: () -> Unit
) {
    var snapshot by remember { mutableStateOf(NativeMarketSnapshot()) }
    var loading by remember { mutableStateOf(false) }
    var loadedOnce by remember { mutableStateOf(false) }

    LaunchedEffect(refreshKey) {
        loading = true
        snapshot = withContext(Dispatchers.IO) { loadNativeMarketSnapshot() }
        loadedOnce = true
        loading = false
    }

    Column(
        Modifier.fillMaxSize().background(DashboardBg).verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("MARKET OVERVIEW", color = DashboardMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.8.sp)
                Text("Your trading desk.", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.ExtraBold)
                Text("Live indicative market prices", color = DashboardMuted, fontSize = 12.sp)
            }
            IconButton(onClick = onRefresh, enabled = !loading) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh market prices", tint = DashboardAccent)
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            Box(Modifier.size(7.dp).background(if (loading) Color(0xFFFFC857) else DashboardAccent, RoundedCornerShape(50)))
            Text(if (loading) "UPDATING FEEDS…" else if (loadedOnce) "FEED CHECKED · ${snapshot.updatedAt}" else "CONNECTING TO MARKET FEEDS", color = DashboardMuted, fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            MarketPriceCard("BITCOIN", "BTC / USD", money(snapshot.btcUsd), "Gold-API · Binance fallback", Modifier.weight(1f))
            MarketPriceCard("GOLD", "XAU / USD", money(snapshot.goldUsd), "Gold-API spot estimate", Modifier.weight(1f))
        }

        Card(colors = CardDefaults.cardColors(containerColor = DashboardPanel), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("SRI LANKA GOLD REFERENCE", color = DashboardMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Indicative 1 gram", color = DashboardMuted, fontSize = 11.sp)
                        Text(money(snapshot.goldLkrGram, "LKR "), color = Color.White, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Text("Indicative 8 grams", color = DashboardMuted, fontSize = 11.sp)
                        Text(snapshot.goldLkrGram?.let { money(it * 8.0, "LKR ") } ?: "Unavailable", color = DashboardAccent, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                    }
                }
                HorizontalDivider(color = Color(0xFF263343))
                Text(snapshot.usdLkr?.let { "USD / LKR  ·  " + NumberFormat.getNumberInstance(Locale.US).format(it) } ?: "USD / LKR  ·  Unavailable", color = DashboardMuted, fontSize = 11.sp)
            }
        }

        Text("QUICK ACCESS", color = DashboardMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.6.sp)
        Card(colors = CardDefaults.cardColors(containerColor = DashboardPanel), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Your QUANTNEX toolkit", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                Text("Native Chart, Signal Lab, Trading Room, Journal and Prop Firm tools are being added in stages. Your local-only computer workspace and its saved data are not changed by this Android build.", color = DashboardMuted, fontSize = 12.sp, lineHeight = 18.sp)
                OutlinedButton(onClick = onOpenSettings, modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.outlinedButtonColors(contentColor = DashboardAccent)) {
                    Text("WORKSPACE CONNECTION SETTINGS")
                }
            }
        }

        if (snapshot.errors.isNotEmpty()) {
            Text(snapshot.errors.joinToString("  ·  "), color = Color(0xFFFFC857), fontSize = 10.sp)
        }
        Text("Prices are indicative provider quotes, not executable broker prices. LKR gold values exclude purity, taxes and dealer premiums.", color = DashboardMuted, fontSize = 10.sp, lineHeight = 15.sp)
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun MarketPriceCard(
    heading: String,
    symbol: String,
    price: String,
    source: String,
    modifier: Modifier = Modifier
) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = DashboardPanel), shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text(heading, color = DashboardMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.1.sp)
            Text(symbol, color = DashboardMuted, fontSize = 11.sp)
            Text(price, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold, maxLines = 1)
            Text(source, color = DashboardAccent, fontSize = 9.sp, maxLines = 2, lineHeight = 12.sp)
        }
    }
}

@Composable
fun NativeFeaturePlaceholder(title: String, description: String) {
    Column(
        Modifier.fillMaxSize().background(DashboardBg).padding(24.dp),
        verticalArrangement = Arrangement.Center
    ) {
        Text("QUANTNEX", color = DashboardAccent, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
        Spacer(Modifier.height(10.dp))
        Text(title, color = Color.White, fontSize = 26.sp, fontWeight = FontWeight.ExtraBold)
        Spacer(Modifier.height(10.dp))
        Text(description, color = DashboardMuted, fontSize = 14.sp, lineHeight = 21.sp)
        Spacer(Modifier.height(14.dp))
        Text("This native module will be added and tested in its development phase.", color = DashboardAccent, fontSize = 11.sp)
    }
}
