package com.quantnex.mobile

import android.app.DownloadManager
import android.content.*
import android.net.Uri
import android.os.Bundle
import android.webkit.*
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val PREFS = "quantnex_mobile"
private const val REPO = "adeeshadasuniduwara/QUANTNEX"
private val Bg = Color(0xFF080D13)
private val Panel = Color(0xFF111A25)
private val Accent = Color(0xFF50D6B0)
private val Muted = Color(0xFF8FA0B5)

class MainActivity : ComponentActivity() {
    private var webView: WebView? = null
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = android.graphics.Color.rgb(8,13,19)
        window.navigationBarColor = android.graphics.Color.rgb(8,13,19)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(background=Bg, surface=Panel, primary=Accent, onPrimary=Bg, onSurface=Color.White)) {
                QuantnexApp(
                    savedUrl = getSharedPreferences(PREFS, MODE_PRIVATE).getString("url", "") ?: "",
                    onSaveUrl = { getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("url", it).apply() },
                    onWebView = { webView = it },
                    onNavigate = { key -> webView?.evaluateJavascript("(function(){var a=document.querySelector('a[href=\\\"#$key\\\"]');if(a)a.click();else location.hash='#$key';})();", null) },
                    onReload = { webView?.reload() },
                    onUpdate = { url -> downloadApk(url) },
                    checkUpdate = { fetchRelease() }
                )
            }
        }
    }

    private fun fetchRelease(): JSONObject? = try {
        val c = URL("https://api.github.com/repos/$REPO/releases/latest").openConnection() as HttpURLConnection
        c.connectTimeout = 10000
        c.readTimeout = 15000
        c.setRequestProperty("Accept", "application/vnd.github+json")
        c.setRequestProperty("User-Agent", "QUANTNEX-Android")
        val result = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
        c.disconnect()
        result
    } catch (_: Exception) { null }

    private fun downloadApk(url: String) {
        try {
            val request = DownloadManager.Request(Uri.parse(url))
                .setTitle("QUANTNEX Android update")
                .setDescription("Downloading the latest QUANTNEX APK")
                .setMimeType("application/vnd.android.package-archive")
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalFilesDir(this, android.os.Environment.DIRECTORY_DOWNLOADS, "QUANTNEX-update.apk")
            val manager = getSystemService(DOWNLOAD_SERVICE) as DownloadManager
            val id = manager.enqueue(request)
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(context: Context, intent: Intent) {
                    if (intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L) != id) return
                    unregisterReceiver(this)
                    val apk = manager.getUriForDownloadedFile(id) ?: return
                    startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(apk, "application/vnd.android.package-archive").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
                }
            }
            if (android.os.Build.VERSION.SDK_INT >= 33) registerReceiver(receiver, IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE), Context.RECEIVER_EXPORTED)
            else @Suppress("DEPRECATION") registerReceiver(receiver, IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE))
        } catch (_: Exception) { }
    }
}

@Composable
private fun QuantnexApp(
    savedUrl: String,
    onSaveUrl: (String) -> Unit,
    onWebView: (WebView) -> Unit,
    onNavigate: (String) -> Unit,
    onReload: () -> Unit,
    onUpdate: (String) -> Unit,
    checkUpdate: suspend () -> JSONObject?
) {
    var url by remember { mutableStateOf(savedUrl) }
    var editUrl by remember { mutableStateOf(savedUrl) }
    var showSettings by remember { mutableStateOf(savedUrl.isBlank()) }
    var release by remember { mutableStateOf<JSONObject?>(null) }
    var active by remember { mutableStateOf("overview") }
    var error by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { release = withContext(Dispatchers.IO) { checkUpdate() } }
    BackHandler(enabled = true) { onNavigate("overview") }

    Column(Modifier.fillMaxSize().background(Bg)) {
        Row(Modifier.fillMaxWidth().padding(horizontal=16.dp, vertical=9.dp), verticalAlignment=Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("QUANTNEX", color=Color.White, fontWeight=FontWeight.ExtraBold, fontSize=16.sp, letterSpacing=2.sp)
                Text("TRADING WORKSPACE", color=Muted, fontSize=9.sp, letterSpacing=1.4.sp)
            }
            IconButton(onClick=onReload) { Icon(Icons.Default.Refresh, "Refresh", tint=Accent) }
            IconButton(onClick={ editUrl=url; showSettings=true }) { Icon(Icons.Default.Settings, "Workspace settings", tint=Color.White) }
        }
        release?.let { data ->
            val apk = apkUrl(data)
            if (apk.isNotBlank()) Row(Modifier.fillMaxWidth().padding(horizontal=12.dp, vertical=4.dp).background(Color(0xFF16372F), RoundedCornerShape(12.dp)).padding(10.dp), verticalAlignment=Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("New QUANTNEX version: " + data.optString("tag_name"), color=Color.White, fontSize=12.sp, fontWeight=FontWeight.Bold)
                    Text("Download and approve the Android update.", color=Color(0xFFB6D8CE), fontSize=10.sp)
                }
                TextButton(onClick={ onUpdate(apk) }) { Text("UPDATE", color=Accent) }
            }
        }
        if (url.isBlank()) {
            Column(Modifier.weight(1f).padding(24.dp), verticalArrangement=Arrangement.Center) {
                Text("YOUR TRADING WORKSPACE, ON ANDROID.", color=Color.White, fontSize=27.sp, fontWeight=FontWeight.ExtraBold)
                Spacer(Modifier.height(12.dp))
                Text("Connect the same QUANTNEX Web workspace to use its charts, trading room, market feeds, journal and tools.", color=Muted)
                Spacer(Modifier.height(18.dp))
                OutlinedTextField(editUrl, { editUrl=it }, modifier=Modifier.fillMaxWidth(), singleLine=true, label={ Text("HTTPS workspace URL") })
                Spacer(Modifier.height(12.dp))
                Button(onClick={
                    val v=editUrl.trim().trimEnd('/')
                    if(v.startsWith("https://")) { url=v; onSaveUrl(v); showSettings=false }
                }, modifier=Modifier.fillMaxWidth(), colors=ButtonDefaults.buttonColors(containerColor=Accent, contentColor=Bg)) { Text("CONNECT WORKSPACE") }
                Text("Your PC's localhost address cannot be opened from a phone. Host the Web workspace on a reachable HTTPS server first.", color=Muted, fontSize=11.sp)
            }
        } else {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                AndroidView(modifier=Modifier.fillMaxSize(), factory={ context ->
                    WebView(context).apply {
                        settings.javaScriptEnabled=true
                        settings.domStorageEnabled=true
                        settings.databaseEnabled=true
                        settings.mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        settings.allowFileAccess=false
                        settings.allowContentAccess=false
                        webChromeClient=WebChromeClient()
                        webViewClient=object: WebViewClient() {
                            override fun onPageFinished(view: WebView, page: String) {
                                error=""
                                view.evaluateJavascript("(function(){var s=document.createElement('style');s.textContent='@media(max-width:900px){.sidebar{display:none!important}.main{margin-left:0!important;width:100%!important}.layout{display:block!important}}';document.head.appendChild(s);})();", null)
                            }
                            override fun onReceivedError(view: WebView, request: WebResourceRequest, e: WebResourceError) {
                                if(request.isForMainFrame) error="Workspace unavailable. Check the URL and internet connection."
                            }
                        }
                        loadUrl(url)
                        onWebView(this)
                    }
                }, update={ onWebView(it) })
                if(error.isNotBlank()) Column(Modifier.align(Alignment.Center).padding(24.dp).background(Panel, RoundedCornerShape(14.dp)).padding(18.dp)) {
                    Text("Connection problem", color=Color.White, fontWeight=FontWeight.Bold)
                    Text(error, color=Muted, fontSize=12.sp)
                    TextButton(onClick=onReload) { Text("RETRY", color=Accent) }
                }
            }
            NavigationBar(containerColor=Panel) {
                val items=listOf(Triple("Home","overview",Icons.Default.Dashboard),Triple("Chart","tradingview",Icons.Default.ShowChart),Triple("Room","trading-room",Icons.Default.Groups),Triple("Journal","journal",Icons.Default.MenuBook),Triple("More","updates",Icons.Default.MoreHoriz))
                items.forEach { item -> NavigationBarItem(
                    selected=active==item.second,
                    onClick={ active=item.second; onNavigate(item.second) },
                    icon={ Icon(item.third, item.first) }, label={ Text(item.first, fontSize=10.sp) },
                    colors=NavigationBarItemDefaults.colors(selectedIconColor=Accent, selectedTextColor=Accent, indicatorColor=Color(0xFF20382F), unselectedIconColor=Muted, unselectedTextColor=Muted)
                ) }
            }
        }
    }
    if(showSettings && url.isNotBlank()) AlertDialog(
        onDismissRequest={ showSettings=false }, containerColor=Panel,
        title={ Text("Workspace settings", color=Color.White) },
        text={ OutlinedTextField(editUrl, { editUrl=it }, singleLine=true, label={ Text("HTTPS workspace URL") }) },
        confirmButton={ TextButton(onClick={ val v=editUrl.trim().trimEnd('/'); if(v.startsWith("https://")) { url=v; onSaveUrl(v); showSettings=false } }) { Text("SAVE", color=Accent) } },
        dismissButton={ TextButton(onClick={ showSettings=false }) { Text("CANCEL", color=Muted) } }
    )
}

private fun apkUrl(release: JSONObject): String {
    val assets=release.optJSONArray("assets") ?: return ""
    for(i in 0 until assets.length()) {
        val a=assets.optJSONObject(i) ?: continue
        if(a.optString("name").endsWith(".apk", true)) return a.optString("browser_download_url")
    }
    return ""
}
