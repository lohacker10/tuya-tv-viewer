package it.tuyatv.logintest;

public final class SafeDiagnosticsTest {
    public static void main(String[] args) {
        String message="STREAM VIDEO (sperimentale)\n"+
            "• ✓ MQTT connesso.\n"+
            "• Record canale: 4420 | AES OK: 4420 | RTP: 0\n"+
            "• Nessuna risposta SDP dalla telecamera entro il timeout.\n"+
            "Dispositivo: Telecamera Est\n"+
            "sid=abcdef12345 token:abcdefghijklmnop\n"+
            "email=utente@example.com\n";
        String safe=SafeDiagnostics.forClipboard(message,"0.11.0");
        ensure(safe.contains("• ✓ MQTT connesso."),"MQTT bullet lost");
        ensure(safe.contains("• Record canale: 4420"),"Record diagnostic lost");
        ensure(safe.contains("• Nessuna risposta SDP"),"SDP diagnostic lost");
        ensure(safe.contains("Dispositivo: [nome omesso]"),"Device not removed");
        ensure(!safe.contains("Telecamera Est"),"Camera name exposed");
        ensure(!safe.contains("abcdef12345"),"SID exposed");
        ensure(!safe.contains("abcdefghijklmnop"),"token exposed");
        ensure(!safe.contains("utente@example.com"),"email exposed");
        ensure(safe.contains("0.11.0\nSTREAM VIDEO"),"Newline missing");
        System.out.println("SafeDiagnostics tests passed");
    }
    private static void ensure(boolean condition,String why){
        if(!condition)throw new AssertionError(why);
    }
}
