from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent # save the main folder as ROOT
RAW = ROOT / "data" / "raw" / "MyActivity.json" # Input file
OUT = ROOT / "data" / "processed" / "watched.parquet" # output file

END = pd.Timestamp("2026-10-01", tz="UTC")  # cut out data from oct 2026

def get_channel(s):
    if isinstance(s,list) and len(s)>0:
        return s[0]["name"]
    else:
        return None

def clean():
    df = pd.read_json(RAW)

    # keep only watches
    df = df[df["title"].str.startswith("Watched ")].copy() #  going to edit 
    df["title"] = df["title"].str.removeprefix("Watched ")

    # timestamps, cut off the partial month
    df["time"] = pd.to_datetime(df["time"], format="ISO8601", utc=True) #  converting time
    df = df[df["time"] < END] # removing entries after endpoint

    # pull out channel and video id
    df["channel"] = df["subtitles"].apply(get_channel)
    df["video_id"] = df["titleUrl"].str.extract(r"v=([\w-]{11})") # get vid id
    df["is_topic_channel"] = df["channel"].str.endswith("- Topic", na=False)

    df = (
        df[["time", "title", "channel", "video_id", "is_topic_channel", "header"]]
        .sort_values("time")
        .reset_index(drop=True) # sort by date and reset the index
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False) # save df as a parquet in processed

    print("rows:", len(df))
    print("date range:", df["time"].min(), "to", df["time"].max())
    print("unique videos:", df["video_id"].nunique())
    print("rows missing video_id:", df["video_id"].isna().sum())


if __name__ == "__main__":
    clean()