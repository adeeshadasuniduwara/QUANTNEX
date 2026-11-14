package com.quantnex.mobile

import android.content.SharedPreferences
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONArray
import org.json.JSONObject
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

private const val JOURNAL_KEY = "native_trade_journal_v1"
private val JournalBg = Color(0xFF080D13)
private val JournalPanel = Color(0xFF111A25)
private val JournalAccent = Color(0xFF50D6B0)
private val JournalMuted = Color(0xFF8FA0B5)
private val JournalRed = Color(0xFFFF6878)

internal data class JournalTrade(
    val id: String,
    val symbol: String,
    val side: String,
    val entryPrice: Double,
    val exitPrice: Double?,
    val quantity: Double,
    val pnl: Double,
    val note: String,
    val createdAt: Long
) {
    val isClosed: Boolean get() = exitPrice != null
}

internal object JournalTradeCodec {
    fun encode(trades: List<JournalTrade>): String {
        val array = JSONArray()
        trades.forEach { trade ->
            array.put(JSONObject().apply {
                put("id", trade.id)
                put("symbol", trade.symbol)
                put("side", trade.side)
                put("entryPrice", trade.entryPrice)
                put("exitPrice", trade.exitPrice ?: JSONObject.NULL)
                put("quantity", trade.quantity)
                put("pnl", trade.pnl)
                put("note", trade.note)
                put("createdAt", trade.createdAt)
            })
        }
        return array.toString()
    }

    fun decode(raw: String): List<JournalTrade> {
        val array = JSONArray(raw)
        return (0 until array.length()).mapNotNull { index ->
            val item = array.optJSONObject(index) ?: return@mapNotNull null
            val id = item.optString("id").takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val symbol = item.optString("symbol").trim().takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val side = item.optString("side").uppercase(Locale.US)
            if (side != "BUY" && side != "SELL") return@mapNotNull null
            val entry = item.optDouble("entryPrice", Double.NaN)
            val quantity = item.optDouble("quantity", Double.NaN)
            val pnl = item.optDouble("pnl", 0.0)
            if (!entry.isFinite() || entry <= 0.0 || !quantity.isFinite() || quantity <= 0.0 || !pnl.isFinite()) return@mapNotNull null
            val exitValue = item.opt("exitPrice")
            val exit = if (exitValue == null || exitValue == JSONObject.NULL) null else (exitValue as? Number)?.toDouble()
            if (exit != null && (!exit.isFinite() || exit <= 0.0)) return@mapNotNull null
            JournalTrade(id, symbol, side, entry, exit, quantity, pnl, item.optString("note"), item.optLong("createdAt", 0L))
        }
    }
}

private object JournalTradeStore {
    fun load(preferences: SharedPreferences): List<JournalTrade> {
        val raw = preferences.getString(JOURNAL_KEY, null) ?: return emptyList()
        return runCatching { JournalTradeCodec.decode(raw) }.getOrElse { emptyList() }
    }
    fun save(preferences: SharedPreferences, trades: List<JournalTrade>) {
        preferences.edit().putString(JOURNAL_KEY, JournalTradeCodec.encode(trades)).apply()
    }
}

private fun journalNumber(value: Double): String =
    NumberFormat.getNumberInstance(Locale.US).apply { maximumFractionDigits = 2 }.format(value)

@Composable
fun NativeJournalScreen(preferences: SharedPreferences) {
    var trades by remember { mutableStateOf(JournalTradeStore.load(preferences)) }
    var search by remember { mutableStateOf("") }
    var filter by remember { mutableStateOf("ALL") }
    var showEditor by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<JournalTrade?>(null) }
    var deleteTarget by remember { mutableStateOf<JournalTrade?>(null) }

    val visibleTrades = trades
        .filter { search.isBlank() || it.symbol.contains(search.trim(), ignoreCase = true) }
        .filter { when (filter) { "OPEN" -> !it.isClosed; "CLOSED" -> it.isClosed; else -> true } }
        .sortedByDescending { it.createdAt }
    val closedPnl = trades.filter { it.isClosed }.sumOf { it.pnl }

    fun persist(next: List<JournalTrade>) {
        trades = next
        JournalTradeStore.save(preferences, next)
    }

    Column(Modifier.fillMaxSize().background(JournalBg).verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("LOCAL TRADE JOURNAL", color = JournalMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
                Text("Trade history", color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.ExtraBold)
            }
            Button(onClick = { editing = null; showEditor = true }, colors = ButtonDefaults.buttonColors(containerColor = JournalAccent, contentColor = JournalBg), shape = RoundedCornerShape(12.dp)) {
                Text("+ ADD TRADE", fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }
        }
        Card(colors = CardDefaults.cardColors(containerColor = JournalPanel), shape = RoundedCornerShape(16.dp)) {
            Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column {
                    Text("CLOSED TRADE P&L", color = JournalMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                    Text(journalNumber(closedPnl), color = if (closedPnl >= 0) JournalAccent else JournalRed, fontSize = 25.sp, fontWeight = FontWeight.ExtraBold)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("TOTAL RECORDS", color = JournalMuted, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                    Text(trades.size.toString(), color = Color.White, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                    Text("Saved on this device", color = JournalMuted, fontSize = 9.sp)
                }
            }
        }
        OutlinedTextField(
            value = search, onValueChange = { search = it }, modifier = Modifier.fillMaxWidth(),
            singleLine = true, label = { Text("Search symbol") },
            colors = OutlinedTextFieldDefaults.colors(focusedTextColor = Color.White, unfocusedTextColor = Color.White,
                focusedBorderColor = JournalAccent, unfocusedBorderColor = Color(0xFF344253),
                focusedLabelColor = JournalAccent, unfocusedLabelColor = JournalMuted)
        )
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            listOf("ALL", "OPEN", "CLOSED").forEach { value ->
                FilterChip(selected = filter == value, onClick = { filter = value }, label = { Text(value) },
                    colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Color(0xFF20382F), selectedLabelColor = JournalAccent))
            }
        }
        if (visibleTrades.isEmpty()) {
            Card(colors = CardDefaults.cardColors(containerColor = JournalPanel), shape = RoundedCornerShape(16.dp)) {
                Column(Modifier.fillMaxWidth().padding(22.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(if (trades.isEmpty()) "Your journal is ready" else "No matching trades", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    Text(if (trades.isEmpty()) "Add your first trade. Records stay on this phone and remain available offline." else "Try another symbol or change the filter.", color = JournalMuted, fontSize = 12.sp)
                    if (trades.isEmpty()) TextButton(onClick = { editing = null; showEditor = true }) { Text("ADD FIRST TRADE", color = JournalAccent) }
                }
            }
        } else {
            visibleTrades.forEach { trade ->
                Card(colors = CardDefaults.cardColors(containerColor = JournalPanel), shape = RoundedCornerShape(15.dp)) {
                    Column(Modifier.fillMaxWidth().padding(13.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(trade.symbol, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                                Text(trade.side + " · " + (if (trade.isClosed) "CLOSED" else "OPEN") + " · " + SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(Date(trade.createdAt)), color = JournalMuted, fontSize = 9.sp)
                            }
                            Text(if (trade.isClosed) journalNumber(trade.pnl) else "OPEN", color = if (trade.pnl >= 0) JournalAccent else JournalRed, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Text("Entry " + journalNumber(trade.entryPrice), color = JournalMuted, fontSize = 10.sp)
                            Text("Exit " + (trade.exitPrice?.let { journalNumber(it) } ?: "—"), color = JournalMuted, fontSize = 10.sp)
                            Text("Qty " + journalNumber(trade.quantity), color = JournalMuted, fontSize = 10.sp)
                        }
                        if (trade.note.isNotBlank()) Text(trade.note, color = Color(0xFFCBD5E1), fontSize = 11.sp, lineHeight = 16.sp)
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            TextButton(onClick = { editing = trade; showEditor = true }) { Text("EDIT", color = JournalAccent, fontSize = 10.sp) }
                            TextButton(onClick = { deleteTarget = trade }) { Text("DELETE", color = JournalRed, fontSize = 10.sp) }
                        }
                    }
                }
            }
        }
        Text("Offline-first journal · No broker connection · P&L is entered by you and is not calculated from broker fills.", color = JournalMuted, fontSize = 9.sp, lineHeight = 14.sp)
        Spacer(Modifier.height(8.dp))
    }

    if (showEditor) {
        JournalTradeEditor(initial = editing, onDismiss = { showEditor = false; editing = null }, onSave = { saved ->
            val next = if (editing == null) trades + saved else trades.map { if (it.id == saved.id) saved else it }
            persist(next)
            showEditor = false
            editing = null
        })
    }
    deleteTarget?.let { target ->
        AlertDialog(onDismissRequest = { deleteTarget = null }, containerColor = JournalPanel,
            title = { Text("Delete trade?", color = Color.White) },
            text = { Text("This removes " + target.symbol + " from this device's journal.", color = JournalMuted) },
            confirmButton = { TextButton(onClick = { persist(trades.filterNot { it.id == target.id }); deleteTarget = null }) { Text("DELETE", color = JournalRed) } },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text("CANCEL", color = JournalMuted) } })
    }
}

@Composable
private fun JournalTradeEditor(initial: JournalTrade?, onDismiss: () -> Unit, onSave: (JournalTrade) -> Unit) {
    var symbol by remember(initial?.id) { mutableStateOf(initial?.symbol ?: "") }
    var side by remember(initial?.id) { mutableStateOf(initial?.side ?: "BUY") }
    var entry by remember(initial?.id) { mutableStateOf(initial?.entryPrice?.toString() ?: "") }
    var exit by remember(initial?.id) { mutableStateOf(initial?.exitPrice?.toString() ?: "") }
    var quantity by remember(initial?.id) { mutableStateOf(initial?.quantity?.toString() ?: "0.01") }
    var pnl by remember(initial?.id) { mutableStateOf(initial?.pnl?.toString() ?: "0") }
    var note by remember(initial?.id) { mutableStateOf(initial?.note ?: "") }
    var error by remember(initial?.id) { mutableStateOf("") }

    AlertDialog(onDismissRequest = onDismiss, containerColor = JournalPanel,
        title = { Text(if (initial == null) "Add trade" else "Edit trade", color = Color.White, fontWeight = FontWeight.Bold) },
        text = {
            Column(Modifier.fillMaxWidth().heightIn(max = 480.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(symbol, { symbol = it.uppercase(Locale.US) }, label = { Text("Symbol (e.g. XAUUSD)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = side == "BUY", onClick = { side = "BUY" }, label = { Text("BUY") })
                    FilterChip(selected = side == "SELL", onClick = { side = "SELL" }, label = { Text("SELL") })
                }
                OutlinedTextField(entry, { entry = it }, label = { Text("Entry price *") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(exit, { exit = it }, label = { Text("Exit price (blank = open)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(quantity, { quantity = it }, label = { Text("Quantity / lots *") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(pnl, { pnl = it }, label = { Text("P&L (account currency)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(note, { note = it }, label = { Text("Notes (optional)") }, modifier = Modifier.fillMaxWidth(), minLines = 2)
                if (error.isNotBlank()) Text(error, color = JournalRed, fontSize = 11.sp)
                Text("P&L is manually recorded. An empty exit price marks the trade as open.", color = JournalMuted, fontSize = 10.sp)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val entryValue = entry.toDoubleOrNull()
                val exitValue = exit.trim().takeIf { it.isNotEmpty() }?.toDoubleOrNull()
                val quantityValue = quantity.toDoubleOrNull()
                val pnlValue = pnl.toDoubleOrNull()
                error = when {
                    symbol.trim().isEmpty() -> "Enter a symbol."
                    entryValue == null || !entryValue.isFinite() || entryValue <= 0.0 -> "Entry price must be greater than zero."
                    exit.isNotBlank() && (exitValue == null || !exitValue.isFinite() || exitValue <= 0.0) -> "Exit price must be greater than zero or left blank."
                    quantityValue == null || !quantityValue.isFinite() || quantityValue <= 0.0 -> "Quantity must be greater than zero."
                    pnlValue == null || !pnlValue.isFinite() -> "Enter a valid P&L number."
                    else -> ""
                }
                if (error.isBlank()) onSave(JournalTrade(
                    id = initial?.id ?: UUID.randomUUID().toString(),
                    symbol = symbol.trim().uppercase(Locale.US),
                    side = side,
                    entryPrice = entryValue!!,
                    exitPrice = exitValue,
                    quantity = quantityValue!!,
                    pnl = pnlValue!!,
                    note = note.trim(),
                    createdAt = initial?.createdAt ?: System.currentTimeMillis()
                ))
            }) { Text("SAVE", color = JournalAccent, fontWeight = FontWeight.Bold) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("CANCEL", color = JournalMuted) } })
}
