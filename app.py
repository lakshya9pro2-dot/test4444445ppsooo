#!/usr/bin/env python3
import concurrent.futures
import json
import os
import re
import subprocess
import urllib.parse
from flask import Flask, request, jsonify, Response, send_file, render_template_string

app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

STREAMTAPE_DEFAULT_URL = "https://streamtape.com/v/0A2vDYQz3wIbPQ6/"
VIDARA_DEFAULT_URL = "https://vidara.to/v/d932127894f1"

# Audio Tracks for HLS Master Playlist & Player
DEFAULT_AUDIO_TRACKS = [
    {
        "id": "original",
        "name": "Original Audio (Fast)",
        "language": "original",
        "default": True,
        "url": None
    },
    {
        "id": "hindi",
        "name": "Hindi (MS)",
        "language": "hindi-(ms)",
        "default": False,
        "url": "https://m696yefd.s1q2105.com//audio/jCpnus1evj/index.m3u8"
    },
    {
        "id": "telugu",
        "name": "Telugu (MS)",
        "language": "telugu-(ms)",
        "default": False,
        "url": "https://m696yefd.s1q2105.com//audio/sMFUCb6Pka/index.m3u8"
    }
]

# Domain lists matching CloudStream3 extractors (Vidara.kt & StreamTape.kt)
STREAMTAPE_DOMAINS = {
    "streamtape.com",
    "watchadsontape.com",
    "streamtape.net",
    "streamtape.xyz",
    "shavetape.cash",
}

VIDARA_DOMAINS = {
    "vidara.to",
    "vidavaca.net",
    "vidaarax.net",
    "vidaarax.com",
    "vidaratem.com",
    "vidaraw.com",
    "vidarax.cc",
    "vidaraa.cc",
    "vidara.so",
    "odysseusa.cc",
    "handfacesnap.cc",
    "namefacesnap.cc",
    "thebesthosterv.com",
    "thebesthostertv.com",
    "vidmatrixa.com",
    "vidchampions.com",
    "antarcticadocs.com",
    "nameitweb.com",
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def clean_id(val: str) -> str:
    if not val:
        return ""
    val = val.strip().replace("(id)", "").replace("%28id%29", "")
    if "://" in val:
        val = val.rstrip("/").split("/")[-1].split("?")[0]
    return re.sub(r"[^a-zA-Z0-9_\-]", "", val)

def parse_ids_from_string(s: str) -> tuple[str, str]:
    """Extract st_id and va_id from any string format."""
    s = urllib.parse.unquote(s or "")
    st_id = ""
    va_id = ""

    # Check for streamtape id
    m_st = re.search(r"(?:st\?play=|\bst/|/st/|[?&]st=|[?&]play=)([^/&?#\s]+)", s, re.IGNORECASE)
    if m_st:
        st_id = clean_id(m_st.group(1))
    else:
        m_st_full = re.search(r"streamtape\.com/v/([a-zA-Z0-9_\-]+)", s, re.IGNORECASE)
        if m_st_full:
            st_id = clean_id(m_st_full.group(1))

    # Check for vidara id
    m_va = re.search(r"(?:va\?playd=|\bva/|/va/|[?&]va=|[?&]playd=)([^/&?#\s]+)", s, re.IGNORECASE)
    if m_va:
        va_id = clean_id(m_va.group(1))
    else:
        m_va_full = re.search(r"vidara\.to/v/([a-zA-Z0-9_\-]+)", s, re.IGNORECASE)
        if m_va_full:
            va_id = clean_id(m_va_full.group(1))

    return st_id, va_id

def extract_vidara(url_or_id: str) -> dict:
    import requests
    if "://" in url_or_id:
        parsed = urllib.parse.urlparse(url_or_id)
        main_url = f"{parsed.scheme or 'https'}://{parsed.netloc}"
        file_code = parsed.path.rstrip("/").split("/")[-1].split("?")[0]
    else:
        main_url = "https://vidara.to"
        file_code = clean_id(url_or_id)

    api_url = f"{main_url}/api/stream"
    payload = {
        "filecode": file_code,
        "device": "web"
    }

    resp = requests.post(api_url, json=payload, headers=DEFAULT_HEADERS, timeout=12)
    resp.raise_for_status()
    data = resp.json()

    streaming_url = data.get("streaming_url", "")
    title = data.get("title", "")
    thumbnail = data.get("thumbnail")
    subtitles = data.get("subtitles")

    return {
        "status": "success",
        "source": "Secondary Server",
        "original_url": f"/v/{file_code}",
        "url": streaming_url,
        "text": title,
        "title": title,
        "thumbnail": thumbnail,
        "subtitles": subtitles,
        "stream_type": "m3u8" if streaming_url.endswith(".m3u8") else "direct",
    }

def eval_streamtape_js(expr: str) -> str:
    try:
        res = subprocess.check_output(
            ["node", "-p", expr],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL
        ).strip()
        if res:
            return res
    except Exception:
        pass

    token_re = re.compile(r"['\"]([^'\"]*)['\"]((?:\.substring\(\s*\d+\s*(?:,\s*\d+\s*)?\))*)")
    parts = []
    for s, subs in token_re.findall(expr):
        val = s
        for sub_call in re.finditer(r"\.substring\((\d+)(?:,\s*(\d+))?\)", subs):
            start = int(sub_call.group(1))
            end = int(sub_call.group(2)) if sub_call.group(2) else len(val)
            val = val[start:end]
        parts.append(val)
    return "".join(parts)

def extract_streamtape(url_or_id: str) -> dict:
    import requests
    if "://" in url_or_id:
        url = url_or_id
    else:
        clean = clean_id(url_or_id)
        url = f"https://streamtape.com/v/{clean}/"

    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
    resp.raise_for_status()
    html = resp.text

    title = ""
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw_title = title_match.group(1).strip()
        title = re.sub(r"\s+at\s+Streamtape\.com.*$", "", raw_title, flags=re.IGNORECASE).strip()

    match = re.search(r"botlink[\x27\x22]\)\.innerHTML\s*=\s*([^;]+);", html)
    if not match:
        match = re.search(r"getElementById\(['\"](?:no)?robotlink['\"]\)\.innerHTML\s*=\s*([^;]+);", html)

    if not match:
        raise ValueError("Could not find media stream token in HTML")

    expr = match.group(1).strip()
    eval_result = eval_streamtape_js(expr)
    if not eval_result:
        raise ValueError("Failed to evaluate media script token")

    if eval_result.startswith("//"):
        stream_url = f"https:{eval_result}&stream=1"
    elif eval_result.startswith("http"):
        stream_url = f"{eval_result}&stream=1"
    else:
        stream_url = f"https://{eval_result}&stream=1"

    return {
        "status": "success",
        "source": "Primary Server",
        "original_url": f"/v/{clean}",
        "url": stream_url,
        "text": title,
        "title": title,
        "stream_type": "mp4",
    }

def extract_any(url: str) -> dict:
    url = url.strip()
    if not url:
        raise ValueError("URL parameter cannot be empty")
    
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.lower()
    if ":" in domain:
        domain = domain.split(":")[0]

    if any(domain == d or domain.endswith("." + d) for d in VIDARA_DOMAINS) or "vidara" in domain:
        return extract_vidara(url)

    if any(domain == d or domain.endswith("." + d) for d in STREAMTAPE_DOMAINS) or "streamtape" in domain:
        return extract_streamtape(url)

    if "/api/stream" in url or "/v/" in url:
        try:
            return extract_vidara(url)
        except Exception:
            return extract_streamtape(url)

    raise ValueError(f"Unsupported host/domain '{domain}'.")

# --- STATIC FILE ROUTES ---

@app.route("/hls.min.js", methods=["GET"])
def serve_hls_js():
    js_path = os.path.join(os.path.dirname(__file__), "hls.min.js")
    if os.path.exists(js_path):
        return send_file(js_path, mimetype="application/javascript")
    return Response("// HLS not cached locally", mimetype="application/javascript")

# --- HTML PLAYER ROUTES ---

@app.route("/player.html", defaults={"subpath": ""}, methods=["GET"])
@app.route("/player.html/<path:subpath>", methods=["GET"])
def serve_player(subpath=""):
    player_path = os.path.join(os.path.dirname(__file__), "player.html")
    if os.path.exists(player_path):
        return send_file(player_path, mimetype="text/html")
    return "player.html not found", 404

@app.route("/player", defaults={"subpath": ""}, methods=["GET"])
@app.route("/player/<path:subpath>", methods=["GET"])
def serve_player_alias(subpath=""):
    return serve_player(subpath)

# --- RESOLVER API ---

@app.route("/api/resolve", defaults={"subpath": ""}, methods=["GET", "POST"])
@app.route("/api/resolve/<path:subpath>", methods=["GET", "POST"])
def api_resolve(subpath=""):
    """Resolves both StreamTape and Vidara streams in parallel with automatic fallback."""
    full_uri = request.full_path or request.url
    st_parsed, va_parsed = parse_ids_from_string(full_uri)

    st_input = st_parsed
    va_input = va_parsed

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        st_input = st_input or data.get("st") or data.get("play")
        va_input = va_input or data.get("va") or data.get("playd")
    else:
        st_input = st_input or request.args.get("st")
        va_input = va_input or request.args.get("va")

    # Clean IDs
    st_input = clean_id(st_input) if st_input else ""
    va_input = clean_id(va_input) if va_input else ""

    # Defaults if completely empty
    if not st_input and not va_input:
        st_input = "0A2vDYQz3wIbPQ6"
        va_input = "d932127894f1"

    st_res = None
    va_res = None

    def fetch_st(sid):
        try:
            return extract_streamtape(sid)
        except Exception as e:
            return {"status": "error", "error": str(e), "id": sid}

    def fetch_va(vid):
        try:
            return extract_vidara(vid)
        except Exception as e:
            return {"status": "error", "error": str(e), "id": vid}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_st = executor.submit(fetch_st, st_input) if st_input else None
        f_va = executor.submit(fetch_va, va_input) if va_input else None
        if f_st:
            st_res = f_st.result()
        if f_va:
            va_res = f_va.result()

    st_ok = st_res and st_res.get("status") == "success" and bool(st_res.get("url"))
    va_ok = va_res and va_res.get("status") == "success" and bool(va_res.get("url"))

    if st_ok and va_ok:
        mode = "dual"
    elif st_ok:
        mode = "primary_only"
    elif va_ok:
        mode = "secondary_only"
    else:
        mode = "none"

    thumb = (va_res or {}).get("thumbnail") or (st_res or {}).get("thumbnail")
    subs = (va_res or {}).get("subtitles") or []

    return jsonify({
        "status": "success" if (st_ok or va_ok) else "error",
        "mode": mode,
        "st_id": st_input,
        "va_id": va_input,
        "primary": st_res,
        "secondary": va_res,
        "st": st_res,
        "va": va_res,
        "thumbnail": thumb,
        "subtitles": subs,
        "audio_tracks": DEFAULT_AUDIO_TRACKS
    })

# --- HLS MASTER PLAYLIST WITH MULTI-AUDIO TRACKS ---

@app.route("/playlist.m3u8", methods=["GET"])
@app.route("/api/playlist.m3u8", methods=["GET"])
def serve_master_playlist():
    va_id = request.args.get("va") or "d932127894f1"
    video_m3u8 = "https://s13-25t.s1q2105.com/hls/XllfQzImUDsHoOts9WN4Bo8BhuzGNx8T/index_1998x1080.m3u8"
    try:
        va_res = extract_vidara(va_id)
        if va_res.get("url"):
            # If the url is master.m3u8, get sub playlist or direct url
            va_url = va_res["url"]
            if va_url.endswith("master.m3u8"):
                video_m3u8 = va_url.replace("master.m3u8", "index_1998x1080.m3u8")
            else:
                video_m3u8 = va_url
    except Exception:
        pass

    manifest = f"""#EXTM3U
#EXT-X-VERSION:6

# Audio Track 1: Hindi (MS)
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Hindi (MS)",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="hindi-(ms)",URI="https://m696yefd.s1q2105.com//audio/jCpnus1evj/index.m3u8"
# Audio Track 2: Telugu (MS)
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Telugu (MS)",DEFAULT=NO,AUTOSELECT=YES,LANGUAGE="telugu-(ms)",URI="https://m696yefd.s1q2105.com//audio/sMFUCb6Pka/index.m3u8"

# Video Stream
#EXT-X-STREAM-INF:BANDWIDTH=5000000,AVERAGE-BANDWIDTH=5000000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1998x1080,FRAME-RATE=30.000,AUDIO="audio"
{video_m3u8}
"""
    return Response(manifest, mimetype="application/vnd.apple.mpegurl")

# --- EXISTING ENDPOINTS ---

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "port": 4447, "service": "stream-extractor-backend"})

@app.route("/api/extract", methods=["GET", "POST"])
def api_extract():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        url = data.get("url") or request.form.get("url")
    else:
        url = request.args.get("url")

    if not url:
        return jsonify({"status": "error", "message": "Missing 'url' parameter"}), 400

    format_type = request.args.get("format", "").lower()
    accept_header = request.headers.get("Accept", "")

    try:
        result = extract_any(url)
        if format_type == "text" or "text/plain" in accept_header:
            plain = f"Text: {result.get('text')}\nURL: {result.get('url')}\n"
            return Response(plain, mimetype="text/plain")
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "url": url}), 500

@app.route("/api/streamtape", methods=["GET"])
def api_streamtape():
    format_type = request.args.get("format", "").lower()
    accept_header = request.headers.get("Accept", "")
    try:
        result = extract_streamtape(STREAMTAPE_DEFAULT_URL)
        if format_type == "text" or "text/plain" in accept_header:
            return Response(f"Text: {result.get('text')}\nURL: {result.get('url')}\n", mimetype="text/plain")
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/vidara", methods=["GET"])
def api_vidara():
    format_type = request.args.get("format", "").lower()
    accept_header = request.headers.get("Accept", "")
    try:
        result = extract_vidara(VIDARA_DEFAULT_URL)
        if format_type == "text" or "text/plain" in accept_header:
            return Response(f"Text: {result.get('text')}\nURL: {result.get('url')}\n", mimetype="text/plain")
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/text/streamtape", methods=["GET"])
def text_streamtape():
    try:
        result = extract_streamtape(STREAMTAPE_DEFAULT_URL)
        return Response(f"Text: {result.get('text')}\nURL: {result.get('url')}\n", mimetype="text/plain")
    except Exception as e:
        return Response(f"Error: {e}\n", status=500, mimetype="text/plain")

@app.route("/text/vidara", methods=["GET"])
def text_vidara():
    try:
        result = extract_vidara(VIDARA_DEFAULT_URL)
        return Response(f"Text: {result.get('text')}\nURL: {result.get('url')}\n", mimetype="text/plain")
    except Exception as e:
        return Response(f"Error: {e}\n", status=500, mimetype="text/plain")

# Web index page redirects or serves tester dashboard
@app.route("/", methods=["GET"])
def index():
    return serve_player()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4447))
    print(f"[*] Starting Stream Extractor Backend on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
