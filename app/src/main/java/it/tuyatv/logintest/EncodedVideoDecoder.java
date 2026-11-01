package it.tuyatv.logintest;

import android.media.MediaCodec;
import android.media.MediaFormat;
import android.view.Surface;
import java.nio.ByteBuffer;

/**
 * On-device Android hardware AVC/HEVC decoder.
 * Input is in-memory Annex B access units from the Tuya P2P transport.
 * No video content, network endpoint, device ID or key is logged or persisted.
 */
final class EncodedVideoDecoder {
    private MediaCodec decoder;
    private String currentType;
    private long frameCount;

    synchronized boolean feed(Surface surface, String codecType, byte[] accessUnit) {
        if (surface == null || !surface.isValid() || accessUnit == null ||
            accessUnit.length == 0 || accessUnit.length > 2_000_000) return false;
        try {
            if(decoder==null || !codecType.equals(currentType)) {
                stop();
                String mime = "hevc".equals(codecType) ? "video/hevc" : "video/avc";
                MediaFormat format=MediaFormat.createVideoFormat(mime,1920,1080);
                decoder=MediaCodec.createDecoderByType(mime);
                decoder.configure(format,surface,null,0);
                decoder.start();
                currentType=codecType;
                frameCount=0;
            }
            int input=decoder.dequeueInputBuffer(10000);
            if(input<0)return false;
            ByteBuffer buffer=decoder.getInputBuffer(input);
            if(buffer==null||accessUnit.length>buffer.capacity())return false;
            buffer.clear();
            buffer.put(accessUnit);
            long pts=(System.nanoTime()/1000L);
            decoder.queueInputBuffer(input,0,accessUnit.length,pts,0);
            MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
            for(int i=0;i<8;i++){
                int output=decoder.dequeueOutputBuffer(info,0);
                if(output>=0){
                    decoder.releaseOutputBuffer(output,true);
                    frameCount++;
                } else if(output==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED){
                    // The decoder reports the true dimensions when available.
                } else break;
            }
            return true;
        }catch(Exception e) {
            stop();
            return false;
        }
    }

    synchronized void stop(){
        if(decoder!=null){
            try{decoder.stop();}catch(Exception ignored){}
            try{decoder.release();}catch(Exception ignored){}
        }
        decoder=null;
        currentType=null;
        frameCount=0;
    }
}
