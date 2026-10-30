package com.gathin.tvhome;

import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Outline;
import android.graphics.drawable.GradientDrawable;
import android.view.*;
import android.widget.*;
import androidx.recyclerview.widget.*;
import java.util.*;
import java.util.concurrent.*;

/** Foreground refresh of public TV recommendations; no account access or background polling. */
final class SmartTubeShelfView extends FrameLayout {
    static final int HEIGHT_DP=260;
    private final RecyclerView list;
    private final Runnable focused,up,down;
    private final java.util.function.Consumer<Boolean> availability;
    private final ExecutorService io=Executors.newFixedThreadPool(2);
    private final android.util.LruCache<String,Bitmap> images=new android.util.LruCache<String,Bitmap>(4*1024*1024){
        @Override protected int sizeOf(String key,Bitmap value){return value.getAllocationByteCount();}
    };
    private List<SmartTubeFeed.Video> videos=Collections.emptyList();
    private int selected;
    private boolean loading,closed;
    private int dp(float n){return Math.round(n*getResources().getDisplayMetrics().density);}
    SmartTubeShelfView(Context c,Runnable focused,Runnable up,Runnable down,java.util.function.Consumer<Boolean> availability){
        super(c);this.focused=focused;this.up=up;this.down=down;this.availability=availability;
        setClipChildren(false);setClipToPadding(false);setVisibility(GONE);
        TextView heading=new TextView(c);heading.setText("Recomendados · SmartTube");heading.setTextSize(19);
        heading.setTextColor(0xffb9b9bd);heading.setTypeface(android.graphics.Typeface.create("sans-serif-medium",0));
        addView(heading,new LayoutParams(-1,dp(30)));
        list=new RecyclerView(c);list.setLayoutManager(new LinearLayoutManager(c,RecyclerView.HORIZONTAL,false));
        list.setItemAnimator(null);list.setClipToPadding(false);list.setClipChildren(false);
        list.setPadding(dp(5),dp(7),dp(20),dp(7));list.setOverScrollMode(OVER_SCROLL_NEVER);
        LayoutParams p=new LayoutParams(-1,dp(228));p.topMargin=dp(28);addView(list,p);
    }
    void reset(){selected=0;list.stopScroll();list.scrollToPosition(0);clearFocus();}
    void refresh(){
        if(loading||closed)return;loading=true;
        io.execute(()->{
            List<SmartTubeFeed.Video> result;
            try{result=SmartTubeFeed.read(getContext());}catch(Exception e){result=Collections.emptyList();}
            final List<SmartTubeFeed.Video> fresh=result;
            post(()->{loading=false;if(closed)return;boolean restore=hasFocus();videos=fresh;
                selected=Math.min(selected,Math.max(0,videos.size()-1));list.setAdapter(new Cards());
                availability.accept(!videos.isEmpty());if(restore&&!videos.isEmpty())enter();});
        });
    }
    void close(){closed=true;io.shutdownNow();images.evictAll();}
    void enter(){if(videos.isEmpty())return;setVisibility(VISIBLE);list.scrollToPosition(selected);focusSelected(0);}
    private void focusSelected(int attempt){list.postDelayed(()->{
        if(closed)return;RecyclerView.ViewHolder h=list.findViewHolderForAdapterPosition(selected);
        if(h!=null)h.itemView.requestFocus();else if(attempt<4)focusSelected(attempt+1);
    },attempt==0?0:60);}
    private GradientDrawable background(boolean focus){
        GradientDrawable d=new GradientDrawable();d.setColor(focus?0xff313236:0xff252629);
        d.setCornerRadius(dp(10));d.setStroke(dp(1),focus?0xffd6d6db:0x16ffffff);return d;
    }
    private void artwork(ImageView image,String uri){
        image.setTag(uri);image.setImageDrawable(null);if(uri==null||uri.isEmpty())return;
        Bitmap cached=images.get(uri);if(cached!=null){image.setImageBitmap(cached);return;}
        if(closed)return;
        io.execute(()->{try{
            if(!uri.startsWith("https://"))return;
            byte[] bytes=StremioStore.getBytes(uri,3*1024*1024);
            BitmapFactory.Options o=new BitmapFactory.Options();o.inJustDecodeBounds=true;
            BitmapFactory.decodeByteArray(bytes,0,bytes.length,o);o.inSampleSize=1;
            while(o.outWidth/o.inSampleSize>640||o.outHeight/o.inSampleSize>360)o.inSampleSize*=2;
            o.inJustDecodeBounds=false;Bitmap b=BitmapFactory.decodeByteArray(bytes,0,bytes.length,o);
            if(b!=null){images.put(uri,b);post(()->{if(!closed&&uri.equals(image.getTag()))image.setImageBitmap(b);});}
        }catch(Exception ignored){}});
    }
    final class Cards extends RecyclerView.Adapter<RecyclerView.ViewHolder>{
        @Override public int getItemCount(){return videos.size();}
        @Override public RecyclerView.ViewHolder onCreateViewHolder(ViewGroup parent,int type){
            LinearLayout tile=new LinearLayout(getContext());tile.setOrientation(LinearLayout.VERTICAL);
            RecyclerView.LayoutParams p=new RecyclerView.LayoutParams(dp(280),dp(213));p.rightMargin=dp(20);tile.setLayoutParams(p);
            tile.setBackground(background(false));tile.setFocusable(true);tile.setFocusableInTouchMode(true);
            tile.setClipToOutline(true);tile.setOutlineProvider(new ViewOutlineProvider(){public void getOutline(View v,Outline o){o.setRoundRect(0,0,v.getWidth(),v.getHeight(),dp(10));}});
            ImageView art=new ImageView(getContext());art.setScaleType(ImageView.ScaleType.CENTER_CROP);art.setBackgroundColor(0xff18181b);
            tile.addView(art,new LinearLayout.LayoutParams(-1,dp(157)));
            TextView title=new TextView(getContext());title.setTextSize(13);title.setTextColor(0xffe4e4e7);title.setMaxLines(2);
            title.setEllipsize(android.text.TextUtils.TruncateAt.END);title.setPadding(dp(9),dp(3),dp(9),0);
            tile.addView(title,new LinearLayout.LayoutParams(-1,dp(34)));
            TextView meta=new TextView(getContext());meta.setTextSize(10);meta.setTextColor(0xffa6a6ad);meta.setSingleLine(true);
            meta.setEllipsize(android.text.TextUtils.TruncateAt.END);meta.setPadding(dp(9),0,dp(9),0);
            tile.addView(meta,new LinearLayout.LayoutParams(-1,dp(20)));
            return new RecyclerView.ViewHolder(tile){};
        }
        @Override public void onBindViewHolder(RecyclerView.ViewHolder holder,int position){
            LinearLayout tile=(LinearLayout)holder.itemView;SmartTubeFeed.Video v=videos.get(position);
            ((TextView)tile.getChildAt(1)).setText(v.title);((TextView)tile.getChildAt(2)).setText(v.description);
            tile.setContentDescription(v.title+" · "+v.description);artwork((ImageView)tile.getChildAt(0),v.image);
            tile.setOnFocusChangeListener((view,has)->{tile.setBackground(background(has));
                tile.animate().scaleX(has?1.025f:1).scaleY(has?1.025f:1).setDuration(150).start();
                if(has){int pos=holder.getBindingAdapterPosition();if(pos>=0){selected=pos;list.smoothScrollToPosition(pos);}focused.run();}});
            tile.setOnKeyListener((view,key,event)->{
                if(event.getAction()!=KeyEvent.ACTION_DOWN)return false;
                if(key==KeyEvent.KEYCODE_DPAD_UP){up.run();return true;}
                if(key==KeyEvent.KEYCODE_DPAD_DOWN){down.run();return true;}
                if(key==KeyEvent.KEYCODE_DPAD_LEFT||key==KeyEvent.KEYCODE_DPAD_RIGHT){
                    selected=Math.max(0,Math.min(videos.size()-1,selected+(key==KeyEvent.KEYCODE_DPAD_RIGHT?1:-1)));enter();return true;
                }return false;
            });
            tile.setOnClickListener(view->{try{
                Intent intent=Intent.parseUri(v.intent,Intent.URI_INTENT_SCHEME);intent.setSelector(null);
                if(intent.getComponent()!=null&&!SmartTubeFeed.PACKAGE.equals(intent.getComponent().getPackageName()))intent.setComponent(null);
                intent.setPackage(SmartTubeFeed.PACKAGE);intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(intent);
            }catch(Exception e){Toast.makeText(getContext(),"No se pudo abrir el vídeo en SmartTube",Toast.LENGTH_SHORT).show();}});
        }
    }
}
