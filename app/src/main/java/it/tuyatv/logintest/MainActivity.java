package it.tuyatv.logintest;

import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.view.SurfaceView;
import android.widget.FrameLayout;
import android.util.Base64;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import java.util.Locale;
import java.util.List;
import java.util.Collections;
import java.util.concurrent.*;

/** TV-friendly test screen. The user enters credentials locally on their Android TV. */
public final class MainActivity extends Activity {
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private SecureCredentials saved;
    private EditText account,password,country,region;
    private CheckBox remember;
    private Button login,clear,probe,relay,refresh,mqtt,copyLog,liveStart,liveStop;
    private ImageView liveImage;
    private SurfaceView videoSurface;
    private final EncodedVideoDecoder videoDecoder=new EncodedVideoDecoder();
    private volatile boolean liveRunning=false;
    private String diagnosticCopyText=null;
    private Spinner cameraPicker;
    private List<TuyaClient.DeviceChoice> choices=Collections.emptyList();
    private volatile TuyaClient authenticated;
    private TextView status;
    private volatile boolean busy=false;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        saved=new SecureCredentials(this);
        makeScreen();
        if(saved.hasCredentials()){
            setStatus("Lettura delle credenziali cifrate da Android Keystore…");
            executor.execute(()->{
                try{
                    SecureCredentials.Data data=saved.load();
                    if(data!=null)runOnUiThread(()->{
                        account.setText(data.account);
                        password.setText(data.password);
                        country.setText(data.country);
                        region.setText(data.region);
                        remember.setChecked(true);
                        authenticate(data.account,data.password,data.country,data.region,true);
                    });
                }catch(Exception error){
                    saved.clear();
                    runOnUiThread(()->setStatus("Credenziali locali non recuperabili; ripeti il login."));
                }
            });
        }else{account.requestFocus();}
    }
    private int dp(int v){return (int)(v*getResources().getDisplayMetrics().density+0.5f);}
    private TextView text(String value,int size,int color){
        TextView t=new TextView(this);
        t.setText(value);t.setTextSize(size);t.setTextColor(color);
        t.setPadding(dp(4),dp(4),dp(4),dp(4));return t;
    }
    private EditText input(String hint,String initial,int type){
        EditText v=new EditText(this);
        v.setSingleLine(true);v.setTextColor(Color.WHITE);
        v.setHintTextColor(0xFF9FB3BF);v.setTextSize(18);
        v.setHint(hint);v.setInputType(type);v.setText(initial);
        v.setSelectAllOnFocus(true);return v;
    }
    private void makeScreen(){
        ScrollView outer=new ScrollView(this);
        outer.setFillViewport(true);
        outer.setBackgroundColor(0xFF101D26);
        LinearLayout root=new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(38),dp(20),dp(38),dp(20));
        outer.addView(root);
        setContentView(outer);
        TextView title=text("TUYA TV  ·  DIAGNOSTICA P2P",26,Color.WHITE);
        title.setTypeface(null,1);root.addView(title);
        root.addView(text("Tuya Smart · Diagnostica di una telecamera · Nessun server domestico",14,0xFFB8CDD8));

        LinearLayout fields=new LinearLayout(this);
        fields.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout left=new LinearLayout(this);left.setOrientation(LinearLayout.VERTICAL);
        LinearLayout right=new LinearLayout(this);right.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams half=new LinearLayout.LayoutParams(0,-2,1);
        half.setMargins(0,0,dp(22),0);fields.addView(left,half);
        fields.addView(right,new LinearLayout.LayoutParams(0,-2,1));
        root.addView(fields);

        left.addView(text("Email o numero dell'account Tuya",14,0xFFEAF3F6));
        account=input("Email / telefono","",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);left.addView(account);
        left.addView(text("Password",14,0xFFEAF3F6));
        password=input("Password","",InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);left.addView(password);

        right.addView(text("Prefisso paese (senza +)",14,0xFFEAF3F6));
        country=input("39","39",InputType.TYPE_CLASS_PHONE);right.addView(country);
        right.addView(text("Regione cloud (eu, us, in, cn, sg)",14,0xFFEAF3F6));
        region=input("eu","eu",InputType.TYPE_CLASS_TEXT);right.addView(region);

        remember=new CheckBox(this);
        remember.setText("Ricorda credenziali cifrate SOLO su questa stick e riprova automaticamente al prossimo avvio");
        remember.setTextSize(14);remember.setTextColor(Color.WHITE);remember.setChecked(true);
        root.addView(remember);
        LinearLayout buttons=new LinearLayout(this);buttons.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(buttons);
        login=new Button(this);login.setText("PROVA LOGIN");buttons.addView(login);
        clear=new Button(this);clear.setText("ELIMINA DATI");buttons.addView(clear);
        probe=new Button(this);probe.setText("CONFIG P2P");probe.setEnabled(false);buttons.addView(probe);

        LinearLayout choose=new LinearLayout(this);choose.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(choose);
        choose.addView(text("Telecamera",15,Color.WHITE));
        cameraPicker=new Spinner(this);
        cameraPicker.setMinimumHeight(dp(48));
        choose.addView(cameraPicker,new LinearLayout.LayoutParams(0,dp(50),1));
        refresh=new Button(this);refresh.setText("RICARICA");refresh.setEnabled(false);
        choose.addView(refresh);
        relay=new Button(this);relay.setText("TEST RELAY P2P");relay.setEnabled(false);
        choose.addView(relay);
        mqtt=new Button(this);mqtt.setText("TEST MQTT");mqtt.setEnabled(false);
        root.addView(mqtt);
        LinearLayout liveActions=new LinearLayout(this);
        root.addView(liveActions);
        liveStart=new Button(this);liveStart.setText("AVVIA VIDEO LIVE");liveStart.setEnabled(false);
        liveActions.addView(liveStart);
        liveStop=new Button(this);liveStop.setText("FERMA VIDEO");liveStop.setEnabled(false);
        liveActions.addView(liveStop);
        FrameLayout videoContainer=new FrameLayout(this);
        videoContainer.setBackgroundColor(Color.BLACK);
        videoSurface=new SurfaceView(this);
        videoContainer.addView(videoSurface,new FrameLayout.LayoutParams(-1,-1));
        liveImage=new ImageView(this);
        liveImage.setScaleType(ImageView.ScaleType.FIT_CENTER);
        liveImage.setVisibility(View.GONE);
        videoContainer.addView(liveImage,new FrameLayout.LayoutParams(-1,-1));
        root.addView(videoContainer,new LinearLayout.LayoutParams(-1,dp(270)));

        copyLog=new Button(this);copyLog.setText("COPIA LOG");copyLog.setEnabled(false);
        root.addView(copyLog);

        status=text("Pronto. Inserisci email e password Tuya Smart.",17,0xFFF0F7FB);
        status.setPadding(dp(16),dp(10),dp(16),dp(10));
        status.setBackgroundColor(0xFF1F3542);
        root.addView(status,new LinearLayout.LayoutParams(-1,-2));
        root.addView(text("Test NON ufficiale. Può fallire per modifiche delle API Tuya, MFA o CAPTCHA. Non condividere mai password o token su GitHub.",13,0xFF9FB3BF));

        login.setOnClickListener(v->authenticate(
            account.getText().toString().trim(),password.getText().toString(),
            country.getText().toString().trim().replace("+",""),
            region.getText().toString().trim().toLowerCase(Locale.ROOT),false));
        probe.setOnClickListener(v->probeCameras());
        refresh.setOnClickListener(v->loadDevices());
        relay.setOnClickListener(v->probeRelay());
        mqtt.setOnClickListener(v->probeMqtt());
        liveStart.setOnClickListener(v->startVideo());
        liveStop.setOnClickListener(v->stopVideo());
        copyLog.setOnClickListener(v->{
            if(diagnosticCopyText==null)return;
            ClipboardManager clipboard=(ClipboardManager)getSystemService(Context.CLIPBOARD_SERVICE);
            if(clipboard!=null){
                clipboard.setPrimaryClip(ClipData.newPlainText("Tuya TV log",diagnosticCopyText));
                Toast.makeText(this,"Log diagnostico copiato",Toast.LENGTH_SHORT).show();
            }
        });
        clear.setOnClickListener(v->{
            if(busy)return;
            stopVideo();
            authenticated=null;probe.setEnabled(false);mqtt.setEnabled(false);
            clearDeviceChoices();refresh.setEnabled(false);
            saved.clear();password.setText("");remember.setChecked(false);
            setStatus("Password salvata eliminata dal dispositivo.");
        });
    }
    private void setStatus(String msg){
        status.setText(msg);diagnosticCopyText=null;
        if(copyLog!=null)copyLog.setEnabled(false);
    }
    private void setDiagnosticStatus(String msg){
        status.setText(msg);
        diagnosticCopyText=sanitizeDiagnostic(msg);
        copyLog.setEnabled(true);
    }
    private static String sanitizeDiagnostic(String msg){
        return "Tuya TV Viewer diagnostica v0.7\n" + msg
            .replaceAll("(?m)^Dispositivo:.*$","Dispositivo: [omesso]")
            .replaceAll("(?m)^\\s*•.*$"," • [nome dispositivo omesso]")
            .replaceAll("(?i)(password|token|localkey|ecode|sid)\\s*[:=]\\s*\\S+","$1=[omesso]")
            .replaceAll("[a-zA-Z0-9]{28,}","[identificativo omesso]");
    }
    private void authenticate(String user,String pass,String cc,String reg,boolean auto){
        if(busy||liveRunning)return;
        if(user.isEmpty()||pass.isEmpty()||cc.isEmpty()||reg.isEmpty()){
            setStatus("Completa tutti i campi.");return;
        }
        if(!(reg.equals("eu")||reg.equals("us")||reg.equals("in")||reg.equals("cn")||reg.equals("sg"))){
            setStatus("Regione non valida, usa eu per l'Italia.");return;
        }
        final boolean shouldRemember=remember.isChecked();
        busy=true;authenticated=null;probe.setEnabled(false);mqtt.setEnabled(false);
        clearDeviceChoices();refresh.setEnabled(false);
        login.setEnabled(false);clear.setEnabled(false);
        setStatus((auto?"Login automatico":"Login manuale")+" in corso verso Tuya "+reg+"…");
        executor.execute(()->{
            String feedback;
            try{
                TuyaClient client=new TuyaClient(reg,saved.fingerprint());
                feedback=client.login(user,pass,cc).text;
                authenticated=client;
                if(shouldRemember){
                    try{saved.save(user,pass,cc,reg);}
                    catch(Exception e){feedback+="\nATTENZIONE: salvataggio locale non disponibile.";}
                }else saved.clear();
            }catch(Exception error){
                // Avoid repeated failed automatic attempts and risk of a locked account.
                saved.clear();
                feedback="LOGIN NON RIUSCITO\n"+TuyaClient.safeMessage(error).replace(pass,"[redatto]")
                    +"\n\nPossibile incompatibilità del protocollo: non significa necessariamente password sbagliata."
                    +"\nCredenziali salvate eliminate per sicurezza.";
            }
            final String message=feedback;
            runOnUiThread(()->{
                if(isFinishing()||isDestroyed())return;
                busy=false;login.setEnabled(true);clear.setEnabled(true);
                probe.setEnabled(authenticated!=null);
                refresh.setEnabled(authenticated!=null);
                mqtt.setEnabled(authenticated!=null);
                setStatus(message);
                if(authenticated!=null)loadDevices();
            });
        });
    }
    private void probeCameras(){
        if(busy || liveRunning || authenticated==null)return;
        busy=true;probe.setEnabled(false);login.setEnabled(false);clear.setEnabled(false);mqtt.setEnabled(false);
        setStatus("Verifica delle configurazioni video P2P in corso…\nNon vengono avviati flussi o salvati dati delle telecamere.");
        final TuyaClient client=authenticated;
        executor.execute(()->{
            String result;
            try{result=client.probeCameraConfigs().text;}
            catch(Exception e){result="TEST NON COMPLETATO\n"+TuyaClient.safeMessage(e)
                +"\n\nPuò dipendere dagli endpoint o dalla struttura dell'account, non necessariamente dalla telecamera.";}
            final String message=result;
            runOnUiThread(()->{
                if(isFinishing()||isDestroyed())return;
                busy=false;probe.setEnabled(authenticated!=null);
                mqtt.setEnabled(authenticated!=null);
                login.setEnabled(true);clear.setEnabled(true);setDiagnosticStatus(message);
            });
        });
    }

    private void clearDeviceChoices(){
        choices=Collections.emptyList();
        ArrayAdapter<TuyaClient.DeviceChoice> adapter=new ArrayAdapter<>(
            this,android.R.layout.simple_spinner_item,choices);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        cameraPicker.setAdapter(adapter);
        relay.setEnabled(false);
        liveStart.setEnabled(false);
    }

    private void loadDevices(){
        if(busy || liveRunning || authenticated==null)return;
        busy=true;refresh.setEnabled(false);relay.setEnabled(false);mqtt.setEnabled(false);
        login.setEnabled(false);clear.setEnabled(false);probe.setEnabled(false);
        setStatus("Caricamento dei dispositivi Tuya Smart…");
        final TuyaClient client=authenticated;
        executor.execute(()->{
            List<TuyaClient.DeviceChoice> devices=Collections.emptyList();
            String failure=null;
            try{devices=client.listDevicesForPreviewTest();}
            catch(Exception e){failure=TuyaClient.safeMessage(e);}
            final List<TuyaClient.DeviceChoice> list=devices;
            final String error=failure;
            runOnUiThread(()->{
                if(isFinishing()||isDestroyed())return;
                busy=false;login.setEnabled(true);clear.setEnabled(true);
                mqtt.setEnabled(authenticated!=null);
                refresh.setEnabled(authenticated!=null);probe.setEnabled(authenticated!=null);
                choices=list;
                ArrayAdapter<TuyaClient.DeviceChoice> adapter=new ArrayAdapter<>(
                    this,android.R.layout.simple_spinner_item,choices);
                adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
                cameraPicker.setAdapter(adapter);
                relay.setEnabled(authenticated!=null && !choices.isEmpty());
                liveStart.setEnabled(authenticated!=null && !choices.isEmpty());
                if(error==null){
                    setStatus("LOGIN RIUSCITO\nDispositivi trovati: "+choices.size()+
                        "\nSelezionane uno e premi TEST RELAY P2P."+
                        "\nIl test verifica la connessione di rete, non mostra ancora il video.");
                }else{
                    setStatus("LOGIN RIUSCITO\nElenco dispositivi non disponibile: "+error);
                }
            });
        });
    }

    private void probeRelay(){
        if(busy || liveRunning || authenticated==null || choices.isEmpty())return;
        Object selected=cameraPicker.getSelectedItem();
        if(!(selected instanceof TuyaClient.DeviceChoice)){
            setStatus("Seleziona una telecamera.");return;
        }
        final TuyaClient.DeviceChoice device=(TuyaClient.DeviceChoice)selected;
        final TuyaClient client=authenticated;
        busy=true;login.setEnabled(false);clear.setEnabled(false);
        probe.setEnabled(false);refresh.setEnabled(false);relay.setEnabled(false);mqtt.setEnabled(false);
        setStatus("Verifica relay P2P di "+device.name+"…\nNon vengono aperti flussi video.");
        executor.execute(()->{
            String message;
            try{message=client.probeOneCameraTransport(device).text;}
            catch(Exception e){message="TEST RELAY NON RIUSCITO\n"+TuyaClient.safeMessage(e)+
                "\nQuesto non prova che la telecamera sia incompatibile.";}
            final String output=message;
            runOnUiThread(()->{
                if(isFinishing()||isDestroyed())return;
                busy=false;login.setEnabled(true);clear.setEnabled(true);
                probe.setEnabled(authenticated!=null);refresh.setEnabled(authenticated!=null);
                relay.setEnabled(authenticated!=null && !choices.isEmpty());
                mqtt.setEnabled(authenticated!=null);
                setDiagnosticStatus(output);
            });
        });
    }


    private void probeMqtt(){
        if(busy || liveRunning || authenticated==null)return;
        final TuyaClient client=authenticated;
        busy=true;login.setEnabled(false);clear.setEnabled(false);
        probe.setEnabled(false);refresh.setEnabled(false);relay.setEnabled(false);mqtt.setEnabled(false);
        setStatus("Test MQTT: apertura canale di segnalazione cifrato…\n"
            +"Nessun comando video viene inviato.");
        executor.execute(()->{
            String result=client.testSignalingMqtt().text;
            runOnUiThread(()->{
                if(isFinishing()||isDestroyed())return;
                busy=false;login.setEnabled(true);clear.setEnabled(true);
                probe.setEnabled(authenticated!=null);refresh.setEnabled(authenticated!=null);
                relay.setEnabled(authenticated!=null&&!choices.isEmpty());
                mqtt.setEnabled(authenticated!=null);
                setDiagnosticStatus(result);
            });
        });
    }


    /** Receives a JPEG frame directly from Python's in-process P2P engine. */
    public final class VideoEvents {
        private long lastFrameAt=0;
        private final StringBuilder progress=new StringBuilder();
        public String fetchRtcJson(String cameraId) throws Exception {
            TuyaClient client=authenticated;
            if(client==null)throw new Exception("Sessione Tuya scaduta");
            return client.streamingRtcConfig(cameraId);
        }
        public synchronized void onStatus(String description){
            if(progress.length()>1500)progress.delete(0,Math.max(0,progress.length()-1000));
            progress.append("• ").append(description).append('\n');
            final String msg="STREAM VIDEO (sperimentale)\n"+progress.toString();
            runOnUiThread(()->{
                if(!isFinishing()&&!isDestroyed())
                    setDiagnosticStatus(msg);
            });
        }
        /** Receives AVC/HEVC Annex B in memory, never writes it to storage. */
        public void onEncodedFrame(String codec, String frameB64){
            if(!liveRunning)return;
            try{
                byte[] frame=Base64.decode(frameB64,Base64.DEFAULT);
                runOnUiThread(()->liveImage.setVisibility(View.GONE));
                videoDecoder.feed(videoSurface.getHolder().getSurface(),codec,frame);
            }catch(Exception ignored){}
        }
        public void onFrame(String jpegB64){
            try{
                long now=android.os.SystemClock.elapsedRealtime();
                if(now-lastFrameAt<200)return;
                lastFrameAt=now;
                byte[] bytes=Base64.decode(jpegB64,Base64.DEFAULT);
                Bitmap frame=BitmapFactory.decodeByteArray(bytes,0,bytes.length);
                if(frame!=null)runOnUiThread(()->{
                    if(!liveRunning||isFinishing()||isDestroyed()){frame.recycle();return;}
                    liveImage.setVisibility(View.VISIBLE);
                    liveImage.setImageBitmap(frame);
                });
            }catch(Exception ignored){}
        }
    }

    private void startVideo(){
        if(busy||liveRunning||authenticated==null)return;
        Object o=cameraPicker.getSelectedItem();
        if(!(o instanceof TuyaClient.DeviceChoice))return;
        TuyaClient.DeviceChoice camera=(TuyaClient.DeviceChoice)o;
        if(camera.localKey.isEmpty()){
            setDiagnosticStatus("VIDEO LIVE: la chiave locale della telecamera non è stata restituita da Tuya.");
            return;
        }
        liveRunning=true;liveStart.setEnabled(false);liveStop.setEnabled(true);
        videoDecoder.stop();
        liveImage.setImageDrawable(null);
        liveImage.setVisibility(View.GONE);
        setStatus("Apertura diretta P2P: "+camera.name+"…");
        TuyaClient client=authenticated;
        executor.execute(()->{
            try{
                if(!Python.isStarted())Python.start(new AndroidPlatform(getApplicationContext()));
                Python.getInstance().getModule("tuya_stream").callAttr("start",
                    client.streamingSid(),client.streamingEcode(),client.streamingUid(),
                    client.streamingRegion(),saved.fingerprint(),
                    camera.id,camera.localKey,client.streamingClientId(),
                    client.streamingComposite(),client.streamingChannelKey(),
                    new VideoEvents());
            }catch(Throwable e){
                runOnUiThread(()->setDiagnosticStatus(
                    "Streaming non avviato: "+e.getClass().getSimpleName()+
                    ". Verificare compatibilità del dispositivo con il motore Python."));
            }finally{
                runOnUiThread(()->{
                    liveRunning=false;liveStop.setEnabled(false);
                    liveStart.setEnabled(authenticated!=null&&!choices.isEmpty());
                });
            }
        });
    }
    private void stopVideo(){
        liveRunning=false;
        videoDecoder.stop();
        if(liveStop!=null)liveStop.setEnabled(false);
        if(liveStart!=null)liveStart.setEnabled(authenticated!=null&&!choices.isEmpty());
        if(Python.isStarted()){
            try{Python.getInstance().getModule("tuya_stream").callAttr("stop");}
            catch(Exception ignored){}
        }
    }

    @Override protected void onDestroy(){stopVideo();executor.shutdownNow();super.onDestroy();}
}
