#!/usr/bin/env python3
"""Read-only browser/MPRIS lyrics; stream changed Waybar JSON lines to stdout."""
from __future__ import annotations

import argparse
import bisect
from functools import lru_cache
import concurrent.futures
import fcntl
import hashlib
import html
import json
import math
import os
import re
import sys
import string
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

STAMP = re.compile(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]")
OFFSET = re.compile(r"\[offset:([+-]?\d+)\]", re.I)
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "adws/netease-lyrics-v2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PREFIX = "org.mpris.MediaPlayer2."
EXPERIMENTAL_MUSIC_HOSTS = {
    "open.spotify.com", "music.youtube.com", "music.apple.com",
    "y.qq.com", "music.qq.com", "kugou.com", "www.kugou.com",
    "kuwo.cn", "www.kuwo.cn", "soundcloud.com", "www.soundcloud.com",
}
EXPERIMENTAL_PLAYER_NAMES = ("spotify", "cider", "yesplaymusic", "applemusic")
SETTINGS = {}


_EN = {'♫ 等待网易云': '♫ Waiting for NetEase', '在支持 MPRIS 的浏览器中播放网易云音乐，歌词会自动跟随。': 'Play NetEase Music in an MPRIS-enabled browser to follow its lyrics.', '♫ 等待音乐': '♫ Waiting for music', '在支持 MPRIS 的音乐平台中播放歌曲，歌词会自动跟随。': 'Play music from a supported MPRIS service to follow its lyrics.', '正在获取歌词': 'Loading lyrics', '未找到匹配版本的歌词': 'No matching lyrics found', '暂无同步歌词': 'No synchronized lyrics available', '歌词暂时无法获取': 'Lyrics temporarily unavailable', '纯音乐': 'Instrumental', '已暂停': 'Paused', '正在播放': 'Playing', '前奏 / 间奏': 'Intro / interlude', '浏览器尚未提供播放进度': 'The browser has not provided playback position yet', '连续输出变更后的面板状态': 'Stream changed panel states', '读取一次当前状态并退出': 'Read the current state once and exit', '显示连接与歌词匹配摘要': 'Show connection and lyrics matching summary'}

# This plugin also runs from extracted .mplg packages without the host's imports.
def _tr(text):
    locale = os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG') or 'C'
    if locale.split('.')[0].upper() not in ('C', 'POSIX'):
        language = (os.environ.get('LANGUAGE') or locale).split(':')[0]
        if language.lower().startswith('zh'):
            return text
    return _EN.get(text, text)


def parse_lrc(text: str) -> list[tuple[float, str]]:
    offset = OFFSET.search(text)
    shift = int(offset[1]) / 1000 if offset else 0.0
    lines: dict[float, list[str]] = {}
    for raw in text.splitlines():
        stamps = STAMP.findall(raw)
        if not stamps:
            continue
        value = STAMP.sub("", raw).strip()
        for minute, second, fraction in stamps:
            if int(second) >= 60:
                continue
            # Positive LRC offset means display earlier than the audio timestamp.
            at = max(0.0, int(minute) * 60 + int(second) + float("0." + (fraction or "0")) - shift)
            bucket = lines.setdefault(at, [])
            if value and value not in bucket:
                bucket.append(value)
    return [(at, " / ".join(values)) for at, values in sorted(lines.items())]


def current_line(lines, position: float) -> tuple[int, str]:
    index = bisect.bisect_right([row[0] for row in lines], position) - 1
    return index, lines[index][1] if index >= 0 else ""


def normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def select_song(songs: list[dict], track: dict) -> dict | None:
    matches = []
    for song in songs:
        if normalize(song.get("name", "")) != normalize(track["title"]):
            continue
        artists = {normalize(a.get("name", "")) for a in song.get("artists", [])}
        wanted = {normalize(a) for a in track["artists"] if a}
        if not artists.intersection(wanted):
            # Firefox may collapse multiple artists into one slash-separated field.
            wanted = {normalize(part) for a in track["artists"]
                      for part in re.split(r"[/／;；、]", a) if part.strip()}
        if not wanted or not artists.intersection(wanted):
            continue
        duration = song.get("duration", 0) / 1000
        distance = abs(duration - track["duration"]) if duration and track["duration"] else 0
        if distance > 4:
            continue
        album_matches = normalize(song.get("album", {}).get("name", "")) == normalize(track["album"])
        matches.append((not album_matches, distance, song))
    matches.sort(key=lambda item: item[:2])
    return matches[0][2] if matches else None


def request_json(path: str, params: dict) -> dict:
    url = "https://music.163.com" + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 ADWS-Lyrics/0.1",
        "Referer": "https://music.163.com/",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read(2_000_000))
    if data.get("code") != 200:
        raise ValueError("Lyrics provider unavailable")
    return data


def json_field(data, path: str) -> str:
    if not path:
        return ""
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return ""
    return data if isinstance(data, str) else ""


def custom_lyrics(track: dict, song_id) -> tuple[str, str, str]:
    template = SETTINGS.get("api_url", "")
    values = {"id": song_id, "title": track["title"], "artist": " / ".join(track["artists"]),
              "album": track["album"], "duration": round(track["duration"])}
    for _, field, spec, conversion in string.Formatter().parse(template):
        if field is not None and (field not in values or spec or conversion):
            raise ValueError("Invalid API template")
    url = template.format_map({key: urllib.parse.quote(str(value), safe="") for key, value in values.items()})
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid API URL")
    request = urllib.request.Request(url, headers={"User-Agent": "ADWS-Lyrics/0.3"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read(2_000_000).decode("utf-8-sig")
    try:
        data = json.loads(body)
    except ValueError:
        return body, "", ""
    return (json_field(data, SETTINGS.get("lyric_path", "lrc.lyric")),
            json_field(data, SETTINGS.get("translation_path", "tlyric.lyric")),
            (json_field(data, SETTINGS.get("romanization_path", "rlyric.lyric")) or
             (json_field(data,"romalrc.lyric") if SETTINGS.get("romanization_path","rlyric.lyric")=="rlyric.lyric" else "")))


def playback_token(track):
    # Firefox can reuse mpris:trackid across songs. Bind controls to metadata too.
    values=[track.get('title'),track.get('artists'),track.get('album'),round(track.get('duration',0))]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def track_key(track: dict) -> str:
    signature = [track["title"], track["artists"], track["album"], round(track["duration"])]
    signature.append({key: SETTINGS.get(key) for key in ("api_mode", "api_url", "lyric_path", "translation_path")})
    if SETTINGS.get("romanization_path", "rlyric.lyric") != "rlyric.lyric":
        signature.append(SETTINGS["romanization_path"])
    return hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()



def romanization_fallback_due(result):
    return (SETTINGS.get('romanization_fallback',True)
            and (SETTINGS.get('show_romanization',False) or SETTINGS.get('show_furigana',False))
            and result.get('state')=='ready' and not result.get('romanization')
            and result.get('romanization_retry_at',0)<=time.time()
            and any(re.search(r'[ぁ-ヺ]',text) for _,text in result.get('lines',[])))


def request_lrclib(track, tagged=False):
    # Public API, no account/token. Only song metadata is sent, never playback/session IDs.
    params=({'q':track['title']+' '+' '.join(track['artists'])+' romanized'} if tagged else
            {'track_name':track['title'],'artist_name':' '.join(track['artists'])})
    request=urllib.request.Request('https://lrclib.net/api/search?'+urllib.parse.urlencode(params),
        headers={'User-Agent':'ADWS/1.35 (https://github.com/Haisairova-Official/ADWS)'})
    with urllib.request.urlopen(request,timeout=4) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Lyrics response exceeded limit')
    records=json.loads(raw)
    if not isinstance(records,list):raise ValueError('Invalid lyrics response')
    return records[:20]


def lrclib_romanization(records,track,original):
    """Accept timed romaji only with matching identity, duration and kana anchors."""
    try:duration=float(track.get('duration',0))
    except (TypeError,ValueError):return [],None
    if not duration>0:return [],None
    wanted={normalize(p) for a in track.get('artists',[]) for p in re.split(r'[/／;；、]',a) if p.strip()}
    source=[(at,text) for at,text in original if re.search(r'[一-鿿㐀-䶿]',text)]
    if not source or not wanted:return [],None
    best=[];best_id=None
    for record in records:
        if not isinstance(record,dict):continue
        title=record.get('trackName');artist=record.get('artistName');lrc=record.get('syncedLyrics')
        if not all(isinstance(v,str) for v in (title,artist,lrc)):continue
        # Only an explicit annotation suffix may be ignored, never live/remix/version tags.
        title=re.sub(r'\s*[(\[]\s*(?:romaji|romanized|romanization)\s*[)\]]\s*$','',title,flags=re.I)
        if normalize(title)!=normalize(track['title']):continue
        artists={normalize(a) for a in re.split(r'[/／;；、]',artist) if a.strip()}
        if not artists.intersection(wanted):continue
        try:distance=abs(float(record['duration'])-duration)
        except (ValueError,TypeError,KeyError):continue
        if not distance<=3:continue
        candidates=[]
        for at,text in parse_lrc(lrc):
            for line in text.split(' / '):
                if re.search('[a-zA-Z]',line) and not re.search(r'[ぁ-ヺ一-鿿]',line):candidates.append((at,line))
        matched=[];used=set()
        for timestamp,text in source:
            options=[(i,roman) for i,(at,roman) in enumerate(candidates)
                     if i not in used and abs(at-timestamp)<=1.5 and furigana_runs(text,roman)]
            if len(options)!=1:continue
            index,roman=options[0];used.add(index);matched.append((timestamp,roman))
        # Require several matching lines and broad coverage; do not attach an isolated coincidence.
        if len(matched)>=min(3,len(source)) and len(matched)/len(source)>=0.6 and len(matched)>len(best):
            best,best_id=matched,record.get('id')
    return best,best_id


def supplement_romanization(track,result):
    if not romanization_fallback_due(result):return result
    # Keep the original lyrics and translations even if this optional lookup fails.
    result=dict(result);result['romanization_retry_at']=time.time()+6*3600
    try:
        for tagged in (False,True):
            rows=request_lrclib(track,tagged)
            romanization,identity=lrclib_romanization(rows,track,result.get('lines',[]))
            if romanization:
                result['romanization']=romanization;result['romanization_source']='LRCLIB'
                if isinstance(identity,int):result['romanization_source_id']=identity
                break
    except Exception as error:
        result['romanization_retry_at']=time.time()+600
        print('ADWS romanization fallback: '+type(error).__name__,file=sys.stderr,flush=True)
    return result


def romanization_cache_ready(cached):
    return (not (SETTINGS.get('show_romanization',False) or SETTINGS.get('show_furigana',False))
            or bool(cached.get('romanization')) or cached.get('romanization_schema')==2)


def fetch_lyrics(track: dict, include_fallback=True) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = track_key(track)
    path = CACHE / (key + ".json")
    # Display a valid primary cache immediately, even while another instance enriches it.
    if not include_fallback:
        try:
            cached=json.loads(path.read_text())
            if cached.get('expires',0)>time.time() and romanization_cache_ready(cached):return cached
        except (OSError,ValueError):pass
    # Each output has its own Waybar process. Share both the cache and fetch lock.
    with (CACHE / (key + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            cached = json.loads(path.read_text())
            if cached.get("expires", 0) > time.time() and romanization_cache_ready(cached):
                if include_fallback and romanization_fallback_due(cached):
                    cached=supplement_romanization(track,cached)
                    staged=path.with_suffix('.tmp');staged.write_text(json.dumps(cached,ensure_ascii=False));os.replace(staged,path)
                return cached
        except (OSError, ValueError):
            pass
        try:
            custom = SETTINGS.get("api_mode") == "custom"
            template = SETTINGS.get("api_url", "")
            song = None
            if not custom or "{id}" in template:
                data = request_json("/api/search/get", {
                    "s": track["title"] + " " + " ".join(re.split(r"[/／;；、]", " ".join(track["artists"]))),
                    "type": 1, "limit": 20, "offset": 0,
                })
                song = select_song(data.get("result", {}).get("songs", []), track)
            if custom and ("{id}" not in template or song is not None):
                lyric, translation, romanization = custom_lyrics(track, song["id"] if song else "")
                lines = parse_lrc(lyric)
                result = {"state": "ready" if lines else "unavailable", "lines": lines,
                          "translation": parse_lrc(translation), "romanization": parse_lrc(romanization), "song_id": song["id"] if song else None}
            elif song is None:
                result = {"state": "unmatched", "lines": [], "translation": []}
            else:
                lyric = request_json("/api/song/lyric", {"id": song["id"], "lv": -1, "tv": -1, "rv": -1})
                lines = parse_lrc(lyric.get("lrc", {}).get("lyric", ""))
                result = {
                    "state": "ready" if lines else "instrumental" if lyric.get("nolyric") else "unavailable",
                    "song_id": song["id"], "lines": lines,
                    "translation": parse_lrc(lyric.get("tlyric", {}).get("lyric", "")),
                    "romanization": parse_lrc(json_field(lyric,"rlyric.lyric") or json_field(lyric,"romalrc.lyric")),
                }
            ttl = 30 * 86400 if result["state"] in ("ready", "instrumental") else 21600
        except Exception as exc:
            print("ADWS lyrics: " + type(exc).__name__, file=sys.stderr, flush=True)
            result = {"state": "error", "lines": [], "translation": []}
            ttl = 60
        result.setdefault("romanization", [])
        result["romanization_schema"]=2
        result["expires"] = time.time() + ttl
        if include_fallback:result=supplement_romanization(track,result)
        staged = path.with_suffix(".tmp")
        staged.write_text(json.dumps(result, ensure_ascii=False))
        os.replace(staged, path)
        return result


def mpris_player_names(names) -> list[str]:
    return sorted(name for name in names if name.startswith(MPRIS_PREFIX))


def is_netease_url(value) -> bool:
    try:
        hostname = urllib.parse.urlsplit(str(value)).hostname or ""
    except ValueError:
        return False
    hostname = hostname.rstrip(".").lower()
    return hostname == "music.163.com" or hostname.endswith(".music.163.com")


def is_supported_source(player: str, url, experimental: bool = False) -> bool:
    if is_netease_url(url):
        return True
    if not experimental:
        return False
    try:
        hostname = (urllib.parse.urlsplit(str(url)).hostname or "").rstrip(".").lower()
    except ValueError:
        hostname = ""
    if any(hostname == host or hostname.endswith("." + host) for host in EXPERIMENTAL_MUSIC_HOSTS):
        return True
    name = player.lower()
    return any(token in name for token in EXPERIMENTAL_PLAYER_NAMES)


class BrowserPlayer:
    def __init__(self):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.players = []
        self.refresh_at = 0.0

    def call(self, name, path, interface, method, signature, args):
        return self.bus.call_sync(name, path, interface, method,
            self.GLib.Variant(signature, args), None,
            self.Gio.DBusCallFlags.NONE, 750, None).unpack()

    def snapshot(self, preferred=None) -> dict | None:
        if time.monotonic() >= self.refresh_at:
            names, = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "ListNames", "()", ())
            self.players = mpris_player_names(names)
            self.refresh_at = time.monotonic() + 2
        candidates = []
        for player in self.players:
            if preferred and player!=preferred:continue
            try:
                props, = self.call(player, OBJECT_PATH, "org.freedesktop.DBus.Properties",
                    "GetAll", "(s)", (PLAYER_IFACE,))
                meta = props.get("Metadata", {})
                url = meta.get("xesam:url", "")
                title = meta.get("xesam:title", "")
                if not title:
                    continue
                artists = list(meta.get("xesam:artist", []))
                duration = meta.get("mpris:length", 0) / 1_000_000
                if not is_supported_source(player, url, bool(SETTINGS.get("experimental_other_platforms", False))):
                    continue
                position = props.get("Position")
                candidates.append({"player": player, "title": title,
                    "artists": artists,
                    "album": meta.get("xesam:album", ""),
                    "duration": duration,
                    "track_id": meta.get("mpris:trackid", ""),
                    "can_seek": bool(props.get("CanControl", True) and props.get("CanSeek", False)),
                    "position": max(0, position / 1_000_000) if isinstance(position, int) else None,
                    "status": props.get("PlaybackStatus", "Stopped"),
                    "capabilities": {"previous":props.get("CanControl",True) and props.get("CanGoPrevious",True),
                                     "next":props.get("CanControl",True) and props.get("CanGoNext",True),
                                     "play-pause":props.get("CanControl",True) and props.get("CanPause" if props.get("PlaybackStatus")=="Playing" else "CanPlay",True)}})
            except self.GLib.Error:
                self.refresh_at = 0
        candidates.sort(key=lambda t: t["status"] != "Playing")
        return candidates[0] if candidates else None

    def control(self, action: str, player=None) -> bool:
        track = self.snapshot(player) if player else self.snapshot()
        if not track or not track.get("capabilities",{}).get(action,True):
            return False
        method = {
            "play-pause": "Pause" if track["status"] == "Playing" else "Play",
            "previous": "Previous",
            "next": "Next",
        }[action]
        try:
            self.call(track["player"], OBJECT_PATH, PLAYER_IFACE, method, "()", ())
        except self.GLib.Error:
            return False
        return True


    def seek(self, position, player, track_id, token):
        # SetPosition carries the original track ID, so a concurrent song change
        # cannot apply the old drag position to the next song.
        if not isinstance(player,str) or not player.startswith(MPRIS_PREFIX):return False
        if not isinstance(track_id,str) or not re.fullmatch(r"/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+",track_id):return False
        if track_id == '/org/mpris/MediaPlayer2/TrackList/NoTrack':return False
        try:
            position=float(position)
            if not math.isfinite(position):return False
            track=self.snapshot(player)
            if not track or track.get('track_id')!=track_id or not track.get('can_seek'):return False
            if not token or playback_token(track)!=token:return False
            duration=float(track.get('duration',0))
            if not math.isfinite(duration) or duration<=0:return False
            target=int(min(duration,max(0,position))*1_000_000)
            self.call(player,OBJECT_PATH,PLAYER_IFACE,'SetPosition','(ox)',(track_id,target))
            return True
        except (self.GLib.Error,ValueError,TypeError,OverflowError):return False


def fit_text(text: str, cells: int = 38) -> str:
    # Wide glyphs count twice, combining characters do not add a cell.
    result, width = [], 0
    for char in text:
        if unicodedata.category(char).startswith("C"):
            continue
        size = 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if width + size > cells:
            return "".join(result).rstrip() + "…"
        result.append(char)
        width += size
    return "".join(result)



# Source-provided romaji is the authority: do not guess kanji readings from a dictionary.
_KANA = {}
for consonant, row in [("", "あいうえお"), ("k", "かきくけこ"), ("g", "がぎぐげご"),
                        ("s", "さしすせそ"), ("z", "ざじずぜぞ"), ("t", "たちつてと"),
                        ("d", "だぢづでど"), ("n", "なにぬねの"), ("h", "はひふへほ"),
                        ("b", "ばびぶべぼ"), ("p", "ぱぴぷぺぽ"), ("m", "まみむめも"),
                        ("r", "らりるれろ")]:
    _KANA.update({consonant + vowel: kana for vowel, kana in zip("aiueo", row)})
_KANA.update(dict(shi="し", chi="ち", tsu="つ", fu="ふ", ji="じ", ya="や", yu="ゆ", yo="よ",
                  wa="わ", wo="を", wi="うぃ", we="うぇ", vu="ゔ", she="しぇ", che="ちぇ", je="じぇ"))
for prefix, kana in [("ky","き"),("gy","ぎ"),("sh","し"),("sy","し"),("jy","じ"),("j","じ"),("zy","じ"),
                     ("ch","ち"),("ty","ち"),("cy","ち"),("ny","に"),("hy","ひ"),("by","び"),
                     ("py","ぴ"),("my","み"),("ry","り")]:
    _KANA.update({prefix+vowel:kana+small for vowel,small in zip("auo","ゃゅょ")})
_KANA.update(dict(fa="ふぁ", fi="ふぃ", fe="ふぇ", fo="ふぉ", ti="ち", di="ぢ"))


def romaji_kana(text):
    """Conservative Hepburn/Kunrei conversion; unknown syllables fail closed."""
    text=unicodedata.normalize('NFKC',text).lower().replace('’',"'")
    for source,target in [('ā','aa'),('ī','ii'),('ū','uu'),('ē','ee'),('ō','ou')]:text=text.replace(source,target)
    words=re.findall(r"[a-z']+|[^a-z'\s.,!?、。！？・…:;()（）\-]+",text)
    result=[]
    for word in words:
        i=0
        while i<len(word):
            char=word[i]
            if char=='n' and (i+1==len(word) or word[i+1]=="'" or word[i+1] not in 'aeiouyn'):
                result.append('ん');i+=2 if i+1<len(word) and word[i+1]=="'" else 1;continue
            if word[i:]=='nn':result.append('ん');break
            if word[i:i+2]=='nn':result.append('ん');i+=1;continue
            if i+1<len(word) and char==word[i+1] and char in 'kstpbgdz':
                result.append('っ');i+=1;continue
            if word[i:i+3]=='tch':result.append('っ');i+=1;continue
            for length in (3,2,1):
                syllable=word[i:i+length]
                if syllable in _KANA:
                    result.append(_KANA[syllable]);i+=len(syllable);break
            else:return ''
    return ''.join(result)


def _hiragana(text):
    return ''.join(chr(ord(c)-0x60) if 'ァ'<=c<='ヶ' else c for c in text)


@lru_cache(maxsize=128)
def furigana_runs(text, romanization):
    """Return (base, reading) runs only when the complete alignment is unique."""
    if not text or len(text)>200 or len(romanization)>1000:return ()
    reading=romaji_kana(romanization)
    if not reading or len(reading)>400:return ()
    kanji_group=r'[一-鿿㐀-䶿々〆〇]+(?:[ \u3000]+[一-鿿㐀-䶿々〆〇]+)*'
    tokens=re.findall(kanji_group+'|.',text)
    if not any(re.fullmatch(kanji_group,t) for t in tokens):return ()
    @lru_cache(maxsize=None)
    def match(index,offset):
        if index==len(tokens):return ((),) if offset==len(reading) else ()
        token=tokens[index];choices=[]
        if re.fullmatch(kanji_group,token):
            choices=[(end,reading[offset:end]) for end in range(offset+1,min(len(reading),offset+64)+1)]
        elif token.isspace() or unicodedata.category(token).startswith(('P','S')):
            choices=[(offset,'')]
        else:
            kana=_hiragana(token)
            variants={kana}
            if kana in {'は','へ','を'}:variants.add({'は':'わ','へ':'え','を':'お'}[kana])
            if kana=='ー':variants=set('あいうえお')
            choices=[(offset+len(v),'') for v in variants if reading.startswith(v,offset)]
        solutions=[]
        for end,ruby in choices:
            for suffix in match(index+1,end):
                candidate=((token,ruby),)+suffix
                if candidate not in solutions:solutions.append(candidate)
                if len(solutions)>1:return tuple(solutions)
        return tuple(solutions)
    solutions=match(0,0)
    return solutions[0] if len(solutions)==1 else ()


def aligned_line(lines, timestamp):
    """Match this lyric timestamp instead of carrying an old translation forward."""
    if not lines:return ""
    times=[row[0] for row in lines]
    index=bisect.bisect_left(times,timestamp)
    candidates=[lines[i] for i in (index-1,index) if 0<=i<len(lines)]
    at,text=min(candidates,key=lambda row:abs(row[0]-timestamp))
    return text if abs(at-timestamp)<=0.75 else ""


def render(track: dict | None, lyrics: dict | None) -> dict:
    if not track or track["status"] == "Stopped":
        experimental = bool(SETTINGS.get("experimental_other_platforms", False))
        waiting = '♫ 等待音乐' if experimental else '♫ 等待网易云'
        tooltip = ('在支持 MPRIS 的音乐平台中播放歌曲，歌词会自动跟随。' if experimental
                   else '在支持 MPRIS 的浏览器中播放网易云音乐，歌词会自动跟随。')
        return {"text": _tr(waiting), "primary": _tr(waiting), "secondary": "", "class": "idle", "alt": "idle",
                "tooltip": _tr(tooltip), "player":"", "playing":False, "controls":{"previous":False,"play-pause":False,"next":False}}
    title = track["title"] + " · " + " / ".join(track["artists"])
    state = lyrics.get("state", "loading") if lyrics else "loading"
    descriptions = {"loading": _tr('正在获取歌词'), "unmatched": _tr('未找到匹配版本的歌词'),
                    "unavailable": _tr('暂无同步歌词'), "error": _tr('歌词暂时无法获取'), "instrumental": _tr('纯音乐')}
    line, translation, romanization, previous, following = "", "", "", "", ""
    ruby = ()
    if lyrics and state == "ready" and track["position"] is not None:
        position = track["position"] + float(SETTINGS.get("offset_ms", 0)) / 1000
        lines=lyrics.get("lines",[])
        index, line = current_line(lines, position)
        if index>=0 and line:
            timestamp=lines[index][0]
            if SETTINGS.get("show_translation",True):translation=aligned_line(lyrics.get("translation",[]),timestamp)
            source_romanization=aligned_line(lyrics.get("romanization",[]),timestamp)
            if SETTINGS.get("show_romanization",False):romanization=source_romanization
            if SETTINGS.get("show_furigana",False) and any(re.search(r'[ぁ-ヺ]', t) for _,t in lines):
                ruby=furigana_runs(line,source_romanization)
        if SETTINGS.get("show_context",False):
            previous=next((text for _,text in reversed(lines[:max(0,index)]) if text),"")
            following=next((text for _,text in lines[index+1:] if text),"")
    paused = track["status"] == "Paused"
    status = _tr('已暂停') if paused else _tr('正在播放')
    message = line or descriptions.get(state, _tr('前奏 / 间奏'))
    if track["position"] is None:
        message = _tr('浏览器尚未提供播放进度')
    tooltip = "\n".join(part for part in (title, status, message, translation if line and translation != line else "") if part)
    return {"text": html.escape(("Ⅱ " if paused else "♫ ") + fit_text(line or track["title"])),
            "primary": ("Ⅱ " if paused else "") + (line or "♫ " + track["title"]),
            "secondary": translation if line and translation != line else "",
            "romanization_source": lyrics.get("romanization_source","") if lyrics else "",
            "romanization": romanization, "previous": previous, "next": following,
            "ruby": ([{"base":"Ⅱ ","reading":""}] if paused else []) + [{"base":b,"reading":r} for b,r in ruby] if ruby else [],
            "position":track.get("position") if SETTINGS.get("show_progress",False) else None,
            "duration":track.get("duration") if SETTINGS.get("show_progress",False) else None,
            "track_id":track.get("track_id",""), "can_seek":track.get("can_seek",False), "track_token":playback_token(track),
            "player": track.get("player",""), "playing": not paused, "controls": track.get("capabilities",{}), "title": title,
            "tooltip": html.escape(tooltip), "class": "paused" if paused else state, "alt": state}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", action="store_true", help=_tr('连续输出变更后的面板状态'))
    parser.add_argument("--once", action="store_true", help=_tr('读取一次当前状态并退出'))
    parser.add_argument("--diagnose", action="store_true", help=_tr('显示连接与歌词匹配摘要'))
    parser.add_argument("--control", choices=("play-pause", "previous", "next"))
    parser.add_argument("--settings-json", default="{}")
    parser.add_argument("--player", default=None)
    parser.add_argument("--seek", type=float)
    parser.add_argument("--track-id", default=None)
    parser.add_argument("--track-token", default=None)
    args = parser.parse_args(argv)
    global SETTINGS
    SETTINGS = json.loads(args.settings_json)
    if not isinstance(SETTINGS, dict):
        parser.error("settings must be a JSON object")
    player = BrowserPlayer()
    if args.seek is not None:
        return 0 if player.seek(args.seek,args.player,args.track_id,args.track_token) else 1
    if args.control:
        return 0 if player.control(args.control,args.player) else 1
    if args.once or args.diagnose:
        track = player.snapshot()
        lyrics = fetch_lyrics(track) if track else None
        payload = ({"track": track, "lyrics_state": lyrics.get("state") if lyrics else None,
                    "song_id": lyrics.get("song_id") if lyrics else None,
                    "line_count": len(lyrics.get("lines", [])) if lyrics else 0}
                   if args.diagnose else render(track, lyrics))
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fallback_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    key, future, lyrics, previous = None, None, None, None
    last_emit = 0.0
    try:
        while True:
            track = player.snapshot()
            new_key = track_key(track) if track else None
            if new_key != key:
                if future:
                    future.cancel()
                key, lyrics = new_key, None
                future = executor.submit(fetch_lyrics, track, False) if track else None
            if future and future.done():
                try:
                    lyrics = future.result()
                except Exception:
                    lyrics = {"state": "error", "expires": time.time() + 60}
                future = None
            if track and lyrics and future is None:
                if lyrics.get("expires",0)<=time.time():
                    future=executor.submit(fetch_lyrics,track,False)
                elif romanization_fallback_due(lyrics):
                    future=fallback_executor.submit(fetch_lyrics,track,True)
            payload = json.dumps(render(track, lyrics), ensure_ascii=False)
            if payload != previous or time.monotonic() - last_emit >= 15:
                print(payload, flush=True)
                previous = payload
                last_emit = time.monotonic()
            time.sleep(0.25 if track and track["status"] == "Playing" else 1.0)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        fallback_executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    raise SystemExit(main())
