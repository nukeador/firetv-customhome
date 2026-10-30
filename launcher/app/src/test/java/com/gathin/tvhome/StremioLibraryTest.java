package com.gathin.tvhome;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import java.util.List;
import static org.junit.Assert.*;

public class StremioLibraryTest {
    private JSONObject item(String id, boolean saved, boolean removed, int offset) throws Exception {
        return new JSONObject().put("_id", id).put("type", "series").put("name", "Title " + id)
                .put("temp", !saved).put("removed", removed).put("_mtime", "2026-10-23T00:00:00Z")
                .put("_ctime", "2026-10-20T00:00:00Z")
                .put("state", new JSONObject().put("timeOffset", offset).put("duration", 1000)
                        .put("video_id", id + ":2:3").put("lastWatched", "2026-10-23T01:00:00Z"));
    }
    @Test public void temporaryWatchedItemsAppearInContinueWatching() throws Exception {
        List<StremioStore.Media> result = StremioStore.parse(new JSONArray().put(item("watch", false, true, 250)));
        assertEquals(1, result.size());
        assertEquals("Seguir viendo", result.get(0).section);
        assertEquals(0.25, result.get(0).progress, 0.001);
        assertTrue(result.get(0).caption.contains("T2 · E3"));
    }
    @Test public void savedUnwatchedItemsWithoutNotificationsStayOut() throws Exception {
        List<StremioStore.Media> result = StremioStore.parse(new JSONArray().put(item("saved", true, false, 0)));
        assertTrue(result.isEmpty());
    }
    @Test public void deletedAndUnwatchedTemporaryItemsStayOut() throws Exception {
        assertTrue(StremioStore.parse(new JSONArray().put(item("deleted", true, true, 0))
                .put(item("temp", false, false, 0))).isEmpty());
    }
    @Test public void continueWatchingIsBoundedToTwentyItems() throws Exception {
        JSONArray source = new JSONArray();
        for (int i=0;i<25;i++) source.put(item("library"+i,true,false,0)).put(item("watch"+i,false,false,10));
        List<StremioStore.Media> result = StremioStore.parse(source);
        assertEquals(20,result.size());
        assertEquals("Seguir viendo",result.get(0).section);
        assertEquals("Seguir viendo",result.get(19).section);
    }
    @Test public void malformedAndDuplicateItemsDoNotCrashOrRepeat() throws Exception {
        JSONArray source=new JSONArray().put(JSONObject.NULL).put(new JSONObject())
                .put(item("same",true,false,100)).put(item("same",true,false,100));
        assertEquals(1,StremioStore.parse(source).size());
    }

    private static final long NOW=java.time.Instant.parse("2026-10-23T12:00:00Z").toEpochMilli();
    private JSONObject meta(String id, JSONObject... videos) throws Exception {
        JSONArray all=new JSONArray();for(JSONObject v:videos)all.put(v);
        return new JSONObject().put("id",id).put("videos",all);
    }
    private JSONObject video(String id,String released) throws Exception {
        return new JSONObject().put("id",id).put("released",released);
    }
    @Test public void seriesWithNewEpisodesAppearsWithoutPlaybackProgress() throws Exception {
        JSONArray source=new JSONArray().put(item("pending",true,false,0));
        JSONArray metas=new JSONArray().put(meta("pending",video("pending:2:4","2026-10-23T10:00:00Z")));
        List<StremioStore.Media> result=StremioStore.parse(source,metas,NOW);
        assertEquals(1,result.size());assertEquals(1,result.get(0).newEpisodes);
        assertFalse(result.get(0).inProgress);assertEquals("pending:2:4",result.get(0).videoId);
    }
    @Test public void notificationsExcludeOldFutureAndDuplicateEpisodes() throws Exception {
        JSONArray metas=new JSONArray().put(meta("series",
                video("series:1:1","2026-10-22T10:00:00Z"),
                video("series:1:2","2026-10-23T02:00:00Z"),
                video("series:1:2","2026-10-23T02:00:00Z"),
                video("series:1:3","2026-10-23T03:00:00Z"),
                video("series:1:4","2026-10-24T00:00:00Z")));
        List<StremioStore.Media> result=StremioStore.parse(new JSONArray().put(item("series",true,false,0)),metas,NOW);
        assertEquals(2,result.get(0).newEpisodes);assertEquals("series:1:2",result.get(0).videoId);
    }
    @Test public void removedTemporaryMutedAndNeverWatchedDoNotGetNotifications() throws Exception {
        JSONArray source=new JSONArray().put(item("removed",true,true,0)).put(item("temporary",false,false,0));
        JSONObject muted=item("muted",true,false,0);muted.getJSONObject("state").put("noNotif",true);source.put(muted);
        JSONObject never=item("never",true,false,0);never.getJSONObject("state").remove("lastWatched");source.put(never);
        JSONArray metas=new JSONArray();for(String id:new String[]{"removed","temporary","muted","never"})metas.put(meta(id,video(id+":1:1","2026-10-23T10:00:00Z")));
        assertTrue(StremioStore.parse(source,metas,NOW).isEmpty());
    }
    @Test public void notificationsOrderByNewestReleaseAndResumeByModificationTime() throws Exception {
        JSONObject resume=item("resume",true,false,100).put("_mtime","2026-10-23T04:00:00Z");
        resume.getJSONObject("state").put("lastWatched","2026-10-23T11:00:00Z");
        JSONObject older=item("older",true,false,0),newer=item("newer",true,false,0);
        JSONArray metas=new JSONArray().put(meta("older",video("older:1:1","2026-10-23T02:00:00Z")))
                .put(meta("newer",video("newer:1:1","2026-10-23T06:00:00Z")));
        List<StremioStore.Media> result=StremioStore.parse(new JSONArray().put(resume).put(older).put(newer),metas,NOW);
        assertEquals("newer",result.get(0).id);assertEquals("resume",result.get(1).id);assertEquals("older",result.get(2).id);
    }
    @Test public void completedNotificationsDisappearAfterWatching() throws Exception {
        JSONObject o=item("series",true,false,0);o.getJSONObject("state").put("lastWatched","2026-10-23T11:00:00Z");
        JSONArray metas=new JSONArray().put(meta("series",video("series:1:1","2026-10-23T10:00:00Z")));
        assertTrue(StremioStore.parse(new JSONArray().put(o),metas,NOW).isEmpty());
    }
    @Test public void resumePointerIsPreservedWhenNotificationsExist() throws Exception {
        JSONArray metas=new JSONArray().put(meta("series",video("series:2:4","2026-10-23T10:00:00Z")));
        List<StremioStore.Media> result=StremioStore.parse(new JSONArray().put(item("series",true,false,250)),metas,NOW);
        assertEquals(1,result.get(0).newEpisodes);assertTrue(result.get(0).inProgress);
        assertEquals("series:2:3",result.get(0).videoId);assertEquals(0.25,result.get(0).progress,0.001);
    }

    @Test public void specialsAreExcludedLikeStremioVideosIterator() throws Exception {
        JSONArray metas=new JSONArray().put(meta("series",video("series:0:1","2026-10-23T10:00:00Z").put("season",0),
                video("series:1:1","2026-10-23T10:00:00Z").put("season",1)));
        assertEquals(1,StremioStore.parse(new JSONArray().put(item("series",true,false,0)),metas,NOW).get(0).newEpisodes);
    }

    @Test public void cinemetaDetailedCatalogResponseIsRecognized() throws Exception {
        JSONArray episodes=new JSONArray().put(meta("series",video("series:1:1","2026-10-23T10:00:00Z")));
        assertSame(episodes,StremioStore.catalogItems(new JSONObject().put("metasDetailed",episodes)));
        assertSame(episodes,StremioStore.catalogItems(new JSONObject().put("metas",episodes)));
    }

    @Test public void episodeImageCanRedirectToHttpsCdn() throws Exception {
        assertEquals("https://cdn.example.org/episode.jpg",StremioStore.httpsRedirect(
                new java.net.URL("https://images.example.org/old.jpg"),"https://cdn.example.org/episode.jpg").toString());
        assertEquals("https://images.example.org/new.jpg",StremioStore.httpsRedirect(
                new java.net.URL("https://images.example.org/old.jpg"),"/new.jpg").toString());
    }
    @Test(expected=Exception.class) public void imageRedirectCannotDowngradeToHttp() throws Exception {
        StremioStore.httpsRedirect(new java.net.URL("https://images.example.org/old.jpg"),"http://cdn.example.org/image.jpg");
    }
    @Test(expected=Exception.class) public void imageRedirectCannotCarryUserInfo() throws Exception {
        StremioStore.httpsRedirect(new java.net.URL("https://images.example.org/old.jpg"),"https://user:password@cdn.example.org/image.jpg");
    }
}
