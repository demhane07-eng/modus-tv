#!/usr/bin/env python3
"""
Builds the Modus TV channel list.

Every run:
  1. Downloads the latest playlists from iptv-org and Free-TV for the countries in config.json.
  2. Merges them per channel (a channel can have several links; the first working one is used).
  3. Applies overrides.json (renames, hidden channels, extra channels).
  4. Checks every link and publishes only working channels to playlists/.
     Links whose sound Android plays (AAC/MP3) go first; links with MP2/AC-3 or no sound become backups.
  5. Remembers when each channel last worked (state.json) and writes report.md.

Channels are never deleted from the sources: a channel that fails today is left out of today's
list and comes back automatically on the first day it works again.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "playlists")
UA = "Mozilla/5.0 (Linux; Android 9; MiBox) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def fetch(url, timeout=30, limit=80_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode("utf-8", "replace")


# ---------------------------------------------------------------- parsing

ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def parse_m3u(text):
    """Returns a list of dicts: name, url, attrs, opts (EXTVLCOPT lines)."""
    out, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = {k.lower(): v.strip() for k, v in ATTR.findall(line)}
            name, inq = "", False
            for i, ch in enumerate(line[7:], 7):
                if ch == '"':
                    inq = not inq
                elif ch == "," and not inq:
                    name = line[i + 1:].strip()
                    break
            cur = {"name": name or attrs.get("tvg-name", ""), "attrs": attrs, "opts": []}
        elif line.startswith("#EXTVLCOPT:"):
            if cur is not None:
                cur["opts"].append(line)
        elif line.startswith("#"):
            continue
        elif cur is not None:
            cur["url"] = line
            out.append(cur)
            cur = None
    return out


CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
AZ = {"ə": "e", "ı": "i", "ş": "s", "ç": "c", "ğ": "g", "ö": "o", "ü": "u"}


def norm(s):
    s = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", (s or "").lower())
    o = []
    for ch in s:
        if ch in CYR:
            o.append(CYR[ch])
        elif ch in AZ:
            o.append(AZ[ch])
        elif ch.isalnum():
            o.append(unicodedata.normalize("NFKD", ch)[0])
    s = "".join(o).replace("yy", "y")
    for suf in ("hd", "tv"):
        if len(s) > len(suf) + 1 and s.endswith(suf):
            s = s[: -len(suf)]
    return s


def channel_key(entry):
    tid = entry["attrs"].get("tvg-id", "").split("@")[0].strip().lower()
    return "id:" + tid if tid else "n:" + norm(entry["name"])


def non_latin(s):
    return any(unicodedata.name(ch, "").startswith(("CYRILLIC", "ARABIC", "GEORGIAN", "ARMENIAN", "GREEK", "HEBREW")) for ch in s)


def clean_name(name):
    """'AzTV (1080p) [Geo-blocked]' -> 'AzTV'"""
    return re.sub(r"\s*[\(\[][^)\]]*[\)\]]", "", name).strip() or name


# ---------------------------------------------------------------- build

def main():
    cfg = load_json(os.path.join(HERE, "config.json"), {})
    over = load_json(os.path.join(HERE, "overrides.json"), {})
    state = load_json(os.path.join(HERE, "state.json"), {})
    today = dt.date.today().isoformat()

    # iptv-org database: original-script names and logos
    natives, logos = {}, {}
    try:
        for c in json.loads(fetch(cfg["iptv_api"] + "channels.json")):
            cid = c.get("id", "").lower()
            for n in c.get("alt_names") or []:
                if non_latin(n):
                    natives[cid] = n
                    break
            if c.get("logo"):
                logos[cid] = c["logo"]
        try:
            for l in json.loads(fetch(cfg["iptv_api"] + "logos.json")):
                cid = l.get("channel", "").lower()
                if cid and cid not in logos and l.get("url"):
                    logos[cid] = l["url"]
        except Exception as e:
            print("logos.json:", e)
    except Exception as e:
        print("channels.json:", e)

    freetv = []
    try:
        freetv = parse_m3u(fetch(cfg["freetv_playlist"]))
    except Exception as e:
        print("Free-TV:", e)

    channels = {}  # key -> channel
    order = []
    by_name = {}  # (list, normalised name) -> key; joins a source without tvg-id to the same channel in another source
    skip = re.compile(cfg.get("skip_url_pattern", r"$^"), re.I)

    def add(entry, country, source, merge_only=False):
        url = entry.get("url", "")
        if not url or skip.search(url):
            return
        key = channel_key(entry)
        if merge_only and key not in channels:
            return  # only extra links for channels this country already has
        nkey = (country["label"], norm(clean_name(entry["name"])))
        if key not in channels and nkey[1] and nkey in by_name:
            other = channels[by_name[nkey]]
            # same name in the same country: merge unless both carry different tvg-ids (then they are different channels)
            if not (key.startswith("id:") and other["id"]):
                key = other["key"]
        ch = channels.get(key)
        if ch is None:
            tid = entry["attrs"].get("tvg-id", "").split("@")[0]
            ch = channels[key] = {
                "key": key, "id": tid, "name": clean_name(entry["name"]),
                "group": entry["attrs"].get("group-title", "").split(";")[0] or "Undefined",
                "logo": entry["attrs"].get("tvg-logo", ""), "list": country["label"],
                "urls": [], "opts": entry["opts"], "sources": set(),
            }
            order.append(key)
        if nkey[1]:
            by_name.setdefault(nkey, key)
        if url not in [u for u, _ in ch["urls"]]:
            ch["urls"].append((url, entry["opts"]))
        ch["sources"].add(source)
        if not ch["id"]:
            tid = entry["attrs"].get("tvg-id", "").split("@")[0]
            if tid:
                ch["id"] = tid
        if not ch["logo"] and entry["attrs"].get("tvg-logo"):
            ch["logo"] = entry["attrs"]["tvg-logo"]

    for code, country in cfg["countries"].items():
        try:
            for e in parse_m3u(fetch(cfg["iptv_org"] + f"countries/{code}.m3u")):
                add(e, country, "iptv-org")
        except Exception as e:
            print(f"iptv-org {code}:", e)
        for e in freetv:
            if e["attrs"].get("group-title", "").lower() == country.get("freetv", "").lower():
                add(e, country, "free-tv")

    # more links for the same channels: iptv-org keeps every stream in its repository,
    # the country lists above sometimes carry only one of them
    for code, country in cfg["countries"].items():
        for src in cfg.get("iptv_streams", []):
            try:
                for e in parse_m3u(fetch(src.format(code=code))):
                    add(e, country, "iptv-org-streams", merge_only=True)
            except Exception as e:
                print(f"streams {code}:", e)

    # overrides: extra channels
    for x in over.get("extra", []):
        e = {"name": x["name"], "url": x["url"], "attrs": {"tvg-id": x.get("id", ""), "group-title": x.get("group", "General"),
             "tvg-logo": x.get("logo", "")}, "opts": []}
        add(e, {"label": x.get("list", "Digər")}, "manual")

    hidden = {h.lower() for h in over.get("hide", [])}
    renames = {k.lower(): v for k, v in over.get("rename", {}).items()}
    native_over = {k.lower(): v for k, v in over.get("native_name", {}).items()}

    todo = [channels[k] for k in order if channels[k]["id"].lower() not in hidden and channels[k]["name"].lower() not in hidden]
    print(f"{len(todo)} channels, {sum(len(c['urls']) for c in todo)} links to check")

    # check links (first working link wins)
    multi = set()  # links that offer several quality levels (the app can step down on a weak network)

    def works(url, opts):
        headers = {"User-Agent": UA}
        for o in opts:
            if "http-user-agent=" in o:
                headers["User-Agent"] = o.split("=", 1)[1]
            if "http-referrer=" in o:
                headers["Referer"] = o.split("=", 1)[1]
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=cfg.get("timeout", 12)) as r:
                if r.status >= 400:
                    return False
                head = r.read(8192)
                ctype = (r.headers.get("Content-Type") or "").lower()
                if head.count(b"#EXT-X-STREAM-INF") >= 2:
                    multi.add(url)
                if b"#EXTM3U" in head or b"#EXT-X" in head:
                    return True
                return "video" in ctype or "mpegurl" in ctype or "octet-stream" in ctype or head[:1] == b"G"
        except Exception:
            return False

    # sound: Android's own player plays AAC/MP3/Opus everywhere; AC-3 only on some boxes; MP2 nowhere
    ffprobe = shutil.which("ffprobe")
    AUDIO_RANK = {"aac": 0, "mp3": 0, "opus": 0, "vorbis": 0, "flac": 0, "ac3": 2, "eac3": 2, "mp2": 3, "mp1": 3, "dts": 3}

    def audio_rank(url, opts):
        """0 = sound plays, 1 = unknown, 2 = only on some devices, 3 = no sound on Android."""
        if not ffprobe:
            return 1
        ua, ref = UA, ""
        for o in opts:
            if "http-user-agent=" in o:
                ua = o.split("=", 1)[1]
            if "http-referrer=" in o:
                ref = o.split("=", 1)[1]
        cmd = [ffprobe, "-v", "error", "-rw_timeout", "10000000", "-user_agent", ua]
        if ref:
            cmd += ["-headers", f"Referer: {ref}\r\n"]
        cmd += ["-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", url]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        except Exception:
            return 1
        if res.returncode != 0:
            return 1  # could not open it from here (often blocked outside the region)
        codecs = [c.strip().lower() for c in res.stdout.splitlines() if c.strip()]
        if not codecs:
            return 3  # it opened but carries no sound
        return min(AUDIO_RANK.get(c, 1) for c in codecs)

    # every link of a channel is checked; working ones go first, the rest stay as backups
    # (a link that fails from GitHub's server may still work in Azerbaijan)
    def check(ch):
        good, bad = [], []
        for url, opts in ch["urls"]:
            (good if works(url, opts) else bad).append((url, opts))
        if not good:
            return ch, None, None, [], None
        rank = None
        if len(good) > 1 and ffprobe:
            ranks = {u: audio_rank(u, o) for u, o in good[:6]}
            good.sort(key=lambda x: ranks.get(x[0], 1))  # stable: same rank keeps the source order
            rank = ranks.get(good[0][0])
        url, opts = good[0]
        return ch, url, opts, [u for u, _ in good[1:] + bad], rank

    results = []
    with cf.ThreadPoolExecutor(max_workers=cfg.get("workers", 24)) as pool:
        for r in pool.map(check, todo):
            results.append(r)

    # write playlists
    os.makedirs(OUT, exist_ok=True)
    epg = ",".join(cfg.get("epg", []))
    head = f'#EXTM3U x-tvg-url="{epg}"\n' if epg else "#EXTM3U\n"
    per_list = {}
    ok_count, report_dead, backup_count = 0, [], 0
    silent, nmulti = [], 0
    for ch, url, opts, alts, rank in results:
        if rank == 3:
            silent.append(ch["name"])
        if url in multi:
            nmulti += 1
        st = state.setdefault(ch["key"], {"name": ch["name"], "list": ch["list"]})
        st["name"], st["list"] = ch["name"], ch["list"]
        if not url:
            st["fails"] = st.get("fails", 0) + 1
            report_dead.append(ch)
            continue
        ok_count += 1
        st["last_ok"], st["fails"] = today, 0
        cid = ch["id"].lower()
        name = renames.get(cid) or renames.get(ch["name"].lower()) or ch["name"]
        native = native_over.get(cid) or natives.get(cid, "")
        logo = logos.get(cid) or ch["logo"]
        attrs = [f'tvg-id="{ch["id"]}"'] if ch["id"] else []
        if logo:
            attrs.append(f'tvg-logo="{logo}"')
        attrs.append(f'group-title="{ch["group"]}"')
        attrs.append(f'x-list="{ch["list"]}"')
        if native and native != name:
            attrs.append(f'x-native-name="{native}"')
        alts = alts[: cfg.get("max_backup_links", 4)]
        backup_count += len(alts)
        # "#EXTALT:" = backup link for M-Modus TV; other players ignore these lines
        lines = [f'#EXTINF:-1 {" ".join(attrs)},{name}'] + list(opts or []) + [f"#EXTALT:{a}" for a in alts] + [url]
        per_list.setdefault(ch["list"], []).append("\n".join(lines))

    all_lines = []
    for code, country in cfg["countries"].items():
        items = per_list.get(country["label"], [])
        all_lines += items
        with open(os.path.join(OUT, f"{code}.m3u"), "w", encoding="utf-8") as f:
            f.write(head + "\n".join(items) + "\n")
    for label, items in per_list.items():
        if label not in [c["label"] for c in cfg["countries"].values()]:
            all_lines += items
    with open(os.path.join(OUT, "modus.m3u"), "w", encoding="utf-8") as f:
        f.write(head + "\n".join(all_lines) + "\n")

    with open(os.path.join(HERE, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)

    # report
    long_dead = sorted((s for s in state.values() if s.get("fails", 0) >= cfg.get("report_after_days", 30)), key=lambda s: s["name"])
    rep = [f"# Kanal hesabatı — {today}", "", f"İşləyən: **{ok_count}** · bu gün işləməyən: **{len(report_dead)}** · ehtiyat linklər: **{backup_count}** · bir neçə keyfiyyətdə: **{nmulti}**", "",
           "| Siyahı | İşləyən |", "|---|---|"]
    for code, country in cfg["countries"].items():
        rep.append(f"| {country['label']} | {len(per_list.get(country['label'], []))} |")
    rep += ["", "## Bu gün işləməyənlər (sabah yenidən yoxlanılacaq)", ""]
    rep += [f"- {c['name']} ({c['list']})" for c in sorted(report_dead, key=lambda c: (c['list'], c['name']))] or ["—"]
    rep += ["", "## Səsi Android-də çıxmayanlar (səsli link tapılmadı)", ""]
    rep += [f"- {n}" for n in sorted(silent)] or ["—"]
    rep += ["", f"## {cfg.get('report_after_days', 30)}+ gündür işləməyənlər (yeni link lazımdır)", ""]
    rep += [f"- {s['name']} ({s['list']}) · son işləmə: {s.get('last_ok', 'heç vaxt')}" for s in long_dead] or ["—"]
    with open(os.path.join(ROOT, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")
    print(f"done: {ok_count} working, {len(report_dead)} not working today, {backup_count} backup links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
