package it.tuyatv.logintest;

import java.util.regex.Pattern;

/** Pure-Java privacy filter for user-copyable diagnostic messages. */
public final class SafeDiagnostics {
    private static final Pattern SECRETS=Pattern.compile(
        "(?i)\\b(password|passwd|token|localkey|local_key|ecode|sid|devId|deviceId|aesKey|sessionId)\\b\\s*[:=]\\s*[^\\s,;]+");
    private static final Pattern EMAIL=Pattern.compile(
        "(?i)\\b[a-z0-9._%+\\-]+@[a-z0-9.\\-]+\\.[a-z]{2,}\\b");
    private static final Pattern LONG_IDS=Pattern.compile(
        "\\b[a-zA-Z0-9_\\-]{32,}\\b");
    private static final Pattern IPV4=Pattern.compile(
        "\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b");

    private SafeDiagnostics(){}

    public static String forClipboard(String message, String version) {
        if(message==null)message="";
        // Only lines explicitly naming a camera are suppressed. Do NOT redact
        // ordinary bullet-point diagnostics.
        String filtered=message.replaceAll("(?m)^\\s*Dispositivo:\\s*[^\\r\\n]+",
                                            "Dispositivo: [nome omesso]");
        filtered=SECRETS.matcher(filtered).replaceAll("$1=[omesso]");
        filtered=EMAIL.matcher(filtered).replaceAll("[email omessa]");
        filtered=IPV4.matcher(filtered).replaceAll("[indirizzo omesso]");
        filtered=LONG_IDS.matcher(filtered).replaceAll("[identificativo omesso]");
        return "Tuya TV Viewer diagnostica v"+version+"\n"+filtered;
    }
}
