package com.gathin.tvhome;

import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Outline;
import android.graphics.Rect;
import android.view.*;
import android.widget.*;
import androidx.recyclerview.widget.*;
import java.util.*;

/** Foreground-only, cached Continue Watching. No background polling. */
final class StremioShelfView extends FrameLayout {
    private final RecyclerView list;
    private final GlassView glass;
    private final Runnable focused, down, up;
    private List<StremioStore.Media> media = new ArrayList<>();
    private int selected;
    private int dp(float n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    StremioShelfView(Context c, Runnable focused, Runnable down, Runnable up) {
        super(c); this.focused=focused;this.down=down;this.up=up;
        setClipChildren(false);setClipToPadding(false);
        TextView heading=new TextView(c);heading.setText("Seguir viendo");heading.setTextSize(19);
        heading.setTextColor(0xffb9b9bd);heading.setTypeface(android.graphics.Typeface.create("sans-serif-medium",0));
        addView(heading,new LayoutParams(-1,dp(30)));
        list=new RecyclerView(c);list.setLayoutManager(new LinearLayoutManager(c,RecyclerView.HORIZONTAL,false));
        list.setClipToPadding(false);list.setClipChildren(false);list.setOverScrollMode(OVER_SCROLL_NEVER);
        list.setItemAnimator(null);list.setPadding(dp(5),dp(7),dp(20),dp(7));
        LayoutParams lp=new LayoutParams(-1,dp(234));lp.topMargin=dp(28);addView(list,lp);
        glass=new GlassView(c,null);glass.setAlpha(0);glass.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        addView(glass,new LayoutParams(10,10));
        list.addOnScrollListener(new RecyclerView.OnScrollListener(){@Override public void onScrolled(RecyclerView r,int x,int y){highlight();}});
        getViewTreeObserver().addOnGlobalFocusChangeListener((old,v)->{if(v==null||!isAncestor(v))glass.setAlpha(0);});
    }
    private boolean isAncestor(View v){ for(ViewParent p=v.getParent();p!=null;p=p.getParent())if(p==this)return true;return false; }
    void reset(){selected=0;list.stopScroll();list.scrollToPosition(0);clearFocus();}
    void refresh(){
        boolean hadFocus=hasFocus();media=StremioStore.cached(getContext());
        selected=Math.min(selected,Math.max(0,media.size()-1));
        list.setAdapter(new Cards());if(hadFocus)enter();
    }
    void enter(){setVisibility(VISIBLE);list.scrollToPosition(selected);list.post(()->{
        RecyclerView.ViewHolder h=list.findViewHolderForAdapterPosition(selected);
        if(h!=null)h.itemView.requestFocus();else list.postDelayed(()->{RecyclerView.ViewHolder next=list.findViewHolderForAdapterPosition(selected);if(next!=null)next.itemView.requestFocus();},60);
    });}
    private void highlight(){
        View v=list.getFocusedChild();if(v==null)return;
        View image=((ViewGroup)v).getChildAt(0);Rect r=new Rect(0,0,image.getWidth(),image.getHeight());
        offsetDescendantRectToMyCoords(image,r);int pad=dp(6);
        LayoutParams p=(LayoutParams)glass.getLayoutParams();p.width=r.width()+2*pad;p.height=r.height()+2*pad;
        glass.setLayoutParams(p);glass.animate().translationX(r.left-pad).translationY(r.top-pad).alpha(1).setDuration(170).start();
    }
    final class Cards extends RecyclerView.Adapter<RecyclerView.ViewHolder>{
        @Override public int getItemCount(){return Math.max(1,media.size());}
        @Override public RecyclerView.ViewHolder onCreateViewHolder(ViewGroup parent,int type){
            LinearLayout tile=new LinearLayout(getContext());tile.setOrientation(LinearLayout.VERTICAL);
            RecyclerView.LayoutParams p=new RecyclerView.LayoutParams(dp(348),dp(224));p.rightMargin=dp(24);tile.setLayoutParams(p);
            tile.setFocusable(true);tile.setFocusableInTouchMode(true);tile.setClipChildren(false);
            ImageView art=new ImageView(getContext());art.setScaleType(ImageView.ScaleType.CENTER_CROP);
            art.setBackgroundColor(0xff18181b);art.setClipToOutline(true);
            art.setOutlineProvider(new ViewOutlineProvider(){public void getOutline(View v,Outline o){o.setRoundRect(0,0,v.getWidth(),v.getHeight(),dp(10));}});
            tile.addView(art,new LinearLayout.LayoutParams(-1,dp(196)));
            TextView title=new TextView(getContext());title.setTextSize(13);title.setTypeface(android.graphics.Typeface.create("sans-serif",0));title.setTextColor(0xff99999f);
            title.setGravity(Gravity.CENTER);title.setSingleLine(true);title.setEllipsize(android.text.TextUtils.TruncateAt.END);
            tile.addView(title,new LinearLayout.LayoutParams(-1,dp(27)));
            return new RecyclerView.ViewHolder(tile){};
        }
        @Override public void onBindViewHolder(RecyclerView.ViewHolder holder,int position){
            LinearLayout tile=(LinearLayout)holder.itemView;ImageView art=(ImageView)tile.getChildAt(0);TextView title=(TextView)tile.getChildAt(1);
            StremioStore.Media m=media.isEmpty()?null:media.get(position);
            title.setText(m==null?(StremioStore.connected(getContext())?"Sin contenido pendiente · Abrir Stremio":"Conectar Stremio"):m.title);
            art.setImageDrawable(m==null?getContext().getDrawable(R.drawable.ic_apps):StremioStore.artwork(getContext(),m));
            tile.setOnFocusChangeListener((v,has)->{title.setTextColor(has?Color.WHITE:0xff99999f);
                art.animate().scaleX(has?1.025f:1).scaleY(has?1.025f:1).setDuration(170).start();
                if(has){selected=holder.getBindingAdapterPosition();focused.run();list.smoothScrollToPosition(selected);post(()->highlight());}});
            tile.setOnKeyListener((v,key,event)->{
                if(event.getAction()!=KeyEvent.ACTION_DOWN)return false;
                if(key==KeyEvent.KEYCODE_DPAD_DOWN){down.run();return true;}
                if(key==KeyEvent.KEYCODE_DPAD_UP){up.run();return true;}
                if(key==KeyEvent.KEYCODE_DPAD_LEFT||key==KeyEvent.KEYCODE_DPAD_RIGHT){
                    selected=Math.max(0,Math.min(getItemCount()-1,selected+(key==KeyEvent.KEYCODE_DPAD_RIGHT?1:-1)));enter();return true;
                }return false;
            });
            tile.setOnClickListener(v->{try{
                Intent intent=m!=null?new Intent(Intent.ACTION_VIEW,m.uri()).setPackage("com.stremio.one"):
                    StremioStore.connected(getContext())?getContext().getPackageManager().getLeanbackLaunchIntentForPackage("com.stremio.one"):
                    new Intent(getContext(),StremioAccountActivity.class);
                if(intent!=null)getContext().startActivity(intent);
            }catch(Exception e){Toast.makeText(getContext(),"No se pudo abrir Stremio",Toast.LENGTH_SHORT).show();}});
        }
    }
}
