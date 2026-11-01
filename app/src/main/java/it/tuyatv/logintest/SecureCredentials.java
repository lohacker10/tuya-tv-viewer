package it.tuyatv.logintest;

import android.content.*;
import android.security.keystore.*;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Passwords remain only on the TV, encrypted with a non-exportable Android Keystore key. */
final class SecureCredentials {
    private static final String ALIAS="tuya_viewer_aes_v1";
    private final SharedPreferences prefs;
    static final class Data {
        final String account,password,country,region;
        Data(String a,String p,String c,String r){account=a;password=p;country=c;region=r;}
    }
    SecureCredentials(Context context){
        prefs=context.getSharedPreferences("tuya_viewer_private",Context.MODE_PRIVATE);
    }
    String fingerprint(){
        String id=prefs.getString("install_id","");
        if(!id.isEmpty())return id;
        byte[] b=new byte[22];TuyaCrypto.RAND.nextBytes(b);id=TuyaCrypto.hex(b);
        prefs.edit().putString("install_id",id).apply();
        return id;
    }
    void clear(){prefs.edit().remove("secret").apply();}
    boolean hasCredentials(){return prefs.contains("secret");}
    private static SecretKey key() throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        KeyStore.Entry current=ks.getEntry(ALIAS,null);
        if(current instanceof KeyStore.SecretKeyEntry)return ((KeyStore.SecretKeyEntry)current).getSecretKey();
        KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        gen.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).build());
        return gen.generateKey();
    }
    void save(String account,String pass,String country,String region) throws Exception {
        JSONObject obj=new JSONObject();
        obj.put("account",account);obj.put("password",pass);
        obj.put("country",country);obj.put("region",region);
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE,key());
        byte[] iv=c.getIV(),payload=c.doFinal(obj.toString().getBytes(StandardCharsets.UTF_8));
        byte[] full=Arrays.copyOf(iv,iv.length+payload.length);
        System.arraycopy(payload,0,full,iv.length,payload.length);
        prefs.edit().putString("secret",Base64.encodeToString(full,Base64.NO_WRAP)).apply();
    }
    Data load() throws Exception {
        String value=prefs.getString("secret",null);if(value==null)return null;
        byte[] b=Base64.decode(value,Base64.DEFAULT);
        if(b.length<29)throw new Exception("Dati locali non validi");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Arrays.copyOfRange(b,0,12)));
        JSONObject obj=new JSONObject(new String(c.doFinal(b,12,b.length-12),StandardCharsets.UTF_8));
        return new Data(obj.getString("account"),obj.getString("password"),
            obj.getString("country"),obj.getString("region"));
    }
}
