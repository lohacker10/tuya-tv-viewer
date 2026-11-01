package it.tuyatv.logintest;

import android.util.Base64;
import java.io.*;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.RSAPublicKeySpec;
import java.util.*;
import java.util.zip.GZIPInputStream;
import javax.crypto.*;
import javax.crypto.spec.*;

/** Tuya mobile crypto implementation. Based on AboveColin/tuya-mobile (MIT). */
final class TuyaCrypto {
    private TuyaCrypto() {}
    static final SecureRandom RAND = new SecureRandom();
    private static final Set<String> SIGN_FIELDS = new HashSet<>(Arrays.asList(
        "a","v","lat","lon","lang","deviceId","appVersion","ttid","isH5",
        "h5Token","os","clientId","postData","time","requestId","et",
        "n4h5","sid","chKey","sp"));

    static String hex(byte[] b) {
        char[] tab = "0123456789abcdef".toCharArray(), out = new char[b.length * 2];
        for(int i=0;i<b.length;i++){out[i*2]=tab[(b[i]>>4)&15];out[i*2+1]=tab[b[i]&15];}
        return new String(out);
    }
    static String md5(String value) throws Exception {
        return hex(MessageDigest.getInstance("MD5").digest(value.getBytes(StandardCharsets.UTF_8)));
    }
    static String hmac(String key, String message) throws Exception {
        Mac m=Mac.getInstance("HmacSHA256");
        m.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        return hex(m.doFinal(message.getBytes(StandardCharsets.UTF_8)));
    }
    static String bodyKey(String requestId, String composite, String ecode) throws Exception {
        return hmac(requestId, ecode == null ? composite : composite + "_" + ecode).substring(0,16);
    }
    static String encryptBody(String key, String plaintext) throws Exception {
        byte[] nonce=new byte[12]; RAND.nextBytes(nonce);
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8),"AES"),new GCMParameterSpec(128,nonce));
        byte[] encrypted=c.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
        byte[] full=Arrays.copyOf(nonce,nonce.length+encrypted.length);
        System.arraycopy(encrypted,0,full,nonce.length,encrypted.length);
        return Base64.encodeToString(full,Base64.NO_WRAP);
    }
    static String decryptBody(String key, String value) throws Exception {
        byte[] blob=Base64.decode(value,Base64.DEFAULT);
        if(blob.length<29) throw new Exception("Risposta cifrata troppo corta");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8),"AES"),new GCMParameterSpec(128,Arrays.copyOfRange(blob,0,12)));
        byte[] data=c.doFinal(blob,12,blob.length-12);
        if(data.length>=2 && (data[0]&255)==31 && (data[1]&255)==139){
            try(GZIPInputStream zip=new GZIPInputStream(new ByteArrayInputStream(data));
                ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] buf=new byte[4096];int n;
                while((n=zip.read(buf))!=-1){out.write(buf,0,n);if(out.size()>2000000)throw new Exception("Risposta troppo grande");}
                data=out.toByteArray();
            }
        }
        return new String(data,StandardCharsets.UTF_8);
    }
    static String signedData(String encrypted) throws Exception {
        String h=md5(encrypted);
        return h.substring(8,16)+h.substring(0,8)+h.substring(24,32)+h.substring(16,24);
    }
    static String signModern(Map<String,String> values, String composite) throws Exception {
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(composite.getBytes(StandardCharsets.UTF_8));
        Mac mac=Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(hash,"HmacSHA256"));
        StringBuilder canonical=new StringBuilder();
        for(Map.Entry<String,String> e:new TreeMap<>(values).entrySet()){
            if(!SIGN_FIELDS.contains(e.getKey()) || e.getValue()==null || e.getValue().isEmpty())continue;
            if(canonical.length()>0)canonical.append("||");
            canonical.append(e.getKey()).append('=').append(e.getValue());
        }
        return hex(mac.doFinal(canonical.toString().getBytes(StandardCharsets.UTF_8)));
    }
    static String rsaMd5(String modulus, String exponent, String passwordHash) throws Exception {
        PublicKey key=KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(new BigInteger(modulus),new BigInteger(exponent)));
        Cipher cipher=Cipher.getInstance("RSA/ECB/PKCS1Padding");
        cipher.init(Cipher.ENCRYPT_MODE,key);
        return hex(cipher.doFinal(passwordHash.getBytes(StandardCharsets.UTF_8)));
    }
}
