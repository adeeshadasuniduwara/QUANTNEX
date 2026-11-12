package com.quantnex.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Background = Color(0xFF080808)
private val Panel = Color(0xFF151515)
private val Muted = Color(0xFF929292)
private val Accent = Color(0xFFF2F2F2)
private val Ink = Color(0xFF111111)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { QuantnexApp() }
    }
}

@Composable
private fun QuantnexApp() {
    var visible by remember { mutableStateOf(false) }
    val alpha by animateFloatAsState(if (visible) 1f else 0f, tween(650), label = "screenFade")
    LaunchedEffect(Unit) { visible = true }
    MaterialTheme(colorScheme = darkColorScheme(
        background = Background, surface = Panel, primary = Accent,
        onPrimary = Ink, onSurface = Color.White
    )) {
        Surface(modifier = Modifier.fillMaxSize(), color = Background) {
            Column(
                modifier = Modifier.fillMaxSize().alpha(alpha).background(Background).padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Column {
                        Text("QUANTNEX", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
                        Text("Overview", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                    }
                    Text("v0.1.0", color = Muted, fontSize = 12.sp)
                }
                Card(colors = CardDefaults.cardColors(containerColor = Accent), shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.padding(20.dp)) {
                        Text("QUANTNEX WORKSPACE", color = Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        Spacer(Modifier.height(9.dp))
                        Text("Clarity for every trading decision.", color = Ink, fontSize = 23.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(7.dp))
                        Text("A focused trading workspace across your devices.", color = Color.DarkGray, fontSize = 13.sp)
                    }
                }
                Text("WORKSPACE STATUS", color = Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                StatusCard("Broker connection", "Not connected")
                StatusCard("Automated trading", "Disabled")
                StatusCard("Market data", "Demo only")
                Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(14.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("UPDATES", color = Muted, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        Spacer(Modifier.height(5.dp))
                        Text("Keep QUANTNEX current", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Text("Software updates will be available through the official release channel.", color = Muted, fontSize = 12.sp)
                    }
                }
                Spacer(Modifier.weight(1f))
                Text("QUANTNEX · Build carefully. Trade responsibly.", color = Muted, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun StatusCard(title: String, value: String) {
    Card(colors = CardDefaults.cardColors(containerColor = Panel), shape = RoundedCornerShape(13.dp)) {
        Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(title, color = Color.White, fontSize = 13.sp)
            Text(value, color = Muted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}