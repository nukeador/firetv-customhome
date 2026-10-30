package com.gathin.tvhome;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.drawable.GradientDrawable;
import android.util.Base64;
import android.view.Gravity;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;

/** Explicit device-code login; no password collection, automatic polling or token display. */
public final class StremioAccountActivity extends Activity {
    private TextView message,codeView;
    private ImageView qr;
    private String code="";
    private boolean busy;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout outer=new LinearLayout(this);outer.setOrientation(LinearLayout.HORIZONTAL);outer.setGravity(Gravity.CENTER);
        outer.setPadding(dp(36),dp(22),dp(36),dp(22));outer.setBackgroundColor(Color.BLACK);setContentView(outer);
        qr=new ImageView(this);LinearLayout.LayoutParams art=new LinearLayout.LayoutParams(dp(230),dp(230));art.setMargins(0,0,dp(32),0);outer.addView(qr,art);
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setGravity(Gravity.CENTER);
        outer.addView(root,new LinearLayout.LayoutParams(dp(500),LinearLayout.LayoutParams.WRAP_CONTENT));
        TextView title=text("Tu biblioteca, en Inicio",26);root.addView(title);
        message=text("Conecta tu cuenta directamente con Stremio.\nSolo leeremos tu biblioteca; no cambiaremos tus contenidos.",14);root.addView(message);
        codeView=text("",16);root.addView(codeView);
        Button check=button(root,"Ya he autorizado · comprobar conexión");check.setOnClickListener(v->check());
        Button link=button(root,"Generar un código nuevo");link.setOnClickListener(v->create());
        Button disconnect=button(root,"Desconectar esta pantalla de Stremio");disconnect.setOnClickListener(v->{StremioStore.disconnect(this);message.setText("Cuenta desconectada del launcher. Stremio conserva su sesión.");});
        button(root,"Volver a Inicio").setOnClickListener(v->finish());
        if(StremioStore.connected(this)) {message.setText("Stremio está conectado. La biblioteca se actualiza al volver a Inicio.\nPuedes desconectar únicamente este launcher.");qr.setVisibility(android.view.View.GONE);codeView.setVisibility(android.view.View.GONE);check.setText("Actualizar biblioteca y volver");check.setOnClickListener(v->{StremioStore.refresh(this,()->{});finish();});}
        else create();
    }
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private TextView text(String s,int size){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(Color.WHITE);t.setGravity(Gravity.CENTER);t.setPadding(6,4,6,4);return t;}
    private Button button(LinearLayout root,String label){Button b=new Button(this);b.setText(label);b.setTextSize(13);root.addView(b,new LinearLayout.LayoutParams(dp(480),dp(46)));return b;}
    private void create(){
        if(busy)return;busy=true;message.setText("Preparando la vinculación oficial de Stremio…");
        StremioStore.IO.execute(()->{
            try {
                JSONObject r=StremioStore.createLink();String c=r.getString("code"),link=r.getString("link"),image=r.optString("qrcode");
                Bitmap bitmap=null;
                try{byte[] bytes=image.startsWith("data:")?Base64.decode(image.substring(image.indexOf(',')+1),Base64.DEFAULT):StremioStore.getBytes(image,512*1024);bitmap=BitmapFactory.decodeByteArray(bytes,0,bytes.length);}catch(Exception ignored){}
                Bitmap shown=bitmap;
                runOnUiThread(()->{if(isFinishing())return;code=c;codeView.setText(link+"\nCódigo: "+c);qr.setImageBitmap(shown);message.setText("Escanea el QR o abre la dirección con tu móvil.\nAutoriza en Stremio y pulsa «Ya he autorizado». Tu contraseña no pasa por este launcher.");busy=false;});
            }catch(Exception e){runOnUiThread(()->{message.setText("No se pudo generar el código. Comprueba la conexión y vuelve a intentarlo.");busy=false;});}
        });
    }
    private void check(){
        if(busy||code.isEmpty())return;busy=true;message.setText("Comprobando tu autorización…");
        StremioStore.IO.execute(()->{
            try {
                String token=StremioStore.readLink(code);if(token.isEmpty())throw new Exception("Pending");
                StremioStore.saveSession(this,token);
                StremioStore.writeCache(this, StremioStore.library(this));
                runOnUiThread(()->{busy=false;finish();});
            }catch(Exception e){runOnUiThread(()->{message.setText("La autorización aún no está disponible. Confirma el enlace en tu móvil y vuelve a comprobar.");busy=false;});}
        });
    }
}
