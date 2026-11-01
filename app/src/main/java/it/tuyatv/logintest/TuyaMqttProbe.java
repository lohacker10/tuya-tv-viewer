package it.tuyatv.logintest;

import java.io.*;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.*;

/**
 * Read-only MQTT 3.1.1 CONNECT probe, with no subscriptions, publications, or
 * wire-data logs. Broker identity is derived in memory by TuyaClient.
 */
final class TuyaMqttProbe {
    private TuyaMqttProbe() {}
    static final class Result {
        final String safeDescription;
        Result(String message){ safeDescription=message; }
    }
    private static void mqttString(DataOutputStream data,String value) throws IOException {
        byte[] encoded=value.getBytes(StandardCharsets.UTF_8);
        if(encoded.length>65535)throw new IOException("MQTT field too long");
        data.writeShort(encoded.length);
        data.write(encoded);
    }
    private static byte[] connectPacket(String clientId,String username,String password) throws IOException {
        ByteArrayOutputStream payload=new ByteArrayOutputStream();
        DataOutputStream body=new DataOutputStream(payload);
        mqttString(body,"MQTT");body.writeByte(4); // MQTT 3.1.1
        body.writeByte(0xC2);                    // user, password, clean-session
        body.writeShort(20);
        mqttString(body,clientId);
        mqttString(body,username);
        mqttString(body,password);
        body.flush();
        byte[] bodyBytes=payload.toByteArray();
        ByteArrayOutputStream frame=new ByteArrayOutputStream();
        frame.write(0x10);
        int length=bodyBytes.length;
        do{
            int digit=length%128;
            length/=128;
            if(length>0)digit|=0x80;
            frame.write(digit);
        }while(length>0);
        frame.write(bodyBytes);
        return frame.toByteArray();
    }
    static Result verify(String host,String clientId,String username,String password) throws Exception {
        SSLSocketFactory factory=(SSLSocketFactory)SSLSocketFactory.getDefault();
        try(SSLSocket sock=(SSLSocket)factory.createSocket()){
            sock.connect(new java.net.InetSocketAddress(host,8883),10000);
            sock.setSoTimeout(10000);
            sock.startHandshake(); // default trust chain verification (not trust-all)
            OutputStream output=sock.getOutputStream();
            output.write(connectPacket(clientId,username,password));
            output.flush();
            InputStream input=sock.getInputStream();
            int packetType=input.read(), remaining=input.read();
            if(packetType!=0x20 || remaining<2 || remaining>4)
                return new Result("Esito: MQTT CONNACK NON VALIDO\n");
            byte[] response=new byte[remaining];
            int count=0;
            while(count<remaining){
                int bytes=input.read(response,count,remaining-count);
                if(bytes<0)throw new EOFException();
                count+=bytes;
            }
            int result=response[1]&255;
            try{output.write(new byte[]{(byte)0xE0,0x00});output.flush();}catch(IOException ignored){}
            switch(result){
                case 0:return new Result("Connessione MQTT: ✓ autenticata\nSessione di segnalazione disponibile.\n");
                case 1:return new Result("Esito: VERSIONE PROTOCOLLO MQTT NON ACCETTATA\n");
                case 2:return new Result("Esito: IDENTIFICATIVO CLIENT MQTT NON ACCETTATO\n");
                case 3:return new Result("Esito: BROKER MQTT NON DISPONIBILE\n");
                case 4:return new Result("Esito: AUTENTICAZIONE MQTT RIFIUTATA (codice 4)\n");
                case 5:return new Result("Esito: MQTT NON AUTORIZZATO (codice 5)\n");
                default:return new Result("Esito: CONNACK MQTT codice "+result+"\n");
            }
        }
    }
}
