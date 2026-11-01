from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
WATCHED = PROCESSED / "watched.parquet" # all watched videos/history
META = PROCESSED / "video_meta.jsonl" # all metadata per UNIQUE video
OUT = PROCESSED / "plays_enriched.parquet" # combine those together

LOCAL_TZ = "Europe/London"  


def load_meta():
    meta = pd.read_json(META, lines=True, dtype={"video_id": str}) # keep video id a string
    meta = meta.drop_duplicates("video_id") # incase video_meta has duplicates
    meta["secs"] = pd.to_timedelta(meta["duration"], errors="coerce").dt.total_seconds()
    # convert duration in .jsonl into seconds instead of ISO8601, if errors just outputs NaT
    meta["category_id"] = pd.to_numeric(meta["category_id"], errors="coerce").astype("Int64")
    meta["topic_music"] = meta["topics"].apply(
        lambda t: isinstance(t, list) and any("music" in u.lower() for u in t) 
        # does topics contain something which contains music?
    )
    return meta.rename(columns={"title": "yt_title"}) 
    # in watched.parquet we have title, so here we change to yt_title since we merging them


def assign_tier(plays): # assign a category to each video e.g. music/ too short
    secs = plays["secs"]
    topic = plays["is_topic_channel"]
    core = plays["cat10"] & plays["topic_music"] # TOPIC_MUSIC IS THE WIKI LINK, NOT TOPIC CHANNEL
    one = (plays["cat10"] ^ plays["topic_music"]) & ~topic

    conditions = [
        ~plays["available"], # unavailable
        secs < 60, # too short
        (topic & (secs <= 1200)) | (core & secs.between(60, 480)), 
        # topic < 20mins or cat 10/topic between 1 and 10 mins
        one & secs.between(60, 480), # either cat10/topic and 1 to 10 mins
        (core | one | topic) & (secs > 480), #longer than 10mins
    ]
    labels = ["unavailable", "too_short", "music", "maybe_music", "long_form"]
    return np.select(conditions, labels, default="not_music")


def build():
    watched = pd.read_parquet(WATCHED)
    plays = watched.merge(load_meta(), on="video_id", how="left") 
    # using video id, merge the two together, so adding columns together
    # keep every row from watched (left)

    plays["available"] = plays["available"].eq(True)
    plays["topic_music"] = plays["topic_music"].eq(True)
    plays["cat10"] = (plays["category_id"] == 10).fillna(False).astype(bool)
    plays["time_local"] = plays["time"].dt.tz_convert(LOCAL_TZ)
    plays["music_tier"] = assign_tier(plays) 
    # use the tier function to categorise all videos in watched.parquet

    plays.to_parquet(OUT, index=False) # output plays saved as parquet file using OUT

    print(plays["music_tier"].value_counts()) # print total value for each tier
    print(
        plays.groupby(plays["time_local"].dt.year)["music_tier"] # proprtion of vids each year
        .value_counts(normalize=True)
        .unstack()
        .round(3)
    )


if __name__ == "__main__":
    build() 
