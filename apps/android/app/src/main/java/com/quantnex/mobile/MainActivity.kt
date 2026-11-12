package com.quantnex.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Background = Color(0xFF090E1B)
private val Panel = Color(0xFF111A2B)
private val Muted = Color(0xFF91A0B8)
private val Accent = Color(0xFF73A7FF)
private val Green = Color(0xFF55D6A0)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { QuantnexApp() }
    }
}

@Composable
private fun QuantnexApp() {
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = Background) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Background)
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Column {
                        Text("QUANTNEX", color = Accent, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                        Text("Overview", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                    }
                    Text("v0.1.0", color = Muted, fontSize = 12.sp)
                }

                Card(
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF172B49)),
                    shape = RoundedCornerShape(18.dp)
                ) {
                    Column(Modifier.padding(18.dp)) {
                        Text("PHASE 01 · FOUNDATION", color = Accent, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        Spacer(Modifier.height(8.dp))
                        Text("Clarity for every trading decision.", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(6.dp))
                        Text("Your lightweight trading workspace starts here.", color = Muted, fontSize = 13.sp)
                    }
                }

                Card(colors = CardDefaults.cardColors(containerColor = Color(0xFF282416))) {
                    Column(Modifier.padding(14.dp)) {
                        Text("DEMO ENVIRONMENT", color = Color(0xFFE5C77F), fontWeight = FontWeight.Bold, fontSize = 11.sp)
                        Spacer(Modifier.height(4.dp))
                        Text("No broker is connected. No live prices or trading orders are used.", color = Color(0xFFC5B58E), fontSize = 12.sp)
                    }
                }

                Text("WORKSPACE STATUS", color = Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                StatusCard("Broker connection", "Not connected", Muted)
                StatusCard("Automated trading", "Disabled", Green)
                StatusCard("Market data", "Demo only", Muted)

                Spacer(Modifier.weight(1f))
                Text("QUANTNEX · Build carefully. Trade responsibly.", color = Muted, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun StatusCard(title: String, value: String, valueColor: Color) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(13.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(title, color = Color.White, fontSize = 13.sp)
            Text(value, color = valueColor, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}
