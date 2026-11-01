package it.tuyatv.logintest;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

/** Experimental Tuya Smart mobile gateway API; does not use a private server.
 * Signing protocol and public Tuya app identity adapted from AboveColin/tuya-mobile (MIT).
 * NO USER credentials, tokens, device IDs or local keys are embedded in this class. */
final class TuyaClient {
    // Public, reverse-engineered Tuya Smart application identity, NOT the user's credentials.
    // These application-level identifiers have already been published in the MIT project cited above.
    private static final String PACKAGE="com.tuya.smart";
    private static final String CERT="93:21:9F:C2:73:E2:20:0F:4A:DE:E5:F7:19:1D:C6:56:BA:2A:2D:7B:2F:F5:D2:4C:D5:5C:4B:61:55:00:1E:40";
    private static final String APP_KEY="f3hd7pet4p83kemjdf5wqsa5tavrv579";
    private static final String APP_SECRET="5gdtanjtf38vyxkqh87cjwfcqjhvjjqa";
    private static final String CLIENT_ID="3cxxt3au9x33ytvq3h9j";
    private static final String COMPOSITE=PACKAGE+"_"+CERT+"_"+APP_KEY+"_"+APP_SECRET;
    private static final String APP_VERSION="7.8.6", SDK_VERSION="5.24.0", CORE_VERSION="5.17.0";
    private final String apiUrl, deviceId;
    private String sid, ecode;

    static final class Outcome { final String text; Outcome(String text){this.text=text;} }
    TuyaClient(String region,String installId){
        switch(region){
            case "eu":apiUrl="https://a1.tuyaeu.com/api.json";break;
            case "us":apiUrl="https://a1.tuyaus.com/api.json";break;
            case "in":apiUrl="https://a1.tuyain.com/api.json";break;
            case "cn":apiUrl="https://a1.tuyacn.com/api.json";break;
            case "sg":apiUrl="https://a1-sg.iotbing.com/api.json";break;
            default:throw new IllegalArgumentException("Regione non supportata");
        }
        deviceId=installId;
    }
    /** Do not call on the UI thread. No credentials are written to logs or files here. */
    Outcome login(String username,String password,String countryCode) throws Exception {
        boolean email=username.contains("@");
        String user=email?username:normalizeMobile(username,countryCode);
        JSONObject request=new JSONObject();
        request.put("countryCode",countryCode);
        request.put("username",user);
        request.put("isUid",false);
        JSONObject token=findObject(call("thing.m.user.username.token.get","2.0",request),"publicKey","exponent","token");
        String encrypted=TuyaCrypto.rsaMd5(token.getString("publicKey"),token.getString("exponent"),TuyaCrypto.md5(password));

        JSONObject auth=new JSONObject();
        auth.put("countryCode",countryCode);
        auth.put(email?"email":"mobile",user);
        auth.put("passwd",encrypted);
        auth.put("ifencrypt",1);
        auth.put("options","{\"group\":1,\"mfaCode\":\"\"}");
        auth.put("token",token.getString("token"));
        JSONObject response=findObject(call(email?"thing.m.user.email.password.login":"thing.m.user.mobile.passwd.login",email?"3.0":"4.0",auth),"sid","ecode");
        sid=response.getString("sid");
        ecode=response.getString("ecode");
        // Login is considered successful even when the optional device listing is unavailable.
        StringBuilder msg=new StringBuilder("LOGIN RIUSCITO ✓\nSessione Tuya Smart ricevuta.\n");
        try {
            JSONObject houses=call("m.life.home.space.list","1.0",new JSONObject());
            JSONArray homes=new JSONArray();
            findItems(houses,"gid",homes);
            Set<String> gids=new HashSet<>(),deviceIds=new HashSet<>();
            int nHomes=0;
            for(int i=0;i<homes.length();i++){
                JSONObject home=homes.getJSONObject(i);
                String gid=home.optString("gid","");
                if(gid.isEmpty() || !gids.add(gid))continue;
                nHomes++;
                JSONObject params=new JSONObject();
                params.put("gid",home.opt("gid"));
                JSONObject list=call("m.life.my.group.device.list","2.2",params);
                JSONArray devices=new JSONArray();
                findItems(list,"devId",devices);
                for(int j=0;j<devices.length();j++){
                    JSONObject device=devices.getJSONObject(j);
                    String id=device.optString("devId","");
                    if(id.isEmpty() || !deviceIds.add(id))continue;
                    if(deviceIds.size()<=20)msg.append(" • ")
                        .append(device.optString("name","Dispositivo"))
                        .append(device.optBoolean("isOnline",true)?" [online]":" [offline]")
                        .append('\n');
                }
            }
            msg.insert("LOGIN RIUSCITO ✓\nSessione Tuya Smart ricevuta.\n".length(),
                "Abitazioni: "+nHomes+" | Dispositivi: "+deviceIds.size()+"\n\n");
        }catch(Exception ex){
            msg.append("\nElenco dispositivi non disponibile: ").append(safeMessage(ex));
        }
        return new Outcome(msg.toString());
    }

    /**
     * Safe, read-only IPC configuration probe. It does NOT open a streaming session.
     * No session tokens, local keys, identifiers or network addresses are shown
     * or written to a log. Call only after an explicit button click.
     */
    Outcome probeCameraConfigs() throws Exception {
        if(sid == null || ecode == null) throw new Exception("Esegui prima il login.");
        List<JSONObject> devices = discoverDeviceRecords();
        if(devices.isEmpty()) return new Outcome("Nessun dispositivo trovato. Controlla l'elenco del login.");

        StringBuilder out=new StringBuilder();
        out.append("TEST CONFIGURAZIONE VIDEO P2P\n");
        out.append("Dispositivi rilevati: ").append(devices.size()).append('\n');
        out.append("Non è ancora una prova di riproduzione video.\n\n");
        int checked=0,ready=0;
        for(JSONObject device:devices){
            if(checked >= 12){out.append("Altri dispositivi non verificati.\n");break;}
            checked++;
            String label=device.optString("name","Dispositivo "+checked);
            if(label.length()>70)label=label.substring(0,70)+"…";
            String id=device.optString("devId","");
            if(id.isEmpty())continue;
            try{
                JSONObject query=new JSONObject();query.put("devId",id);
                JSONObject result=call("m.ipc.v4.rtc.config.get","1.0",query);
                // Do not display, store or export secrets returned by the gateway.
                if(hasNestedKey(result,"sessionId") || hasNestedKey(result,"motoId") ||
                    hasNestedKey(result,"p2pConfig")){
                    out.append("✓ ").append(label).append(": config P2P disponibile\n");
                    ready++;
                }else{
                    out.append("? ").append(label).append(": risposta senza config P2P riconosciuta\n");
                }
            }catch(Exception e){
                // Only show a short protocol category; never include the response body.
                String type=safeMessage(e);
                out.append("– ").append(label).append(": ").append(type).append('\n');
            }
        }
        out.append("\nConfig P2P ottenute: ").append(ready).append("/").append(checked);
        out.append("\nNessun flusso video avviato. I risultati rimangono solo sullo schermo.");
        return new Outcome(out.toString());
    }

    private List<JSONObject> discoverDeviceRecords() throws Exception {
        JSONObject houses;
        try{houses=call("m.life.home.space.list","1.0",new JSONObject());}
        catch(Exception ignored){houses=call("tuya.m.location.list","2.1",new JSONObject());}
        JSONArray homes=new JSONArray();
        findItems(houses,"gid",homes);
        Set<String> seenHomes=new HashSet<>();
        Map<String,JSONObject> records=new LinkedHashMap<>();
        for(int i=0;i<homes.length();i++){
            JSONObject home=homes.getJSONObject(i);
            String gid=home.optString("gid","");
            if(gid.isEmpty() || !seenHomes.add(gid))continue;
            JSONObject params=new JSONObject();params.put("gid",home.opt("gid"));
            JSONObject list;
            try{list=call("m.life.my.group.device.list","2.2",params);}
            catch(Exception ignored){list=call("tuya.m.my.group.device.list","1.0",params);}
            JSONArray devices=new JSONArray();
            findItems(list,"devId",devices);
            for(int j=0;j<devices.length();j++){
                JSONObject rec=devices.getJSONObject(j);
                String id=rec.optString("devId","");
                if(!id.isEmpty() && !records.containsKey(id)) records.put(id,rec);
            }
        }
        return new ArrayList<>(records.values());
    }
    private static boolean hasNestedKey(Object data,String key){
        if(data instanceof JSONObject){
            JSONObject obj=(JSONObject)data;
            if(obj.has(key)&&!obj.isNull(key))return true;
            JSONArray names=obj.names();
            if(names!=null)for(int i=0;i<names.length();i++){
                Object child=obj.opt(names.optString(i));
                if((child instanceof JSONObject || child instanceof JSONArray) &&
                    hasNestedKey(child,key))return true;
            }
        }else if(data instanceof JSONArray){
            JSONArray a=(JSONArray)data;
            for(int i=0;i<a.length();i++){
                Object child=a.opt(i);
                if((child instanceof JSONObject || child instanceof JSONArray) &&
                    hasNestedKey(child,key))return true;
            }
        }
        return false;
    }

    private static String normalizeMobile(String raw,String country) throws Exception {
        String p=raw.trim().replaceAll("[\\s\\-()]","");
        String prefix=country.replace("+","");
        if(p.startsWith("+")){p=p.substring(1);if(p.startsWith(prefix))p=p.substring(prefix.length());}
        else if(p.startsWith("00"+prefix))p=p.substring(prefix.length()+2);
        if(p.startsWith("0") && p.length()>1)p=p.substring(1);
        if(!p.matches("[0-9]+"))throw new Exception("Numero telefonico non valido");
        return p;
    }
    private static void findItems(Object value,String field,JSONArray into){
        if(value instanceof JSONObject){
            JSONObject ob=(JSONObject)value;
            if(ob.has(field))into.put(ob);
            JSONArray names=ob.names();
            if(names!=null)for(int i=0;i<names.length();i++) {
                Object child=ob.opt(names.optString(i));
                if(child instanceof JSONObject || child instanceof JSONArray)findItems(child,field,into);
            }
        } else if(value instanceof JSONArray){
            JSONArray array=(JSONArray)value;
            for(int i=0;i<array.length();i++)findItems(array.opt(i),field,into);
        }
    }
    private static JSONObject findObject(JSONObject data,String... fields) throws Exception {
        JSONArray found=new JSONArray();
        findItems(data,fields[0],found);
        for(int i=0;i<found.length();i++){
            JSONObject ob=found.getJSONObject(i);boolean valid=true;
            for(String f:fields)if(!ob.has(f)||ob.isNull(f)){valid=false;break;}
            if(valid)return ob;
        }
        throw new Exception("Risposta Tuya senza dati richiesti ("+fields[0]+")");
    }

    private JSONObject call(String action,String version,JSONObject body) throws Exception {
        String requestId=UUID.randomUUID().toString();
        String aesKey=TuyaCrypto.bodyKey(requestId,COMPOSITE,ecode);
        String encrypted=TuyaCrypto.encryptBody(aesKey,body.toString());
        LinkedHashMap<String,String> form=new LinkedHashMap<>();
        form.put("a",action);form.put("v",version);form.put("clientId",CLIENT_ID);
        form.put("os","Android");form.put("appVersion",APP_VERSION);
        form.put("channel","sdk");form.put("osSystem","15");
        form.put("sdkVersion",SDK_VERSION);form.put("deviceCoreVersion",CORE_VERSION);
        form.put("platform","y");form.put("timeZoneId","Europe/Rome");
        form.put("cp","gzip");form.put("nd","1");form.put("lang","en");
        form.put("ttid","international");form.put("et","3");
        form.put("chKey",TuyaCrypto.hmac(CLIENT_ID,PACKAGE+"_"+CERT).substring(8,16));
        form.put("deviceId",deviceId);form.put("time",String.valueOf(System.currentTimeMillis()/1000));
        form.put("requestId",requestId);form.put("postData",encrypted);
        form.put("appRnVersion","5.84");
        if(sid!=null)form.put("sid",sid);
        LinkedHashMap<String,String> signatureParams=new LinkedHashMap<>(form);
        signatureParams.put("postData",TuyaCrypto.signedData(encrypted));
        form.put("sign",TuyaCrypto.signModern(signatureParams,COMPOSITE));
        HttpURLConnection connection=null;
        try{
            connection=(HttpURLConnection)new URL(apiUrl).openConnection();
            connection.setConnectTimeout(16000);connection.setReadTimeout(22000);
            connection.setRequestMethod("POST");connection.setDoOutput(true);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Content-Type","application/x-www-form-urlencoded; charset=UTF-8");
            connection.setRequestProperty("User-Agent","Thing-UA=APP/Android/"+APP_VERSION+"/SDK/"+SDK_VERSION);
            StringBuilder post=new StringBuilder();
            for(Map.Entry<String,String> e:form.entrySet()){
                if(post.length()>0)post.append('&');
                post.append(URLEncoder.encode(e.getKey(),"UTF-8"))
                    .append('=').append(URLEncoder.encode(e.getValue(),"UTF-8"));
            }
            byte[] bytes=post.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bytes.length);
            try(OutputStream out=connection.getOutputStream()){out.write(bytes);}
            int http=connection.getResponseCode();
            if(http!=200)throw new Exception("HTTP "+http+" ("+action+")");
            String raw;
            try(InputStream in=connection.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] b=new byte[4096];int n;
                while((n=in.read(b))!=-1){
                    out.write(b,0,n);
                    if(out.size()>2000000)throw new Exception("Risposta Tuya troppo grande");
                }
                raw=out.toString("UTF-8");
            }
            JSONObject envelope=new JSONObject(raw);
            Object payload=envelope.opt("result");
            if(!(payload instanceof String))
                throw new Exception("Tuya "+envelope.optString("errorCode","errore"));
            JSONObject result=new JSONObject(TuyaCrypto.decryptBody(aesKey,(String)payload));
            if(result.optBoolean("success",true)==false || !result.optString("errorCode","").isEmpty())
                throw new Exception("Tuya "+result.optString("errorCode","errore"));
            return result;
        }finally{if(connection!=null)connection.disconnect();}
    }

    static String safeMessage(Throwable t){
        String s=t.getMessage();
        if(s==null||s.isEmpty())s=t.getClass().getSimpleName();
        return s.length()>180?s.substring(0,180):s;
    }
}
