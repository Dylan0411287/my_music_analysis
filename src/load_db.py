import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PLAYS = ROOT / "data" / "processed" / "plays_enriched.parquet"
DB = ROOT / "db" / "music.db"
SCHEMA = ROOT / "sql" / "schema.sql"


def to_json(x):
    # Lists can't go in a SQL column so store them as JSON text.
    if isinstance(x, (list, np.ndarray)):
        return json.dumps([str(i) for i in x]) # convert every item in list into json
    return "[]"


def nulls_to_none(df): 
    # Turn pandas missing values into None, which SQLite stores as NULL.
    return df.astype(object).where(df.notna(), None)


def build_videos(plays):
    first = plays.sort_values("time").drop_duplicates("video_id") 
    # sort by time and remove duplicates
    videos = pd.DataFrame( # go through all schema things and specify what they are
        {
            "video_id": first["video_id"],
            "title": first["yt_title"].fillna(first["title"]),
            # if video deleted try and fill the name with one in my history instead
            "channel": first["channel_title"].fillna(first["channel"]), # same thing
            "channel_id": first["channel_id"],
            "category_id": first["category_id"],
             "published_at": pd.to_datetime(first["published_at"], utc=True).dt.strftime(
                "%Y-%m-%d %H:%M:%S" # turn into string
            ),
            "duration_secs": first["secs"],
            "available": first["available"].astype(int), # into 0 and 1 for sql
            "is_topic_channel": first["is_topic_channel"].astype(int),
            "topic_music": first["topic_music"].astype(int),
            "music_tier": first["music_tier"],
            "tags": first["tags"].apply(to_json), # turn python lists into .json text
            "topics": first["topics"].apply(to_json),
        }
    )
    return nulls_to_none(videos)


def build_plays(plays): # 2nd table for all plays
    return pd.DataFrame(
        {
            "video_id": plays["video_id"],
            "watched_at_utc": plays["time"].dt.strftime("%Y-%m-%d %H:%M:%S"),
            "watched_at_local": plays["time_local"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

# so far we have built 2 pandas dataframes, in order to put the dataframe rows into SQLite
# we use insert function. it takes in connection, whatever table (plays or videos) and the 
# respective dataframe.

def insert(con, table, df): 
    cols = ", ".join(df.columns)
    marks = ", ".join("?" * len(df.columns)) # sql placeholder depending on how many columns
    con.executemany(
        f"INSERT INTO {table} ({cols}) VALUES ({marks})", # repeatedly insert values
        df.itertuples(index=False, name=None), # converts df row into tuple sql can understand
    )


def main():
    plays = pd.read_parquet(PLAYS)

    DB.parent.mkdir(exist_ok=True) # ensure db exists
    if DB.exists():
        DB.unlink()  # delete music.db if exists and start again

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA.read_text(encoding="utf-8")) # make tables etc
    insert(con, "videos", build_videos(plays)) # insert videos into videos
    insert(con, "plays", build_plays(plays)) # insert plays into plays
    con.commit()

    for table in ("videos", "plays"):
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(table, n)
    con.close()


if __name__ == "__main__":
    main()