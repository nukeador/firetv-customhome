package com.gathin.tvhome;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import java.io.ByteArrayOutputStream;
import java.util.List;
import java.util.zip.DeflaterOutputStream;
import static org.junit.Assert.*;

public class WatchedEpisodesTest {
    private static final long NOW=java.time.Instant.parse("2026-10-23T12:00:00Z").toEpochMilli();
    private String field(String anchor,int length,int bits) throws Exception {
        ByteArrayOutputStream out=new ByteArrayOutputStream();
        try(DeflaterOutputStream z=new DeflaterOutputStream(out)){z.write(bits);}
        return anchor+":"+length+":"+java.util.Base64.getEncoder().encodeToString(out.toByteArray());
    }
    private JSONObject video(int season,int episode,String release) throws Exception {
        return new JSONObject().put("id","show:"+season+":"+episode).put("season",season).put("episode",episode).put("released",release);
    }
    private JSONArray videos() throws Exception {
        return new JSONArray().put(video(1,1,"2026-01-01T00:00:00Z")).put(video(1,2,"2026-01-02T00:00:00Z"));
    }
    private JSONObject item(String watched) throws Exception {
        return new JSONObject().put("_id","show").put("name","Show").put("type","series")
                .put("state",new JSONObject().put("video_id","show:1:2").put("timeOffset",999).put("duration",1000)
                        .put("lastWatched","2026-10-22T00:00:00Z").put("watched",watched));
    }
    private List<StremioStore.Media> parse(JSONObject item,JSONArray videos,JSONArray notices) throws Exception {
        return StremioStore.parse(new JSONArray().put(item),notices,
                new JSONArray().put(new JSONObject().put("id","show").put("videos",videos)),NOW);
    }
    @Test public void completedFinalEpisodeHasNoContinueCard() throws Exception {
        assertTrue(parse(item(field("show:1:2",2,3)),videos(),new JSONArray()).isEmpty());
    }
    @Test public void futureSeasonDoesNotKeepCompletedSeriesVisible() throws Exception {
        assertTrue(parse(item(field("show:1:2",2,3)),videos().put(video(2,1,"2027-01-01T00:00:00Z")),new JSONArray()).isEmpty());
    }
    @Test public void releasedNextSeasonBecomesResumeTargetWithoutOldProgress() throws Exception {
        List<StremioStore.Media> items=parse(item(field("show:1:2",2,3)),videos().put(video(2,1,"2026-10-23T01:00:00Z")),new JSONArray());
        assertEquals(1,items.size());assertEquals("show:2:1",items.get(0).videoId);assertEquals(0,items.get(0).progress,0);
    }
    @Test public void genuineUnwatchedProgressIsPreserved() throws Exception {
        assertEquals("show:1:2",parse(item(field("show:1:1",1,1)),videos(),new JSONArray()).get(0).videoId);
    }
    @Test public void alreadyWatchedNotificationsAreNotCounted() throws Exception {
        JSONArray v=videos();v.getJSONObject(1).put("released","2026-10-23T01:00:00Z");
        JSONArray notices=new JSONArray().put(new JSONObject().put("id","show").put("videos",v));
        assertTrue(parse(item(field("show:1:2",2,3)),v,notices).isEmpty());
    }
    @Test public void invalidBitfieldDoesNotDiscardProgress() throws Exception {
        assertEquals(1,parse(item("broken"),videos(),new JSONArray()).size());
    }
    @Test public void missingAnchorDoesNotGuessWatchedState() throws Exception {
        assertNull(WatchedEpisodes.read(field("missing:1:1",1,1),videos()));
    }
    @Test public void anchorShiftAccountsForInsertedSpecials() throws Exception {
        WatchedEpisodes w=WatchedEpisodes.read(field("show:1:2",2,3),videos().put(video(0,1,"2025-01-01T00:00:00Z")));
        assertFalse(w.watched("show:0:1"));assertTrue(w.watched("show:1:1"));assertTrue(w.watched("show:1:2"));
    }
}
