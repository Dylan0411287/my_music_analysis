-- One row per unique video
CREATE TABLE videos (
    video_id          TEXT PRIMARY KEY,
    title             TEXT,
    channel           TEXT,
    channel_id        TEXT,
    category_id       INTEGER,
    published_at      TEXT,
    duration_secs     REAL,
    available         INTEGER,   -- 1 = still on YouTube, 0 = deleted/private
    is_topic_channel  INTEGER,   -- 1 = "- Topic" channel
    topic_music       INTEGER,   -- 1 = YouTube gave it a music topic
    music_tier        TEXT,      -- music, maybe_music, long_form, ...
    tags              TEXT,      -- a JSON list stored as text (unpacked later)
    topics            TEXT
);

-- One row per time I watched something
CREATE TABLE plays (
    play_id           INTEGER PRIMARY KEY,
    video_id          TEXT NOT NULL REFERENCES videos (video_id),
    watched_at_utc    TEXT,
    watched_at_local  TEXT
);

-- Indexes (video id maybe "how many times did i watch this" or watched at "when did i watch")
CREATE INDEX idx_plays_video ON plays (video_id);
CREATE INDEX idx_plays_time  ON plays (watched_at_local);

-- a saved query that behaves like a table for all music videos.
-- Includes duplicates, from music_PLAYS
CREATE VIEW music_plays AS
SELECT
    p.play_id,
    p.watched_at_local,
    p.video_id,
    v.title,
    v.channel,
    v.duration_secs,
    v.category_id
FROM plays AS p
JOIN videos AS v ON v.video_id = p.video_id
WHERE v.music_tier = 'music'
  AND p.watched_at_local >= '2024-04-01'
  AND p.watched_at_local <  '2026-10-01';



  -- One row per music video: who it's by and what song it is (filled by src/extract_artists.py)
CREATE TABLE video_artists (
    video_id    TEXT PRIMARY KEY REFERENCES videos (video_id),
    kind        TEXT,   -- song, type_beat, reaction
    artist      TEXT,   -- main (first-credited) artist, display spelling
    artist_key  TEXT,   -- matching key: lowercase, no spaces or punctuation
    song        TEXT,
    song_key    TEXT,
    track_key   TEXT,   -- artist_key|song_key: merges uploads of the same song
    method      TEXT,   -- topic, matched, quote, dash_guess, pipe_guess, in_title, unknown, excluded
    confidence  TEXT    -- high, medium, low, none
);
CREATE INDEX idx_va_artist ON video_artists (artist_key);

-- Music plays in the analysis window, with artist and song attached.
-- The ONE place that decides which confidence levels count.
CREATE VIEW song_plays AS
SELECT m.play_id, m.watched_at_local, m.video_id,
       va.artist, va.artist_key, va.song, va.track_key, va.confidence
FROM music_plays AS m
JOIN video_artists AS va ON va.video_id = m.video_id
WHERE va.kind = 'song'
  AND va.confidence IN ('high', 'medium', 'low');