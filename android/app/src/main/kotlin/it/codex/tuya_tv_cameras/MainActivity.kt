package it.codex.tuya_tv_cameras

import android.content.Intent
import android.content.pm.PackageInfo
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.WindowManager
import android.util.Base64
import androidx.core.content.FileProvider
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.security.KeyStore
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val METHOD_CHANNEL = "tuya_tv/backend"
private const val EVENT_CHANNEL = "tuya_tv/events"

class MainActivity : FlutterActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val poller = Executors.newSingleThreadScheduledExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private lateinit var bridge: PyObject
    private lateinit var vault: CredentialVault
    @Volatile private var eventSink: EventChannel.EventSink? = null
    private var eventPoll: ScheduledFuture<*>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
        bridge = Python.getInstance().getModule("bridge")
        vault = CredentialVault(applicationContext)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, METHOD_CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "checkForUpdate" -> worker.execute {
                        val update = try {
                            latestUpdate()?.toString()
                        } catch (_: Exception) {
                            null
                        }
                        mainHandler.post { result.success(update) }
                    }
                    "canInstallUpdates" -> result.success(
                        Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageManager.canRequestPackageInstalls(),
                    )
                    "getQualityMode" -> result.success(
                        getSharedPreferences("tuya_settings", MODE_PRIVATE).getString("quality_mode", "auto"),
                    )
                    "setQualityMode" -> {
                        val mode = call.arguments as? String
                        if (mode == null || mode !in listOf("auto", "hd", "sd")) {
                            result.error("INVALID_QUALITY", "Qualità video non valida.", null)
                        } else {
                            getSharedPreferences("tuya_settings", MODE_PRIVATE)
                                .edit()
                                .putString("quality_mode", mode)
                                .apply()
                            result.success(null)
                        }
                    }
                    "installUpdate" -> {
                        val args = call.arguments as? Map<*, *>
                        val version = args?.get("version") as? String
                        val apkUrl = args?.get("apkUrl") as? String
                        val checksumUrl = args?.get("checksumUrl") as? String
                        if (version.isNullOrBlank() || apkUrl.isNullOrBlank() || checksumUrl.isNullOrBlank()) {
                            result.error("INVALID_UPDATE", "Aggiornamento non valido.", null)
                        } else worker.execute {
                            try {
                                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !packageManager.canRequestPackageInstalls()) {
                                    mainHandler.post {
                                        try {
                                            startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                                            result.success(false)
                                        } catch (exception: Exception) {
                                            result.error("UPDATE_PERMISSION", safeMessage(exception), null)
                                        }
                                    }
                                } else {
                                    val apk = downloadAndVerifyUpdate(version, apkUrl, checksumUrl)
                                    mainHandler.post {
                                        try {
                                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !packageManager.canRequestPackageInstalls()) {
                                                startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
                                                result.success(false)
                                            } else {
                                                startPackageInstaller(apk)
                                                result.success(true)
                                            }
                                        } catch (exception: Exception) {
                                            result.error("UPDATE_INSTALL_FAILED", safeMessage(exception), null)
                                        }
                                    }
                                }
                            } catch (exception: Exception) {
                                mainHandler.post { result.error("UPDATE_FAILED", safeMessage(exception), null) }
                            }
                        }
                    }
                    "autoLogin" -> worker.execute {
                        val credentials = vault.read()
                        if (credentials == null) {
                            mainHandler.post { result.success(null) }
                        } else {
                            runBridge(result) {
                                login(credentials.username, credentials.password, credentials.countryCode, credentials.region)
                            }
                        }
                    }
                    "login" -> {
                        val args = call.arguments as? Map<*, *>
                        val username = args?.get("username") as? String
                        val password = args?.get("password") as? String
                        val countryCode = args?.get("countryCode") as? String
                        val region = args?.get("region") as? String
                        if (username.isNullOrBlank() || password.isNullOrBlank() || countryCode.isNullOrBlank() || region.isNullOrBlank()) {
                            result.error("INVALID_LOGIN", "Inserisci email/telefono e password Tuya.", null)
                        } else worker.execute {
                            runBridge(result) {
                                val cameras = login(username.trim(), password, countryCode, region)
                                vault.save(username.trim(), password, countryCode, region)
                                cameras
                            }
                        }
                    }
                    "prepareStream" -> {
                        val args = call.arguments as? Map<*, *>
                        val id = args?.get("id") as? String
                        val quality = args?.get("quality") as? String
                        if (id.isNullOrBlank() || quality !in listOf("sd", "hd")) result.error("INVALID_CAMERA", "Telecamera non valida", null)
                        else worker.execute { runBridge(result, "STREAM_START") {
                            bridge.callAttr("prepare_stream", id, quality).toJava(String::class.java)
                        } }
                    }
                    "rtcSignal" -> {
                        val args = call.arguments as? Map<*, *>
                        val values = listOf("id", "handle", "type", "value").map { args?.get(it) as? String }
                        if (values.any { it.isNullOrBlank() }) result.error("INVALID_SIGNAL", "Segnale non valido", null)
                        else worker.execute { runBridge(result, "STREAM_SIGNAL") {
                            bridge.callAttr("rtc_signal", *values.toTypedArray())
                            null
                        } }
                    }
                    "stopStreams" -> worker.execute { runBridge(result, "STREAM_STOP") {
                        bridge.callAttr("stop_streams")
                        null
                    } }
                    "logout" -> worker.execute {
                        try {
                            bridge.callAttr("logout")
                            vault.clear()
                            mainHandler.post { result.success(null) }
                        } catch (exception: Exception) {
                            mainHandler.post { result.error("LOGOUT_FAILED", safeMessage(exception), null) }
                        }
                    }
                    else -> result.notImplemented()
                }
            }

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, EVENT_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    eventSink = events
                    eventPoll?.cancel(false)
                    eventPoll = poller.scheduleAtFixedRate({ emitEvents() }, 0, 100, TimeUnit.MILLISECONDS)
                }

                override fun onCancel(arguments: Any?) {
                    eventSink = null
                    eventPoll?.cancel(false)
                    eventPoll = null
                }
            })
    }

    private fun login(username: String, password: String, countryCode: String, region: String): String =
        bridge.callAttr("login", username, password, countryCode, region, vault.installationId).toJava(String::class.java)

    private fun runBridge(result: MethodChannel.Result, code: String = "LOGIN_FAILED", block: () -> Any?) {
        try {
            val cameras = block()
            mainHandler.post { result.success(cameras) }
        } catch (exception: Exception) {
            mainHandler.post { result.error(code, safeMessage(exception), null) }
        }
    }

    private fun emitEvents() {
        if (eventSink == null) return
        try {
            val events = bridge.callAttr("drain_events").toJava(String::class.java)
            if (events != "[]") mainHandler.post { eventSink?.success(events) }
        } catch (_: Exception) {
            // The activity may be stopping while the event channel polls.
        }
    }

    override fun onDestroy() {
        eventSink = null
        eventPoll?.cancel(false)
        poller.shutdownNow()
        worker.shutdown()
        super.onDestroy()
    }

    private fun safeMessage(exception: Exception): String =
        exception.cause?.message ?: exception.message ?: "Errore di comunicazione con Tuya."

    private fun latestUpdate(): JSONObject? {
        val release = JSONObject(String(
            readUrl("https://api.github.com/repos/lohacker10/tuya-tv-viewer/releases/latest", 2_000_000),
            Charsets.UTF_8,
        ))
        if (release.optBoolean("draft", true) || release.optBoolean("prerelease", true)) return null
        val version = release.optString("tag_name").removePrefix("v")
        if (!version.matches(Regex("\\d+\\.\\d+\\.\\d+"))) return null
        val installed = packageManager.getPackageInfo(packageName, 0).versionName ?: return null
        if (!isNewerVersion(version, installed)) return null

        val apkName = "Telecamere-v$version.apk"
        val assets = release.optJSONArray("assets") ?: return null
        var apkUrl: String? = null
        var checksumUrl: String? = null
        for (index in 0 until assets.length()) {
            val asset = assets.optJSONObject(index) ?: continue
            when (asset.optString("name")) {
                apkName -> apkUrl = asset.optString("browser_download_url")
                "$apkName.sha256" -> checksumUrl = asset.optString("browser_download_url")
            }
        }
        if (apkUrl.isNullOrBlank() || checksumUrl.isNullOrBlank()) return null
        return JSONObject()
            .put("version", version)
            .put("apkUrl", apkUrl)
            .put("checksumUrl", checksumUrl)
    }

    private fun isNewerVersion(candidate: String, installed: String): Boolean {
        fun parts(value: String): List<Int>? {
            val match = Regex("^(?:v)?(\\d+)\\.(\\d+)\\.(\\d+)(?:[-+].*)?$").matchEntire(value) ?: return null
            return match.groupValues.drop(1).take(3).map { it.toIntOrNull() ?: return null }
        }
        val newer = parts(candidate) ?: return false
        val current = parts(installed) ?: return true
        for (index in newer.indices) {
            if (newer[index] != current[index]) return newer[index] > current[index]
        }
        return false
    }

    private fun downloadAndVerifyUpdate(version: String, apkUrl: String, checksumUrl: String): File {
        require(version.matches(Regex("\\d+\\.\\d+\\.\\d+"))) { "Versione non valida" }
        val apkName = "Telecamere-v$version.apk"
        val prefix = "/lohacker10/tuya-tv-viewer/releases/download/v$version/"
        require(isReleaseAsset(apkUrl, prefix, apkName)) { "URL APK non valido" }
        require(isReleaseAsset(checksumUrl, prefix, "$apkName.sha256")) { "URL checksum non valido" }

        val checksumText = String(readUrl(checksumUrl, 4096, "text/plain"), Charsets.UTF_8)
        val expected = Regex("(?i)^([0-9a-f]{64})\\b").find(checksumText.trim())?.groupValues?.get(1)?.lowercase()
            ?: throw IllegalStateException("Checksum APK non valido")
        val directory = File(cacheDir, "updates").apply { mkdirs() }
        val apkFile = File(directory, apkName)
        val temporary = File(directory, "$apkName.part")
        temporary.delete()
        val connection = openConnection(apkUrl, "application/octet-stream")
        try {
            if (connection.contentLengthLong > 250L * 1024 * 1024) throw IllegalStateException("APK troppo grande")
            val digest = MessageDigest.getInstance("SHA-256")
            var total = 0L
            connection.inputStream.use { input ->
                temporary.outputStream().buffered().use { output ->
                    val buffer = ByteArray(32 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        if (total > 250L * 1024 * 1024) throw IllegalStateException("APK troppo grande")
                        digest.update(buffer, 0, count)
                        output.write(buffer, 0, count)
                    }
                }
            }
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            if (!MessageDigest.isEqual(expected.toByteArray(), actual.toByteArray())) {
                throw IllegalStateException("Checksum APK non corrispondente")
            }
            apkFile.delete()
            if (!temporary.renameTo(apkFile)) throw IllegalStateException("Salvataggio APK non riuscito")
        } catch (exception: Exception) {
            temporary.delete()
            throw exception
        } finally {
            connection.disconnect()
        }

        @Suppress("DEPRECATION")
        val candidate = packageManager.getPackageArchiveInfo(apkFile.absolutePath, 0)
            ?: throw IllegalStateException("File APK non valido")
        if (candidate.packageName != packageName || candidate.versionName != version) {
            apkFile.delete()
            throw IllegalStateException("APK non corrisponde a questa app")
        }
        val installed = packageManager.getPackageInfo(packageName, 0)
        if (packageVersionCode(candidate) <= packageVersionCode(installed)) {
            apkFile.delete()
            throw IllegalStateException("La versione APK non è più recente")
        }
        return apkFile
    }

    private fun isReleaseAsset(url: String, prefix: String, name: String): Boolean {
        val uri = Uri.parse(url)
        return uri.scheme == "https" && uri.host == "github.com" && uri.encodedPath == prefix + name
    }

    private fun readUrl(url: String, maxBytes: Int, accept: String = "application/vnd.github+json"): ByteArray {
        val connection = openConnection(url, accept)
        try {
            val output = ByteArrayOutputStream()
            connection.inputStream.use { input ->
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (output.size() + count > maxBytes) throw IllegalStateException("Risposta GitHub troppo grande")
                    output.write(buffer, 0, count)
                }
            }
            return output.toByteArray()
        } finally {
            connection.disconnect()
        }
    }

    private fun openConnection(url: String, accept: String = "application/vnd.github+json"): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 12_000
            readTimeout = 25_000
            instanceFollowRedirects = true
            requestMethod = "GET"
            setRequestProperty("User-Agent", "Telecamere-Android-TV")
            setRequestProperty("Accept", accept)
            if (responseCode !in 200..299) {
                disconnect()
                throw IllegalStateException("Download GitHub non riuscito (HTTP $responseCode)")
            }
        }

    @Suppress("DEPRECATION")
    private fun packageVersionCode(info: PackageInfo): Long =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()

    private fun startPackageInstaller(apk: File) {
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", apk)
        val intent = Intent(Intent.ACTION_INSTALL_PACKAGE).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            putExtra(Intent.EXTRA_RETURN_RESULT, true)
        }
        startActivity(intent)
    }
}

private data class TuyaCredentials(
    val username: String,
    val password: String,
    val countryCode: String,
    val region: String,
)

private class CredentialVault(context: android.content.Context) {
    private val preferences = context.getSharedPreferences("tuya_credentials", android.content.Context.MODE_PRIVATE)
    private val alias = "tuya_tv_credentials_v1"
    val installationId: String = preferences.getString("installation_id", null) ?: (
        UUID.randomUUID().toString().replace("-", "") +
            UUID.randomUUID().toString().replace("-", "").take(12)
    ).also { preferences.edit().putString("installation_id", it).apply() }

    fun save(username: String, password: String, countryCode: String, region: String) {
        val json = JSONObject()
            .put("username", username)
            .put("password", password)
            .put("countryCode", countryCode)
            .put("region", region)
            .toString()
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.iv + cipher.doFinal(json.toByteArray(Charsets.UTF_8))
        preferences.edit().putString("sealed", Base64.encodeToString(encrypted, Base64.NO_WRAP)).apply()
    }

    fun read(): TuyaCredentials? {
        val sealed = preferences.getString("sealed", null) ?: return null
        return try {
            val encrypted = Base64.decode(sealed, Base64.NO_WRAP)
            require(encrypted.size > 12) { "Credenziali salvate non valide" }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, encrypted.copyOfRange(0, 12)))
            val json = JSONObject(String(cipher.doFinal(encrypted.copyOfRange(12, encrypted.size)), Charsets.UTF_8))
            TuyaCredentials(
                json.getString("username"),
                json.getString("password"),
                json.getString("countryCode"),
                json.getString("region"),
            )
        } catch (_: Exception) {
            clear()
            null
        }
    }

    fun clear() {
        preferences.edit().remove("sealed").apply()
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance("AES", "AndroidKeyStore")
        generator.init(
            android.security.keystore.KeyGenParameterSpec.Builder(
                alias,
                android.security.keystore.KeyProperties.PURPOSE_ENCRYPT or
                    android.security.keystore.KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes("GCM")
                .setEncryptionPaddings("NoPadding")
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }
}
