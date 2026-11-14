package com.quantnex.mobile

import org.json.JSONObject
import java.io.InputStream
import java.net.URI
import java.security.MessageDigest

internal data class AndroidApkReleaseAsset(
    val downloadUrl: String,
    val checksumUrl: String,
    val fileName: String
)

/** Validates official Android release metadata and the downloaded APK checksum. */
internal object AndroidReleaseVerifier {
    private const val MAX_APK_BYTES = 150L * 1024L * 1024L

    fun findApkAsset(release: JSONObject): AndroidApkReleaseAsset? {
        val assets = release.optJSONArray("assets") ?: return null
        var apkName = ""
        var apkUrl = ""
        var checksumUrl = ""
        for (index in 0 until assets.length()) {
            val asset = assets.optJSONObject(index) ?: continue
            val name = asset.optString("name")
            val url = asset.optString("browser_download_url")
            if (name.endsWith(".apk", ignoreCase = true) && apkName.isBlank()) {
                apkName = name
                apkUrl = url
            }
            if (name.equals("SHA256SUMS.txt", ignoreCase = true)) {
                checksumUrl = url
            }
        }
        if (apkName.isBlank() || !isTrustedReleaseAssetUrl(apkUrl) ||
            !isTrustedReleaseAssetUrl(checksumUrl)
        ) return null
        return AndroidApkReleaseAsset(apkUrl, checksumUrl, apkName)
    }

    fun isTrustedReleaseAssetUrl(value: String): Boolean {
        val uri = try { URI(value) } catch (_: Exception) { return false }
        return uri.scheme?.equals("https", ignoreCase = true) == true &&
            uri.host?.equals("github.com", ignoreCase = true) == true &&
            uri.userInfo == null && (uri.port == -1 || uri.port == 443)
    }

    fun expectedSha256(checksumText: String, fileName: String): String? {
        for (line in checksumText.lineSequence()) {
            val fields = line.trim().split(Regex("\\s+"), limit = 2)
            if (fields.size != 2 || !fields[0].matches(Regex("(?i)[0-9a-f]{64}"))) continue
            val listedName = fields[1].trim().removePrefix("*")
            if (listedName == fileName || listedName.endsWith("/$fileName")) {
                return fields[0].lowercase()
            }
        }
        return null
    }

    fun sha256(input: InputStream): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(16 * 1024)
        var total = 0L
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            total += count
            require(total <= MAX_APK_BYTES) { "Downloaded APK exceeds the 150 MB safety limit." }
            digest.update(buffer, 0, count)
        }
        require(total > 0L) { "Downloaded APK is empty." }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    fun verifySha256(actual: String, checksumText: String, fileName: String): Boolean {
        val expected = expectedSha256(checksumText, fileName) ?: return false
        return actual.matches(Regex("(?i)[0-9a-f]{64}")) &&
            MessageDigest.isEqual(
                expected.toByteArray(Charsets.US_ASCII),
                actual.lowercase().toByteArray(Charsets.US_ASCII)
            )
    }
}
