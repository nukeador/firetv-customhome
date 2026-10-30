package com.gathin.tvhome;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.zip.InflaterInputStream;

/** Read-only decoder of Stremio's anchor:length:zlib-base64 watched field. */
final class WatchedEpisodes {
    final List<JSONObject> videos;
    private final byte[] bits;
    private final int shift;
    private WatchedEpisodes(List<JSONObject> videos, byte[] bits, int shift) {
        this.videos=videos;this.bits=bits;this.shift=shift;
    }
    static WatchedEpisodes read(String field, JSONArray source) {
        try {
            if(field.isEmpty() || source==null)return null;
            int end=field.lastIndexOf(':'),start=field.lastIndexOf(':',end-1);
            String anchor=field.substring(0,start);
            int length=Integer.parseInt(field.substring(start+1,end));
            if(length<1 || length>524288)return null;
            List<JSONObject> videos=new ArrayList<>();
            java.util.Set<String> ids=new java.util.HashSet<>();
            for(int i=0;i<source.length();i++) {
                JSONObject v=source.optJSONObject(i);
                if(v!=null && !v.optString("id").isEmpty() && ids.add(v.optString("id")))videos.add(v);
            }
            videos.sort(Comparator.comparingInt((JSONObject v)->number(v,"season",1))
                    .thenComparingInt(v->number(v,"episode",2))
                    .thenComparing(v->v.optString("released")));
            int anchorIndex=-1;
            for(int i=0;i<videos.size();i++)if(anchor.equals(videos.get(i).optString("id")))anchorIndex=i;
            if(anchorIndex<0)return null;
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            try(InflaterInputStream in=new InflaterInputStream(new ByteArrayInputStream(
                    java.util.Base64.getDecoder().decode(field.substring(end+1))))) {
                byte[] buffer=new byte[1024];int n;
                while((n=in.read(buffer))!=-1){if(out.size()+n>65536)return null;out.write(buffer,0,n);}
            }
            return new WatchedEpisodes(videos,out.toByteArray(),length-anchorIndex-1);
        }catch(Exception ignored){return null;}
    }
    private static int number(JSONObject v,String key,int part) {
        if(v.has(key))return v.optInt(key,-1);
        String[] id=v.optString("id").split(":");
        try{return Integer.parseInt(id[part]);}catch(Exception ignored){return -1;}
    }
    boolean watched(String id) {
        for(int i=0;i<videos.size();i++)if(id.equals(videos.get(i).optString("id"))) {
            int bit=i+shift;
            return bit>=0 && bit/8<bits.length && ((bits[bit/8]>>(bit%8))&1)!=0;
        }
        return false;
    }
    String nextUnwatched(String current,long now) {
        boolean after=false;
        for(JSONObject v:videos) {
            String id=v.optString("id");
            if(id.equals(current)){after=true;continue;}
            if(!after || number(v,"season",1)==0 || watched(id))continue;
            try {
                String released=v.optString("released");
                if(released.isEmpty() || java.time.Instant.parse(released).toEpochMilli()>now)continue;
                return id;
            }catch(Exception ignored){}
        }
        return "";
    }
}
