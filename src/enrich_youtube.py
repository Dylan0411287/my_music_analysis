import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API_KEY = os.getenv("YT_API_KEY")

WATCHED = ROOT / "data" / "processed" / "watched.parquet"
CACHE = ROOT / "data" / "processed" / "video_meta.jsonl"
URL = "https://www.googleapis.com/youtube/v3/videos"
BATCH = 50


def load_done():
    # loads video ids that we have already fetched
    done = set()
    if CACHE.exists(): # does this path exist yet?
        with open(CACHE, encoding="utf-8") as f: # open cache as f, utf-8 for diff languages
            for line in f: # loop through each line of JSONL file
                done.add(json.loads(line)["video_id"]) # add each id to done
    return done


def fetch_batch(ids): # ask youtube for video metadata
    r = requests.get(
        URL,
        params={
            "part": "snippet,contentDetails,topicDetails", # we want these 3 bits of info
            "id": ",".join(ids), # join video ids
            "key": API_KEY,
        },
        timeout=30,
    )
    if r.status_code == 403: # forbidden error
        raise SystemExit(f"403 from the API (quota or key problem): {r.text[:300]}")
    r.raise_for_status()
    return r.json().get("items", [])


def to_row(item):
    sn = item.get("snippet", {}) # get snippet from the API response, empty dictionary if none
    return {
        "video_id": item["id"],
        "available": True,
        "title": sn.get("title"),
        "channel_id": sn.get("channelId"),
        "channel_title": sn.get("channelTitle"),
        "category_id": sn.get("categoryId"),
        "published_at": sn.get("publishedAt"),
        "tags": sn.get("tags", []),
        "duration": item.get("contentDetails", {}).get("duration"),
        "topics": item.get("topicDetails", {}).get("topicCategories", []),
        "live": sn.get("liveBroadcastContent"),
    }


def main(limit=None):
    if not API_KEY:
        raise SystemExit("No YT_API_KEY found. Check the .env file.")

    ids = pd.read_parquet(WATCHED)["video_id"].dropna().unique().tolist() 
    # give me a list of available, unique video ids
    done = load_done() # load fetched ids
    todo = [i for i in ids if i not in done] # only do the ids not in done
    if limit:
        todo = todo[:limit]
    print(f"{len(ids)} unique videos, {len(done)} already fetched, {len(todo)} to do") # progress

    with open(CACHE, "a", encoding="utf-8") as f: # append each new vid id in CACHE
        for n in range(0, len(todo), BATCH):
            batch = todo[n : n + BATCH]
            items = fetch_batch(batch)
            returned = set() # what is returned by fetch_batch
            for item in items:
                returned.add(item["id"]) # adding returned ids to returned
                f.write(json.dumps(to_row(item), ensure_ascii=False) + "\n")
            # IDs the API didn't return are deleted/private: record them too
            for vid in batch:
                if vid not in returned:
                    f.write(json.dumps({"video_id": vid, "available": False}) + "\n")
            f.flush()
            if (n // BATCH) % 20 == 0:
                print(f"  {n + len(batch)} / {len(todo)}") # print the progress
            time.sleep(0.1)

    print("done")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None) # allow test runs with custom limit