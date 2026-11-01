
# extract_artists.py
# Gives every music video an artist and a song, and saves the result to the `video_artists` table in db/music.db

import re
import sqlite3
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "db" / "music.db"


# Patterns

QUOTES = "'‘’\"“”"
HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]+")

# clutter: (Official Video), [MV], (Lyrics), (prod. X) ...
NOISE = re.compile(
    r"(?i)[\(\[\{][^\)\]\}]*\b(official|video|mv|m/v|lyrics?|audio|visuali[sz]er"
    r"|hd|4k|music|film|prod)\b[^\)\]\}]*[\)\]\}]"
)
SPLIT = re.compile(r"\s[-–—]\s|\s\|\s")                     # " - " and " | "
FEAT = re.compile(r"(?i)\s+(?:x|ft\.?|feat\.?|featuring|&)\s+|\s*,\s*")
QUOTE = re.compile(rf"^\s*([^{QUOTES}]{{1,40}}?)\s*[{QUOTES}](.+)[{QUOTES}]\s*(.*)$")
BARE_NOISE = re.compile(
    r"(?i)\b(official\s+(music\s+)?video|official\s+audio|lyric\s+video|lyrics?|audio|mv|hd|4k)\b"
)
TYPE_BEAT = re.compile(r"(?i)type\s*beat")
REACTION = re.compile(r"(?i)\breact(?:ion|ing|s)?\b")

CONFIDENCE = {
    "topic": "high", "matched": "high", "quote": "high",
    "dash_guess": "medium",
    "pipe_guess": "low", "in_title": "low",
    "unknown": "none", "excluded": "none",
}



# Text helpers

# turn all titles into plain text, lowercase, no accents or punctuation etc
def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", s.lower()).strip()

# removing any spaces from artist names, eg 50 Cent turns into 50cent
def squash(s):
    return norm(s).replace(" ", "")

# Channel name without '- Topic', 'VEVO', 'Official', 'Music' ... as a key
def channel_key(ch):
    ch = re.sub(r"\s*-\s*Topic$", "", str(ch))
    ch = re.sub(r"(?i)vevo$", "", ch)
    ch = re.sub(r"(?i)\b(official|music|records?|channel)\b", "", ch)
    return squash(ch)


def strip_noise(t):
    return re.sub(r"\s+", " ", NOISE.sub(" ", str(t))).strip()


def drop_brackets(t):
    return re.sub(r"[\(\[\{].*?[\)\]\}]", " ", str(t))

# split a cleaned title into parts. Returns (parts, delimiter)
def split_parts(clean):
    parts = [p.strip() for p in SPLIT.split(clean) if p.strip()]
    if len(parts) > 1:
        delim = "pipe" if re.search(r"\s\|\s", clean) else "dash"
        return parts, delim
    colon = [p.strip() for p in re.split(r":\s", clean, maxsplit=1) if p.strip()]
    if len(colon) == 2:
        return colon, "colon"
    return parts or [clean], "none"

# The whole credit first, then each name in it ('A x B ft. C' -> A, B, C)
def names(part):
    whole = re.sub(r"\s+", " ", drop_brackets(part)).strip()
    pieces = [n.strip() for n in FEAT.split(whole) if n and n.strip()]
    return [whole] + pieces

# Display version of an artist name: no Korean script, no empty brackets,
# no stray separators at the ends, Falls back to the original if nothing is left

def tidy(name):
    raw = str(name).strip()
    s = HANGUL.sub(" ", raw)
    s = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", s)
    s = re.sub(r"^[\s\-–—|:]+|[\s\-–—|:]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if squash(s) else raw

# Main artist from a credit. Keeps the whole credit if it is a known name
# (so 'Tyler, The Creator' isn't cut at the comma), otherwise the first name
def primary(part, known):
    cands = names(part)
    if squash(cands[0]) in known:
        return tidy(cands[0])
    for n in cands[1:]:
        if squash(n):
            return tidy(n)
    return tidy(part)


def clean_song(s):
    if not isinstance(s, str):
        return None
    s = re.sub(r"\s+", " ", str(s))
    return re.sub(r"^[\s\-–—|:]+|[\s\-–—|:]+$", "", s).strip() or None

# Key used to merge uploads of the same song (features/remaster tags removed)
def song_key(s):
    if not s:
        return None
    s = BARE_NOISE.sub(" ", NOISE.sub(" ", str(s)))
    s = re.sub(r"(?i)[\(\[][^\)\]]*\b(feat|ft|featuring|with|remaster(ed)?|radio edit"
               r"|explicit|clean)\b[^\)\]]*[\)\]]", " ", s)
    s = re.sub(r"(?i)\s+(feat\.?|ft\.?|featuring)\s+.*$", " ", s)
    s = re.sub(r"(?i)\s-\s.*\bremaster(ed)?\b.*$", " ", s)
    return squash(s) or None


# (index of the first title part containing the channel name or a known artist,
# the name that matched). (-1, None) if nothing matched.
def find_side(parts, chan_sq, known):
    for i, p in enumerate(parts):
        for n in names(p):
            k = squash(n)
            if k and (k == chan_sq or k in known):
                return i, n
    return -1, None



# Add newly confirmed artist names to the dictionary. Adds the name that matched;
# if that was one name inside a credit ('A x B ft. C'), also adds the other names,
# but never the whole credit as if it were one artist
def learn(known, part, matched):
    found = names(part)
    to_add = [matched] if squash(matched) == squash(found[0]) else found[1:]
    for n in to_add:
        if squash(n):
            known.setdefault(squash(n), norm(n))


# ARTIST 이름 'Song' MV  ->  (artist, song), or None if the title isn't in that shape
def quote_parse(title):
    m = QUOTE.match(str(title))
    if not m:
        return None
    artist_raw = m.group(1)
    if re.search(r"\s[-–—|]\s|:", artist_raw):      # a different title format
        return None
    return tidy(artist_raw), m.group(2).strip()


# Main logic

# One row per music-tier video, with its total number of plays
def load_videos(con):
    v = pd.read_sql("""
        SELECT v.video_id, v.title, v.channel, v.is_topic_channel,
               COUNT(p.play_id) AS plays
        FROM videos AS v
        JOIN plays AS p ON p.video_id = v.video_id
        WHERE v.music_tier = 'music'
        GROUP BY v.video_id
    """, con)
    v["title"] = v["title"].fillna("")
    v["channel"] = v["channel"].fillna("")
    return v


def extract(v):
    v = v.copy()
    v["kind"] = "song"
    v["method"] = "unknown"
    v["artist"] = None
    v["song"] = None

    topic = v["is_topic_channel"] == 1

    # 0. set aside type beats and reaction videos
    v.loc[~topic & v["title"].str.contains(TYPE_BEAT), "kind"] = "type_beat"
    v.loc[~topic & (v["kind"] == "song") & v["title"].str.contains(REACTION), "kind"] = "reaction"
    v.loc[v["kind"] != "song", "method"] = "excluded"

    # 1. Topic channels
    v.loc[topic, "artist"] = v.loc[topic, "channel"].str.replace(r"\s*-\s*Topic$", "", regex=True)
    v.loc[topic, "song"] = v.loc[topic, "title"]
    v.loc[topic, "method"] = "topic"

    # the artist dictionary: matching key (no spaces) -> spaced form (for in_title)
    known = {squash(a): norm(a) for a in v.loc[topic, "artist"] if squash(a)}

    # everything else that is a song
    t = v[~topic & (v["kind"] == "song")].copy()
    t["clean"] = t["title"].map(strip_noise)
    split = t["clean"].map(split_parts)
    t["parts"] = split.str[0]
    t["delim"] = split.str[1]
    t["chan_sq"] = t["channel"].map(channel_key)

    # 2. matched: pass 1 learns new artist names, pass 2 uses the bigger dictionary
    for p, c in zip(t["parts"], t["chan_sq"]):
        side, matched = find_side(p, c, known)
        if side >= 0:
            learn(known, p[side], matched)
    t["side"] = [find_side(p, c, known)[0] for p, c in zip(t["parts"], t["chan_sq"])]
    method = pd.Series("unknown", index=t.index)
    method[t["side"] >= 0] = "matched"

    # 3. quote pattern (K-pop titles from label channels)
    q = t["title"].map(quote_parse)
    is_q = q.notna() & (method == "unknown")
    method[is_q] = "quote"
    for a in q[is_q].str[0]:
        if squash(a):
            known.setdefault(squash(a), norm(a))

    # 4 and 5. two-part titles where nothing was recognised
    two = t["parts"].str.len() == 2
    method[(method == "unknown") & two & (t["delim"] == "dash")] = "dash_guess"
    method[(method == "unknown") & two & (t["delim"] == "pipe")] = "pipe_guess"

    # 6. a known artist (4+ letters) appearing anywhere in the title
    long_known = [s for k, s in known.items() if len(k) >= 4]

    def in_title(title):
        padded = f" {norm(title)} "
        hits = [a for a in long_known if f" {a} " in padded]
        return max(hits, key=len) if hits else None

    hit = pd.Series(None, index=t.index, dtype=object)
    still = method == "unknown"
    hit[still] = t.loc[still, "title"].map(in_title)
    method[still & hit.notna()] = "in_title"
    t["method"] = method

    # artist and song for each non-Topic row
    def artist_song(r):
        m, p = r["method"], r["parts"]
        if m == "matched":
            song = " - ".join(x for i, x in enumerate(p) if i != r["side"])
            return primary(p[r["side"]], known), clean_song(song)
        if m == "quote":
            return q[r.name]
        if m == "dash_guess":
            return primary(p[0], known), clean_song(p[1])
        if m == "pipe_guess":
            return primary(p[1], known), clean_song(p[0])
        if m == "in_title":
            a = hit[r.name]
            pattern = r"[\W_]+".join(re.escape(w) for w in a.split())
            song = re.sub(rf"(?i)(?<!\w){pattern}(?!\w)", " ", r["clean"])
            return a, clean_song(BARE_NOISE.sub(" ", song))
        return None, None

    res = t.apply(artist_song, axis=1)
    v.loc[t.index, "method"] = t["method"]
    v.loc[t.index, "artist"] = res.str[0]
    v.loc[t.index, "song"] = res.str[1]

    # keys
    v["artist_key"] = v["artist"].map(lambda a: (squash(a) or None) if isinstance(a, str) else None)
    v["song_key"] = v["song"].map(lambda s: song_key(s) if isinstance(s, str) else None)
    v["track_key"] = [f"{a}|{s}" if isinstance(a, str) and isinstance(s, str) else None
                      for a, s in zip(v["artist_key"], v["song_key"])]

    # one display spelling per artist: prefer the Topic channel spelling,
    # then the most common spelling; in_title names (lowercase) come last
    cand = v.loc[v["artist_key"].notna(), ["artist_key", "artist", "method"]].copy()
    cand["rank"] = cand["method"].map({"topic": 0, "in_title": 2}).fillna(1)
    best = (cand.groupby(["artist_key", "artist"])
            .agg(rank=("rank", "min"), n=("artist", "size"))
            .reset_index()
            .sort_values(["artist_key", "rank", "n"], ascending=[True, True, False])
            .drop_duplicates("artist_key")
            .set_index("artist_key")["artist"])
    has_key = v["artist_key"].notna()
    v.loc[has_key, "artist"] = v.loc[has_key, "artist_key"].map(best)

    v["confidence"] = v["method"].map(CONFIDENCE)
    return v, len(known)


def report(v, dict_size):
    print("Music videos:", len(v), "| plays:", v["plays"].sum())
    print("Artist dictionary size:", dict_size)

    print("\nBy kind (videos, plays):")
    print(v.groupby("kind").agg(videos=("video_id", "size"), plays=("plays", "sum")).to_string())

    songs = v[v["kind"] == "song"]
    tab = songs.groupby(["confidence", "method"]).agg(videos=("video_id", "size"), plays=("plays", "sum"))
    tab["% plays"] = (100 * tab["plays"] / songs["plays"].sum()).round(1)
    print("\nSongs by method:")
    print(tab.to_string())

    resolved = songs.loc[songs["confidence"] != "none", "plays"].sum()
    print(f"\nArtist coverage: {resolved / songs['plays'].sum():.1%} of song plays")
    print("Unique artists:", songs["artist_key"].nunique(),
          "| unique tracks:", songs["track_key"].nunique(),
          "| song videos:", len(songs))


def main():
    con = sqlite3.connect(DB)
    try:
        v, dict_size = extract(load_videos(con))
        cols = ["video_id", "kind", "artist", "artist_key", "song", "song_key",
                "track_key", "method", "confidence"]
        con.execute("DELETE FROM video_artists")      # makes the script safe to re-run
        v[cols].to_sql("video_artists", con, if_exists="append", index=False)
        con.commit()
        report(v, dict_size)
        n = con.execute("SELECT COUNT(*) FROM video_artists").fetchone()[0]
        print("\nvideo_artists rows saved:", n)
    finally:
        con.close()


if __name__ == "__main__":
    main()