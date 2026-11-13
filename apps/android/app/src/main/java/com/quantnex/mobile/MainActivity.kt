package com.quantnex.mobile

import android.app.DownloadManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.*
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.content.pm.PackageManager
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val PREFS = "quantnex_mobile"
private const val REPO = "adeeshadasuniduwara/QUANTNEX"
private const val UPDATE_CHANNEL = "quantnex_updates"
private const val UPDATE_PREF = "last_notified_release"
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
        createUpdateChannel()
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 7301)
        }
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(background=Bg, surface=Panel, primary=Accent, onPrimary=Bg, onSurface=Color.White)) {
                QuantnexApp(
                    savedUrl = getSharedPreferences(PREFS, MODE_PRIVATE).getString("url", "") ?: "",
                    onSaveUrl = { getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("url", it).apply() },
                    onWebView = { webView = it },
                    onNavigate = { key -> webView?.evaluateJavascript("(function(){var a=document.querySelector('a[href=\\\"#$key\\\"]');if(a)a.click();else location.hash='#$key';})();", null) },
                    onReload = { webView?.reload() },
                    onUpdate = { url -> downloadApk(url) },
                    checkUpdate = { fetchRelease() },
                    lastNotifiedTag = getSharedPreferences(PREFS, MODE_PRIVATE).getString(UPDATE_PREF, "") ?: "",
                    installedVersion = packageManager.getPackageInfo(packageName, 0).versionName ?: "0",
                    onReleaseSeen = { tag -> getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(UPDATE_PREF, tag).apply() },
                    onNotifyRelease = { data -> notifyRelease(data) }
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

    private fun createUpdateChannel() {
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(UPDATE_CHANNEL, "QUANTNEX updates", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "New QUANTNEX Android releases"
        })
    }

    private fun notifyRelease(release: JSONObject) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val launch = packageManager.getLaunchIntentForPackage(packageName) ?: return
        val pending = PendingIntent.getActivity(this, 7302, launch, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val tag = release.optString("tag_name", "New version")
        val notification = Notification.Builder(this, UPDATE_CHANNEL)
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setContentTitle("QUANTNEX update released")
            .setContentText("Version $tag is ready. Open QUANTNEX to download it.")
            .setStyle(Notification.BigTextStyle().bigText("A new QUANTNEX Android update ($tag) is available. Open the app and tap UPDATE to download and install it."))
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(7303, notification)
    }
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
    checkUpdate: suspend () -> JSONObject?,
    lastNotifiedTag: String,
    installedVersion: String,
    onReleaseSeen: (String) -> Unit,
    onNotifyRelease: (JSONObject) -> Unit
) {
    var url by remember { mutableStateOf(savedUrl) }
    var editUrl by remember { mutableStateOf(savedUrl) }
    var showSettings by remember { mutableStateOf(savedUrl.isBlank()) }
    var release by remember { mutableStateOf<JSONObject?>(null) }
    var active by remember { mutableStateOf("overview") }
    var error by remember { mutableStateOf("") }
    var showUpdatePopup by remember { mutableStateOf(false) }
    var dashboardRefresh by remember { mutableIntStateOf(0) }
    var notifiedTag by remember { mutableStateOf(lastNotifiedTag) }
    LaunchedEffect(Unit) {
        while (true) {
            val latest = withContext(Dispatchers.IO) { checkUpdate() }
            if (latest != null && apkUrl(latest).isNotBlank()) {
                val tag = latest.optString("tag_name")
                if (tag.isNotBlank()) {
                    if (notifiedTag.isBlank()) {
                        release = latest
                        if (tag.removePrefix("v") != installedVersion.removePrefix("v")) {
                            showUpdatePopup = true
                            onNotifyRelease(latest)
                        }
                        notifiedTag = tag
                        onReleaseSeen(tag)
                    } else if (tag != notifiedTag) {
                        release = latest
                        showUpdatePopup = true
                        onNotifyRelease(latest)
                        notifiedTag = tag
                        onReleaseSeen(tag)
                    } else {
                        release = latest
                    }
                }
            }
            delay(5 * 60 * 1000L)
        }
    }
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
        if (url.isBlank() || active == "overview" || active == "tradingview") {
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when (active) {
                    "overview" -> NativeDashboardScreen(
                        refreshKey = dashboardRefresh,
                        onRefresh = { dashboardRefresh++ },
                        onOpenSettings = { editUrl=url; showSettings=true }
                    )
                    "tradingview" -> NativeChartScreen()
                    "trading-room" -> NativeFeaturePlaceholder("TRADING ROOM", "Live market discussion, market context and trading-room tools will be integrated in a later native phase.")
                    "journal" -> NativeFeaturePlaceholder("TRADE JOURNAL", "Your local trade journal and wallet tools will be connected after the secure data-sync architecture is ready.")
                    else -> NativeFeaturePlaceholder("MORE TOOLS", "Updates, settings, prop-firm challenges and the remaining QUANTNEX toolkit will be added progressively.")
                }
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
        }
        NavigationBar(containerColor=Panel) {
            val items=listOf(Triple("Home","overview",Icons.Default.Dashboard),Triple("Chart","tradingview",Icons.Default.ShowChart),Triple("Room","trading-room",Icons.Default.Groups),Triple("Journal","journal",Icons.Default.MenuBook),Triple("More","updates",Icons.Default.MoreHoriz))
            items.forEach { item -> NavigationBarItem(
                selected=active==item.second,
                onClick={ active=item.second; if(url.isNotBlank()) onNavigate(item.second) },
                icon={ Icon(item.third, item.first) }, label={ Text(item.first, fontSize=10.sp) },
                colors=NavigationBarItemDefaults.colors(selectedIconColor=Accent, selectedTextColor=Accent, indicatorColor=Color(0xFF20382F), unselectedIconColor=Muted, unselectedTextColor=Muted)
            ) }
        }
    }
    if (showUpdatePopup && release != null) {
        val updateData = release!!
        AlertDialog(
            onDismissRequest = { showUpdatePopup = false },
            containerColor = Panel,
            title = { Text("New update released!", color = Color.White, fontWeight = FontWeight.Bold) },
            text = { Text("QUANTNEX " + updateData.optString("tag_name") + " is available. Download the latest Android update now?", color = Muted) },
            confirmButton = {
                TextButton(onClick = { showUpdatePopup = false; onUpdate(apkUrl(updateData)) }) {
                    Text("DOWNLOAD NOW", color = Accent, fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = { TextButton(onClick = { showUpdatePopup = false }) { Text("LATER", color = Muted) } }
        )
    }
    if(showSettings) AlertDialog(
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
