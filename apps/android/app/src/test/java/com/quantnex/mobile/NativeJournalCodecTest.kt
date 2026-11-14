package com.quantnex.mobile

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeJournalCodecTest {
    @Test
    fun roundTripPreservesOpenAndClosedTrades() {
        val trades = listOf(
            JournalTrade("one", "XAUUSD", "BUY", 2700.5, null, 0.02, 0.0, "still open", 1000L),
            JournalTrade("two", "BTCUSDT", "SELL", 98000.0, 97000.0, 0.01, 10.0, "partial exit", 2000L)
        )
        val decoded = JournalTradeCodec.decode(JournalTradeCodec.encode(trades))
        assertEquals(trades, decoded)
        assertNull(decoded.first().exitPrice)
        assertTrue(decoded.last().isClosed)
    }

    @Test
    fun decoderSkipsInvalidRecordsWithoutRejectingValidOnes() {
        val raw = """[
          {"id":"bad","symbol":"XAUUSD","side":"BUY","entryPrice":-1,"quantity":0.1,"pnl":0},
          {"id":"good","symbol":"EURUSD","side":"SELL","entryPrice":1.08,"exitPrice":1.07,"quantity":0.1,"pnl":12.5,"note":"ok","createdAt":42}
        ]"""
        val decoded = JournalTradeCodec.decode(raw)
        assertEquals(1, decoded.size)
        assertEquals("good", decoded.single().id)
        assertEquals(12.5, decoded.single().pnl, 0.000001)
    }

    @Test
    fun codecHandlesEmptyJournal() {
        assertTrue(JournalTradeCodec.decode(JournalTradeCodec.encode(emptyList())).isEmpty())
    }
}
