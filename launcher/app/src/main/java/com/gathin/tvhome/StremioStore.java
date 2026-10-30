package com.gathin.tvhome;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.drawable.BitmapDrawable;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Read-only library client. No service, periodic refresh, account logging or library writes. */
final class StremioStore {
    static final ExecutorService IO = Executors.newSingleThreadExecutor();
    private static Handler ui() { return new Handler(Looper.getMainLooper()); }
    private static final String KEY = "tvhome.stremio.session";
    private static volatile long lastRefresh;
    private static volatile boolean loading;
    static final class Media {
        String id, type, title, poster, caption, section, videoId;
        int newEpisodes;
        boolean inProgress;
        double progress;
        long rank;
        Uri uri() { return Uri.parse("stremio:///detail/" + Uri.encode(type) + "/" + Uri.encode(id)
                + (videoId == null || videoId.isEmpty() ? "" : "/" + Uri.encode(videoId) + "?autoPlay=true")); }
    }
    private static File cache(Context c) { return new File(c.getFilesDir(), "stremio-library.json"); }
    static boolean connected(Context c) { return c.getSharedPreferences("stremio-private",0).contains("session"); }
    private static SecretKey secret() throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore"); ks.load(null);
        if (!ks.containsAlias(KEY)) {
            KeyGenerator g=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            g.init(new KeyGenParameterSpec.Builder(KEY,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            return g.generateKey();
        }
        return (SecretKey)ks.getKey(KEY,null);
    }
    static void saveSession(Context c,String token) throws Exception {
        if(token==null||token.length()<8||token.length()>4096)throw new Exception("Invalid session");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,secret());
        String value=Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP)+":"+
                Base64.encodeToString(cipher.doFinal(token.getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);
        if(!c.getSharedPreferences("stremio-private",0).edit().putString("session",value).commit())throw new Exception("Storage unavailable");
        lastRefresh=0;
    }
    private static String session(Context c) throws Exception {
        String[] value=c.getSharedPreferences("stremio-private",0).getString("session","").split(":",2);
        if(value.length!=2)throw new Exception("Not connected");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,secret(),new GCMParameterSpec(128,Base64.decode(value[0],Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(value[1],Base64.NO_WRAP)),StandardCharsets.UTF_8);
    }
    static void disconnect(Context c) {
        c.getSharedPreferences("stremio-private",0).edit().clear().commit();
        File f=cache(c);if(f.exists())f.delete();
        File notifications=notificationsFile(c);if(notifications.exists())notifications.delete();
        File[] posters=new File(c.getCacheDir(),"stremio-art").listFiles();
        if(posters!=null)for(File p:posters)p.delete();
        lastRefresh=0;
    }
    static URL httpsRedirect(URL current,String location) throws Exception {
        URL next=new URL(current,location);
        if(!next.getProtocol().equals("https")||next.getHost().isEmpty()||next.getUserInfo()!=null)
            throw new Exception("Invalid HTTPS URL");
        return next;
    }
    static byte[] getBytes(String address,int limit) throws Exception {
        URL url=httpsRedirect(new URL(address),address);
        // Episode thumbnails redirect to an image CDN. Follow bounded HTTPS-only redirects,
        // never the authenticated POST requests used for the Stremio account.
        for(int redirects=0;redirects<=4;redirects++) {
            HttpURLConnection con=(HttpURLConnection)url.openConnection();
            con.setConnectTimeout(12000);con.setReadTimeout(15000);con.setInstanceFollowRedirects(false);
            con.setRequestProperty("User-Agent","Stremio/1.6.0 TVHome/1.0");
            try {
                int status=con.getResponseCode();
                if(status==200)return read(con.getInputStream(),limit);
                if((status==301||status==302||status==303||status==307||status==308)&&redirects<4) {
                    String location=con.getHeaderField("Location");
                    if(location==null||location.isEmpty())throw new Exception("Missing image redirect");
                    url=httpsRedirect(url,location);continue;
                }
                throw new Exception("HTTP "+status);
            }finally{con.disconnect();}
        }
        throw new Exception("Too many HTTPS redirects");
    }
    private static byte[] read(InputStream stream,int limit) throws Exception {
        try(InputStream in=stream;ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] b=new byte[8192];int n;
            while((n=in.read(b))!=-1){if(out.size()+n>limit)throw new Exception("Response too large");out.write(b,0,n);}
            return out.toByteArray();
        }
    }
    static JSONObject result(JSONObject raw) throws Exception {
        if(raw.has("error")&&!raw.isNull("error"))throw new Exception("Stremio request rejected");
        return raw.optJSONObject("result")!=null?raw.getJSONObject("result"):raw;
    }
    static JSONObject createLink() throws Exception {
        return result(new JSONObject(new String(getBytes("https://link.stremio.com/api/v2/create?type=Create",262144),StandardCharsets.UTF_8)));
    }
    static String readLink(String code) throws Exception {
        JSONObject r=result(new JSONObject(new String(getBytes("https://link.stremio.com/api/v2/read?type=Read&code="+Uri.encode(code),262144),StandardCharsets.UTF_8)));
        return r.optString("authKey","");
    }
    static JSONArray library(Context c) throws Exception {
        JSONObject body=new JSONObject().put("authKey",session(c)).put("collection","libraryItem")
                .put("all",true).put("ids",new JSONArray());
        HttpURLConnection con=(HttpURLConnection)new URL("https://api.strem.io/api/datastoreGet").openConnection();
        con.setConnectTimeout(12000);con.setReadTimeout(15000);con.setInstanceFollowRedirects(false);
        con.setRequestMethod("POST");con.setDoOutput(true);
        con.setRequestProperty("Content-Type","application/json");
        con.setRequestProperty("User-Agent","Stremio/1.6.0 TVHome/1.0");
        try {
            byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);
            try(java.io.OutputStream out=con.getOutputStream()){out.write(bytes);}
            int status=con.getResponseCode();
            android.util.Log.i("TvHomeStremio", "library HTTP " + status);
            if(status!=200)throw new Exception("Library unavailable");
            JSONObject raw=new JSONObject(new String(read(con.getInputStream(),4*1024*1024),StandardCharsets.UTF_8));
            if(raw.has("error")&&!raw.isNull("error"))throw new Exception("Session rejected");
            JSONArray result=raw.optJSONArray("result");
            if(result==null)throw new Exception("Unexpected library format");
            android.util.Log.i("TvHomeStremio", "library rows=" + result.length() + " visible=" + parse(result).size());
            return result;
        } finally {con.disconnect();}
    }
    /** Matches stremio-core ContinueWatchingPreview: resume OR episode notifications; notification release / _mtime order. */
    static List<Media> parse(JSONArray array) { return parse(array, new JSONArray(), System.currentTimeMillis()); }
    static boolean pullsNotifications(JSONObject item) {
        JSONObject state=item.optJSONObject("state"), hints=item.optJSONObject("behaviorHints");
        String type=item.optString("type");
        return !item.optBoolean("removed") && !item.optBoolean("temp")
                && !type.equals("movie") && !type.equals("other")
                && (state==null || !state.optBoolean("noNotif",state.optBoolean("no_notif")))
                && (hints==null || (hints.optString("defaultVideoId", "").isEmpty() && !hints.optBoolean("isLive")));
    }
    static List<Media> parse(JSONArray array, JSONArray notificationMetas, long now) {
        return parse(array,notificationMetas,new JSONArray(),now);
    }
    static List<Media> parse(JSONArray array, JSONArray notificationMetas, JSONArray fullMetas, long now) {
        java.util.Map<String,JSONObject> complete=new java.util.HashMap<>();
        for(int i=0;i<fullMetas.length();i++){JSONObject m=fullMetas.optJSONObject(i);if(m!=null)complete.put(m.optString("id"),m);}
        List<Media> watching=new ArrayList<>();
        java.util.Map<String,JSONObject> metas=new java.util.LinkedHashMap<>();
        for(int i=0;i<notificationMetas.length();i++) {
            JSONObject meta=notificationMetas.optJSONObject(i);
            if(meta!=null && meta.optJSONArray("videos")!=null && meta.optJSONArray("videos").length()>0)
                metas.putIfAbsent(meta.optString("id"),meta);
        }
        java.util.Set<String> seen=new java.util.HashSet<>();
        for(int i=0;i<array.length();i++) {
            JSONObject o=array.optJSONObject(i);if(o==null)continue;
            String type=o.optString("type"),id=o.optString("_id"),title=o.optString("name");
            if(id.isEmpty()||title.isEmpty()||(!type.equals("movie")&&!type.equals("series"))||!seen.add(type+":"+id))continue;
            JSONObject state=o.optJSONObject("state");if(state==null)state=new JSONObject();
            double duration=state.optDouble("duration",0),offset=state.optDouble("timeOffset",0);
            boolean continuing=offset>0&&(!o.optBoolean("removed")||o.optBoolean("temp"));
            String resumeId=state.optString("video_id",type.equals("movie")?id:"");
            JSONObject full=complete.get(id);
            WatchedEpisodes watched=type.equals("series")&&full!=null?
                    WatchedEpisodes.read(state.optString("watched",""),full.optJSONArray("videos")):null;
            if(continuing && watched!=null && watched.watched(resumeId)) {
                resumeId=watched.nextUnwatched(resumeId,now);
                continuing=!resumeId.isEmpty();offset=0;
            }
            int count=0;long newest=0,oldest=Long.MAX_VALUE;String firstNew="";
            long lastWatched=date(state.optString("lastWatched"));
            JSONObject meta=metas.get(id);
            JSONArray videos=meta==null?null:meta.optJSONArray("videos");
            if(pullsNotifications(o) && lastWatched>0 && videos!=null) {
                java.util.Set<String> videoIds=new java.util.HashSet<>();
                for(int j=0;j<videos.length();j++) {
                    JSONObject v=videos.optJSONObject(j);if(v==null)continue;
                    String vid=v.optString("id");long released=date(v.optString("released"));
                    // Stremio MetaItem.videos_iter excludes specials (season zero).
                    if(type.equals("series") && v.optInt("season",1)==0)continue;
                    if(!vid.isEmpty() && (watched==null || !watched.watched(vid)) && released>lastWatched && released<=now && videoIds.add(vid)) {
                        count++;newest=Math.max(newest,released);
                        if(released<oldest){oldest=released;firstNew=vid;}
                    }
                }
            }
            if(!continuing && count==0)continue;
            Media m=new Media();m.id=id;m.type=type;m.title=title.replace('\n',' ').replace('\r',' ');
            m.poster=o.optString("poster","");m.newEpisodes=count;m.inProgress=continuing;
            m.progress=duration>0&&continuing?Math.max(0,Math.min(1,offset/duration)):0;
            m.section="Seguir viendo";m.rank=count>0?newest:date(o.optString("_mtime"));
            m.videoId=continuing?resumeId:firstNew;
            String[] video=m.videoId.split(":");
            String episode=video.length==3?"T"+video[1]+" · E"+video[2]:"";
            m.caption=continuing?(episode.isEmpty()?"Continuar":"Continuar · "+episode):
                    (episode.isEmpty()?"Nuevo episodio":"Nuevo · "+episode);
            watching.add(m);
        }
        watching.sort(Comparator.comparingLong((Media m)->m.rank).reversed().thenComparing(m->m.id));
        return new ArrayList<>(watching.subList(0,Math.min(20,watching.size())));
    }
    private static long date(String s){try{return Long.parseLong(s);}catch(Exception ignored){}try{return java.time.Instant.parse(s).toEpochMilli();}catch(Exception e){return 0;}}
    private static File notificationsFile(Context c){return new File(c.getFilesDir(),"stremio-notification-metas.json");}
    private static JSONArray readArray(File file){try{return new JSONArray(new String(java.nio.file.Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));}catch(Exception e){return new JSONArray();}}
    private static List<Media> parseCached(Context c,JSONArray library,JSONArray notices) {
        JSONArray complete=new JSONArray();
        for(int i=0;i<library.length();i++) {
            JSONObject item=library.optJSONObject(i);if(item==null || !item.optString("type").equals("series"))continue;
            JSONObject state=item.optJSONObject("state");if(state==null || state.optString("watched", "").isEmpty())continue;
            File file=new File(new File(c.getCacheDir(),"stremio-art"),Integer.toHexString(("series:"+item.optString("_id")).hashCode())+"-meta.json");
            try{JSONObject meta=new JSONObject(new String(java.nio.file.Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8)).optJSONObject("meta");if(meta!=null)complete.put(meta);}catch(Exception ignored){}
        }
        return parse(library,notices,complete,System.currentTimeMillis());
    }
    static List<Media> cached(Context c){return parseCached(c,readArray(cache(c)),readArray(notificationsFile(c)));}
    private static void writeArray(File file,JSONArray data) throws Exception {
        android.util.AtomicFile f=new android.util.AtomicFile(file);java.io.FileOutputStream out=f.startWrite();
        try{out.write(data.toString().getBytes(StandardCharsets.UTF_8));f.finishWrite(out);}catch(Exception e){f.failWrite(out);throw e;}
    }
    private static JSONObject addons(Context c) throws Exception {
        HttpURLConnection con=(HttpURLConnection)new URL("https://api.strem.io/api/addonCollectionGet").openConnection();
        con.setConnectTimeout(12000);con.setReadTimeout(15000);con.setInstanceFollowRedirects(false);
        con.setRequestMethod("POST");con.setDoOutput(true);con.setRequestProperty("Content-Type","application/json");
        con.setRequestProperty("User-Agent","Stremio/1.6.0 TVHome/1.0");
        try {
            byte[] body=new JSONObject().put("authKey",session(c)).put("update",false).toString().getBytes(StandardCharsets.UTF_8);
            try(java.io.OutputStream out=con.getOutputStream()){out.write(body);}
            if(con.getResponseCode()!=200)throw new Exception("Addons unavailable");
            return result(new JSONObject(new String(read(con.getInputStream(),4*1024*1024),StandardCharsets.UTF_8)));
        }finally{con.disconnect();}
    }
    static JSONArray catalogItems(JSONObject response) {
        JSONArray detailed=response.optJSONArray("metasDetailed");
        return detailed!=null?detailed:response.optJSONArray("metas");
    }
    private static JSONArray notificationMetas(Context c,JSONArray library) {
        File file=notificationsFile(c);JSONArray previous=readArray(file);
        List<JSONObject> candidates=new ArrayList<>();
        for(int i=0;i<library.length();i++){JSONObject o=library.optJSONObject(i);if(o!=null&&pullsNotifications(o))candidates.add(o);}
        candidates.sort(Comparator.comparingLong((JSONObject o)->date(o.optString("_mtime"))).reversed());
        StringBuilder signature=new StringBuilder();for(JSONObject o:candidates)signature.append(o.optString("_id")).append('|');
        String key=Integer.toHexString(signature.toString().hashCode());
        android.content.SharedPreferences prefs=c.getSharedPreferences("stremio-private",0);
        if(file.exists() && key.equals(prefs.getString("notificationIds","")) && System.currentTimeMillis()-file.lastModified()<6*60*60*1000)return previous;
        try {
            JSONArray descriptors=addons(c).optJSONArray("addons");if(descriptors==null)throw new Exception("No addon collection");
            java.util.LinkedHashMap<String,JSONObject> found=new java.util.LinkedHashMap<>();boolean success=false;
            for(int a=0;a<descriptors.length();a++) {
                JSONObject addon=descriptors.optJSONObject(a);if(addon==null)continue;
                JSONObject manifest=addon.optJSONObject("manifest");if(manifest==null)continue;
                JSONArray catalogs=manifest.optJSONArray("catalogs");if(catalogs==null)continue;
                for(int k=0;k<catalogs.length();k++) {
                    JSONObject catalog=catalogs.optJSONObject(k);if(catalog==null)continue;
                    JSONArray extras=catalog.optJSONArray("extra");boolean supports=false;int limit=100;
                    if(extras!=null)for(int e=0;e<extras.length();e++) {
                        JSONObject extra=extras.optJSONObject(e);
                        if(extra!=null&&extra.optString("name").equals("lastVideosIds")){supports=true;limit=Math.max(1,Math.min(100,extra.optInt("optionsLimit",1)));}
                    }
                    JSONArray legacy=catalog.optJSONArray("extraSupported");
                    if(legacy!=null)for(int e=0;e<legacy.length();e++)if("lastVideosIds".equals(legacy.optString(e)))supports=true;
                    if(!supports)continue;
                    List<String> ids=new ArrayList<>();JSONArray prefixes=manifest.optJSONArray("idPrefixes");
                    for(JSONObject item:candidates) {
                        if(!catalog.optString("type").equals(item.optString("type")))continue;
                        boolean prefix=prefixes==null||prefixes.length()==0;
                        if(prefixes!=null)for(int q=0;q<prefixes.length();q++)if(item.optString("_id").startsWith(prefixes.optString(q)))prefix=true;
                        if(prefix)ids.add(item.optString("_id"));
                    }
                    String transport=addon.optString("transportUrl");
                    if(!transport.startsWith("https://")||!transport.endsWith("/manifest.json"))continue;
                    String base=transport.substring(0,transport.length()-"manifest.json".length());
                    // Stremio requests at most 100 eligible library items per catalog.
                    if(ids.size()>100)ids=new ArrayList<>(ids.subList(0,100));
                    for(int start=0;start<ids.size();start+=limit) {
                        String joined=android.text.TextUtils.join(",",ids.subList(start,Math.min(ids.size(),start+limit)));
                        String address=base+"catalog/"+Uri.encode(catalog.optString("type"))+"/"+Uri.encode(catalog.optString("id"))+"/lastVideosIds="+Uri.encode(joined)+".json";
                        try {
                            JSONObject response=new JSONObject(new String(getBytes(address,4*1024*1024),StandardCharsets.UTF_8));
                            JSONArray metas=catalogItems(response);if(metas==null)continue;success=true;
                            for(int j=0;j<metas.length();j++){JSONObject m=metas.optJSONObject(j);if(m!=null)found.putIfAbsent(m.optString("id"),m);}
                        }catch(Exception ignored){android.util.Log.w("TvHomeStremio","Episode catalog unavailable");}
                    }
                }
            }
            if(!success && !candidates.isEmpty())return previous;
            for(int i=0;i<previous.length();i++){JSONObject m=previous.optJSONObject(i);if(m!=null)found.putIfAbsent(m.optString("id"),m);}
            JSONArray merged=new JSONArray();for(JSONObject m:found.values())merged.put(m);
            writeArray(file,merged);prefs.edit().putString("notificationIds",key).apply();
            return merged;
        }catch(Exception ignored){android.util.Log.w("TvHomeStremio","Episode refresh unavailable");return previous;}
    }
    static void writeCache(Context c, JSONArray data) throws Exception {
        android.util.AtomicFile f=new android.util.AtomicFile(cache(c));
        java.io.FileOutputStream out=f.startWrite();
        try{out.write(data.toString().getBytes(StandardCharsets.UTF_8));f.finishWrite(out);}catch(Exception e){f.failWrite(out);throw e;}
    }
    static void refresh(Context c,Runnable changed) {
        Context app=c.getApplicationContext();
        if(!connected(app)||loading||System.currentTimeMillis()-lastRefresh<5000)return;
        loading=true;
        IO.execute(()->{
            try {
                JSONArray data=library(app);
                writeCache(app,data);
                JSONArray notices=notificationMetas(app,data);
                List<Media> items=parseCached(app,data,notices);
                ui().post(changed);
                for(Media m:items){poster(app,m,true);background(app,m,true);}
                lastRefresh=System.currentTimeMillis();
                ui().post(changed);
            } catch(Exception ignored) { android.util.Log.w("TvHomeStremio", "refresh failed: " + ignored.getClass().getSimpleName()); }
            finally {loading=false;}
        });
    }
    static BitmapDrawable artwork(Context c,Media m) {
        Bitmap original=background(c,m,false);
        if(original==null)original=poster(c,m,false);
        Bitmap image=Bitmap.createBitmap(640,360,Bitmap.Config.ARGB_8888);
        Canvas canvas=new Canvas(image);canvas.drawColor(Color.rgb(22,22,24));Paint p=new Paint(Paint.ANTI_ALIAS_FLAG|Paint.FILTER_BITMAP_FLAG);
        if(original!=null){
            int w=original.getWidth(),h=original.getHeight();
            float scale=Math.max(640f/w,360f/h);
            int dw=Math.round(w*scale),dh=Math.round(h*scale);
            canvas.drawBitmap(original,null,new Rect((640-dw)/2,(360-dh)/2,(640+dw)/2,(360+dh)/2),p);
        }
        p.setShader(new android.graphics.LinearGradient(0,220,0,360,0x00000000,0xD9000000,android.graphics.Shader.TileMode.CLAMP));
        canvas.drawRect(0,210,640,360,p);p.setShader(null);
        p.setColor(Color.WHITE);p.setTextSize(20);p.setTypeface(android.graphics.Typeface.create("sans-serif-medium",0));
        canvas.drawText(m.caption,22,312,p);
        if(m.inProgress){
            p.setColor(0x66FFFFFF);canvas.drawRoundRect(22,330,618,336,3,3,p);
            p.setColor(Color.WHITE);canvas.drawRoundRect(22,330,22+(float)(596*m.progress),336,3,3,p);
        }
        if(m.newEpisodes>0){
            String label="+"+m.newEpisodes;p.setTextSize(26);p.setTypeface(android.graphics.Typeface.create("sans-serif-medium",0));
            float width=p.measureText(label)+32,left=618-width;
            p.setColor(0xC9FFFFFF);canvas.drawRoundRect(left-7,17,611,59,10,10,p);
            p.setColor(0xF5FFFFFF);canvas.drawRoundRect(left,24,618,68,10,10,p);
            p.setColor(0xff202123);canvas.drawText(label,left+16,55,p);
        }
        return new BitmapDrawable(c.getResources(),image);
    }
    private static Bitmap decode(File file) {
        if(!file.exists())return null;
        BitmapFactory.Options options=new BitmapFactory.Options();options.inJustDecodeBounds=true;
        BitmapFactory.decodeFile(file.getPath(),options);options.inSampleSize=1;
        while(options.outWidth/options.inSampleSize>1280||options.outHeight/options.inSampleSize>1280)options.inSampleSize*=2;
        options.inJustDecodeBounds=false;return BitmapFactory.decodeFile(file.getPath(),options);
    }
    private static Bitmap background(Context c,Media m,boolean fetch) {
        File dir=new File(c.getCacheDir(),"stremio-art");dir.mkdirs();
        String key=Integer.toHexString((m.type+":"+m.id).hashCode());
        File image=new File(dir,key+"-bg.img"),meta=new File(dir,key+"-meta.json");
        try {
            if(fetch&&m.id.matches("tt[0-9]+")&&(!meta.exists()||System.currentTimeMillis()-meta.lastModified()>6*60*60*1000)) {
                byte[] bytes=getBytes("https://v3-cinemeta.strem.io/meta/"+m.type+"/"+m.id+".json",2*1024*1024);
                java.nio.file.Files.write(meta.toPath(),bytes);
            }
            JSONObject info=meta.exists()?new JSONObject(new String(java.nio.file.Files.readAllBytes(meta.toPath()),StandardCharsets.UTF_8)).optJSONObject("meta"):null;
            String thumb="";JSONArray videos=info==null?null:info.optJSONArray("videos");
            if(videos!=null)for(int i=0;i<videos.length();i++){JSONObject video=videos.optJSONObject(i);if(video!=null&&m.videoId.equals(video.optString("id"))){thumb=video.optString("thumbnail","");break;}}
            File episode=new File(dir,key+"-"+Integer.toHexString(m.videoId.hashCode())+"-episode.img");
            if(fetch&&!thumb.isEmpty()&&!episode.exists())try{java.nio.file.Files.write(episode.toPath(),getBytes(thumb,3*1024*1024));}catch(Exception ignored){}
            Bitmap thumbnail=decode(episode);if(thumbnail!=null)return thumbnail;
            if(fetch&&!image.exists()) {
                String url=info==null?"":info.optString("background","");
                if(!url.isEmpty())java.nio.file.Files.write(image.toPath(),getBytes(url,3*1024*1024));
            }
            return decode(image);
        }catch(Exception ignored){return decode(image);}
    }
    private static Bitmap poster(Context c,Media m,boolean fetch) {
        File dir=new File(c.getCacheDir(),"stremio-art");dir.mkdirs();
        File f=new File(dir,Integer.toHexString(m.poster.hashCode())+".img");
        try {
            if(!f.exists()&&fetch&&!m.poster.isEmpty()) {
                byte[] bytes=getBytes(m.poster,2*1024*1024);
                java.nio.file.Files.write(f.toPath(),bytes);
            }
            BitmapFactory.Options opts=new BitmapFactory.Options();opts.inSampleSize=2;
            return f.exists()?BitmapFactory.decodeFile(f.getPath(),opts):null;
        } catch(Exception e){return null;}
    }
}
