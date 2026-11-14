package com.quantnex.mobile

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream

class AndroidReleaseVerifierTest {
    private fun asset(name: String, url: String) = JSONObject()
        .put("name", name)
        .put("browser_download_url", url)

    @Test
    fun requiresBothApkAndChecksumFromOfficialGithubRelease() {
        val release = JSONObject().put("assets", JSONArray()
            .put(asset("QUANTNEX-Android.apk", "https://github.com/owner/repo/releases/download/v1/QUANTNEX-Android.apk"))
            .put(asset("SHA256SUMS.txt", "https://github.com/owner/repo/releases/download/v1/SHA256SUMS.txt")))

        val result = AndroidReleaseVerifier.findApkAsset(release)

        assertNotNull(result)
        assertEquals("QUANTNEX-Android.apk", result?.fileName)
        assertTrue(result?.checksumUrl?.endsWith("SHA256SUMS.txt") == true)
    }

    @Test
    fun doesNotOfferApkWhenChecksumManifestIsMissing() {
        val release = JSONObject().put("assets", JSONArray()
            .put(asset("QUANTNEX-Android.apk", "https://github.com/owner/repo/releases/download/v1/QUANTNEX-Android.apk")))

        assertNull(AndroidReleaseVerifier.findApkAsset(release))
    }

    @Test
    fun rejectsNonHttpsAndNonGithubAssetUrls() {
        assertFalse(AndroidReleaseVerifier.isTrustedReleaseAssetUrl("http://github.com/owner/repo/file.apk"))
        assertFalse(AndroidReleaseVerifier.isTrustedReleaseAssetUrl("https://example.com/file.apk"))
        assertFalse(AndroidReleaseVerifier.isTrustedReleaseAssetUrl("https://user:pass@github.com/file.apk"))
        assertFalse(AndroidReleaseVerifier.isTrustedReleaseAssetUrl("not a URL"))
    }

    @Test
    fun verifiesExactApkDigestAndFilename() {
        val bytes = "QUANTNEX synthetic APK test payload".toByteArray()
        val digest = AndroidReleaseVerifier.sha256(ByteArrayInputStream(bytes))
        val manifest = "$digest  QUANTNEX-Android.apk\n"

        assertTrue(AndroidReleaseVerifier.verifySha256(digest, manifest, "QUANTNEX-Android.apk"))
        assertFalse(AndroidReleaseVerifier.verifySha256("0".repeat(64), manifest, "QUANTNEX-Android.apk"))
        assertFalse(AndroidReleaseVerifier.verifySha256(digest, manifest, "Other.apk"))
    }

    @Test
    fun refusesMalformedChecksumEntries() {
        assertNull(AndroidReleaseVerifier.expectedSha256("not-a-checksum  QUANTNEX-Android.apk", "QUANTNEX-Android.apk"))
        assertNull(AndroidReleaseVerifier.expectedSha256("a".repeat(64) + "  QUANTNEX.exe", "QUANTNEX-Android.apk"))
    }
}
