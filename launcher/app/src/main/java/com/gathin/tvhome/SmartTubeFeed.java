package com.gathin.tvhome;

import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import java.util.ArrayList;
import java.util.List;

/** Reads only the recommendations SmartTube publishes to the system TV provider. */
final class SmartTubeFeed {
    static final String PACKAGE = "org.smarttube.beta";
    static final class Video {
        final String title, description, image, intent;
        Video(String title, String description, String image, String intent) {
            this.title=title; this.description=description; this.image=image; this.intent=intent;
        }
    }
    static List<Video> read(Context context) {
        List<Video> videos=new ArrayList<>();
        List<Long> channels=new ArrayList<>();
        try(Cursor c=context.getContentResolver().query(Uri.parse("content://android.media.tv/channel"),
                new String[]{"_id","package_name","display_name"},null,null,null)) {
            if(c!=null)while(c.moveToNext()) {
                String name=c.getString(2);
                if(PACKAGE.equals(c.getString(1)) && name!=null &&
                        (name.toLowerCase(java.util.Locale.ROOT).contains("recommend") ||
                         name.toLowerCase(java.util.Locale.ROOT).contains("recomend"))) channels.add(c.getLong(0));
            }
        }
        for(long id:channels) {
            Uri uri=Uri.parse("content://android.media.tv/preview_program").buildUpon()
                    .appendQueryParameter("channel",Long.toString(id)).build();
            try(Cursor c=context.getContentResolver().query(uri,
                    new String[]{"title","short_description","poster_art_uri","intent_uri","channel_id"},null,null,null)) {
                if(c!=null)while(c.moveToNext() && videos.size()<40) {
                    if(c.getLong(4)!=id || c.isNull(3)) continue;
                    videos.add(new Video(c.getString(0),c.getString(1),c.getString(2),c.getString(3)));
                }
            }
        }
        return videos;
    }
}
