package it.tuyatv.logintest;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import java.util.Locale;
import java.util.concurrent.*;

/** TV-friendly test screen. The user enters credentials locally on their Android TV. */
public final class MainActivity extends Activity {
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private SecureCredentials saved;
    private EditText account,password,country,region;
    private CheckBox remember;
    private Button login,clear;
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
        TextView title=text("TUYA TV  ·  LOGIN TEST",26,Color.WHITE);
        title.setTypeface(null,1);root.addView(title);
        root.addView(text("Prova sperimentale su Tuya Smart (non Smart Life) · Nessun server domestico",14,0xFFB8CDD8));

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

        status=text("Pronto. Inserisci email e password Tuya Smart.",17,0xFFF0F7FB);
        status.setPadding(dp(16),dp(10),dp(16),dp(10));
        status.setBackgroundColor(0xFF1F3542);
        root.addView(status,new LinearLayout.LayoutParams(-1,-2));
        root.addView(text("Test NON ufficiale. Può fallire per modifiche delle API Tuya, MFA o CAPTCHA. Non condividere mai password o token su GitHub.",13,0xFF9FB3BF));

        login.setOnClickListener(v->authenticate(
            account.getText().toString().trim(),password.getText().toString(),
            country.getText().toString().trim().replace("+",""),
            region.getText().toString().trim().toLowerCase(Locale.ROOT),false));
        clear.setOnClickListener(v->{
            if(busy)return;
            saved.clear();password.setText("");remember.setChecked(false);
            setStatus("Password salvata eliminata dal dispositivo.");
        });
    }
    private void setStatus(String msg){status.setText(msg);}
    private void authenticate(String user,String pass,String cc,String reg,boolean auto){
        if(busy)return;
        if(user.isEmpty()||pass.isEmpty()||cc.isEmpty()||reg.isEmpty()){
            setStatus("Completa tutti i campi.");return;
        }
        if(!(reg.equals("eu")||reg.equals("us")||reg.equals("in")||reg.equals("cn")||reg.equals("sg"))){
            setStatus("Regione non valida, usa eu per l'Italia.");return;
        }
        final boolean shouldRemember=remember.isChecked();
        busy=true;login.setEnabled(false);clear.setEnabled(false);
        setStatus((auto?"Login automatico":"Login manuale")+" in corso verso Tuya "+reg+"…");
        executor.execute(()->{
            String feedback;
            try{
                TuyaClient client=new TuyaClient(reg,saved.fingerprint());
                feedback=client.login(user,pass,cc).text;
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
                busy=false;login.setEnabled(true);clear.setEnabled(true);setStatus(message);
            });
        });
    }
    @Override protected void onDestroy(){executor.shutdownNow();super.onDestroy();}
}
