package it.codex.tuya_tv_cameras

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.security.KeyStore
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val METHOD_CHANNEL = "tuya_tv/backend"
private const val FRAME_CHANNEL = "tuya_tv/frames"

class MainActivity : FlutterActivity() {
    private val worker = Executors.newFixedThreadPool(2)
    private val poller = Executors.newSingleThreadScheduledExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private lateinit var bridge: PyObject
    private lateinit var vault: CredentialVault
    @Volatile private var frameSink: EventChannel.EventSink? = null
    private var framePoll: ScheduledFuture<*>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
        bridge = Python.getInstance().getModule("bridge")
        vault = CredentialVault(applicationContext)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, METHOD_CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
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
                    "startStreams" -> {
                        val cameraIds = (call.arguments as? List<*>)?.filterIsInstance<String>()
                        if (cameraIds == null) result.error("INVALID_CAMERAS", "Elenco telecamere non valido.", null)
                        else worker.execute {
                            try {
                                bridge.callAttr("start_streams", org.json.JSONArray(cameraIds).toString())
                                mainHandler.post { result.success(null) }
                            } catch (exception: Exception) {
                                mainHandler.post { result.error("STREAM_START", safeMessage(exception), null) }
                            }
                        }
                    }
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

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, FRAME_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                    frameSink = events
                    framePoll?.cancel(false)
                    framePoll = poller.scheduleAtFixedRate({ emitFrames() }, 0, 250, TimeUnit.MILLISECONDS)
                }

                override fun onCancel(arguments: Any?) {
                    frameSink = null
                    framePoll?.cancel(false)
                    framePoll = null
                }
            })
    }

    private fun login(username: String, password: String, countryCode: String, region: String): String =
        bridge.callAttr("login", username, password, countryCode, region).toJava(String::class.java)

    private fun runBridge(result: MethodChannel.Result, block: () -> String) {
        try {
            val cameras = block()
            mainHandler.post { result.success(cameras) }
        } catch (exception: Exception) {
            mainHandler.post { result.error("LOGIN_FAILED", safeMessage(exception), null) }
        }
    }

    private fun emitFrames() {
        if (frameSink == null) return
        try {
            val raw = bridge.callAttr("drain_frames").asMap()
            val frames = mutableMapOf<String, ByteArray>()
            raw.forEach { (key, value) ->
                val bytes = value.toJava(ByteArray::class.java)
                frames[key.toJava(String::class.java)] = bytes
            }
            if (frames.isNotEmpty()) mainHandler.post { frameSink?.success(frames) }
        } catch (_: Exception) {
            // A stream may be starting or stopping while the frame channel polls.
        }
    }

    private fun safeMessage(exception: Exception): String =
        exception.cause?.message ?: exception.message ?: "Errore di comunicazione con Tuya."
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
