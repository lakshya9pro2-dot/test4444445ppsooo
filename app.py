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

def extract_audio_tracks_from_m3u(m3u_url: str) -> list[dict]:
    """Fetches master M3U in real-time and parses dynamic #EXT-X-MEDIA:TYPE=AUDIO tracks."""
    import requests
    if not m3u_url or not m3u_url.startswith("http"):
        return []
    try:
        resp = requests.get(m3u_url, headers=DEFAULT_HEADERS, timeout=8)
        if resp.status_code != 200:
            return []
        text = resp.text
        tracks = []
        seen = set()
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("#EXT-X-MEDIA:") or "TYPE=AUDIO" not in line:
                continue
            m_name = re.search(r'NAME="([^"]+)"', line, re.IGNORECASE)
            m_lang = re.search(r'LANGUAGE="([^"]+)"', line, re.IGNORECASE)
            m_uri = re.search(r'URI="([^"]+)"', line, re.IGNORECASE)
            m_def = re.search(r'DEFAULT=(YES|NO)', line, re.IGNORECASE)

            if not m_uri:
                continue

            uri = urllib.parse.urljoin(m3u_url, m_uri.group(1).strip())
            name = m_name.group(1).strip() if m_name else (m_lang.group(1).strip() if m_lang else "Audio Track")
            lang = m_lang.group(1).strip() if m_lang else ""
            is_default = bool(m_def and m_def.group(1).upper() == "YES")

            tid = f"{lang}|{name}|{uri}"
            if tid in seen:
                continue
            seen.add(tid)

            tracks.append({
                "id": re.sub(r"[^a-zA-Z0-9_\-]", "_", (lang or name).lower()),
                "name": name,
                "language": lang,
                "default": is_default,
                "url": uri
            })
        return tracks
    except Exception:
        return []

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

    # Real-time extraction of dynamic audio tracks from actual M3U
    dynamic_audio_tracks = []
    if streaming_url and ".m3u8" in streaming_url:
        dynamic_audio_tracks = extract_audio_tracks_from_m3u(streaming_url)

    return {
        "status": "success",
        "source": "Secondary Server",
        "original_url": f"/v/{file_code}",
        "url": streaming_url,
        "text": title,
        "title": title,
        "thumbnail": thumbnail,
        "subtitles": subtitles,
        "audio_tracks": dynamic_audio_tracks,
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
    clean = clean_id(url_or_id)
    if "://" in url_or_id:
        url = url_or_id
    else:
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

    # Follow HTTP 302 to read Location header and resolve direct TapeContent CDN URL
    tapecontent_url = None
    try:
        redirect_headers = {
            **DEFAULT_HEADERS,
            "Referer": url,
        }
        r_redir = requests.head(stream_url, headers=redirect_headers, allow_redirects=False, timeout=8)
        if r_redir.status_code in (301, 302, 303, 307, 308) and "Location" in r_redir.headers:
            tapecontent_url = r_redir.headers["Location"]
        elif r_redir.status_code == 200:
            tapecontent_url = r_redir.url
        else:
            r_redir_get = requests.get(stream_url, headers=redirect_headers, allow_redirects=False, stream=True, timeout=8)
            if r_redir_get.status_code in (301, 302, 303, 307, 308) and "Location" in r_redir_get.headers:
                tapecontent_url = r_redir_get.headers["Location"]
            r_redir_get.close()
    except Exception:
        pass

    final_url = tapecontent_url if tapecontent_url else stream_url
    proxy_url = f"/api/proxy/stream?url={urllib.parse.quote(final_url, safe='')}"

    return {
        "status": "success",
        "source": "Primary Server",
        "original_url": f"/v/{clean}",
        "url": proxy_url,
        "proxy_url": proxy_url,
        "direct_url": final_url,
        "tapecontent_url": tapecontent_url or final_url,
        "stream_url": stream_url,
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

# --- STREAM PROXY ROUTE (Solves StreamTape IP-lock 403 & CORS) ---

@app.route("/api/proxy/stream", methods=["GET", "HEAD", "OPTIONS"])
def proxy_stream():
    """Proxies media stream chunks from TapeContent so users on any IP can stream without 403 or CORS errors."""
    if request.method == "OPTIONS":
        return Response("", status=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        })

    target_url = request.args.get("url")
    if not target_url:
        return jsonify({"status": "error", "message": "Missing 'url' parameter"}), 400

    req_headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Accept": "*/*",
    }
    if "Range" in request.headers:
        req_headers["Range"] = request.headers["Range"]

    try:
        import requests
        method = requests.head if request.method == "HEAD" else requests.get
        upstream = method(
            target_url,
            headers=req_headers,
            stream=True,
            timeout=15,
            allow_redirects=True
        )

        resp_headers = []
        passthrough = ["content-range", "content-length", "content-type", "accept-ranges"]
        for k, v in upstream.headers.items():
            if k.lower() in passthrough:
                resp_headers.append((k, v))

        resp_headers.append(("Access-Control-Allow-Origin", "*"))
        resp_headers.append(("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS"))
        resp_headers.append(("Access-Control-Allow-Headers", "*"))
        resp_headers.append(("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges"))
        resp_headers.append(("Accept-Ranges", "bytes"))

        if request.method == "HEAD":
            return Response("", status=upstream.status_code, headers=resp_headers, mimetype=upstream.headers.get("content-type", "video/mp4"))

        def stream_chunks():
            try:
                for chunk in upstream.iter_content(chunk_size=128 * 1024):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        return Response(
            stream_chunks(),
            status=upstream.status_code,
            headers=resp_headers,
            mimetype=upstream.headers.get("content-type", "video/mp4")
        )
    except Exception as e:
        return Response(f"Proxy error: {str(e)}", status=502, mimetype="text/plain")

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

    # Dynamic audio tracks parsed directly from the stream's M3U in real-time
    dynamic_audio_tracks = (va_res or {}).get("audio_tracks") or []
    audio_tracks = [
        {
            "id": "original",
            "name": "Original Audio (Fast)",
            "language": "original",
            "default": True,
            "url": None
        }
    ] + dynamic_audio_tracks

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
        "audio_tracks": audio_tracks
    })

# --- HLS MASTER PLAYLIST (Proxies real-time M3U directly from upstream) ---

@app.route("/playlist.m3u8", methods=["GET"])
@app.route("/api/playlist.m3u8", methods=["GET"])
def serve_master_playlist():
    va_id = request.args.get("va") or "d932127894f1"
    try:
        va_res = extract_vidara(va_id)
        va_url = va_res.get("url")
        if va_url and va_url.startswith("http"):
            import requests
            resp = requests.get(va_url, headers=DEFAULT_HEADERS, timeout=10)
            if resp.status_code == 200:
                return Response(resp.text, mimetype="application/vnd.apple.mpegurl")
    except Exception:
        pass
    return Response("#EXTM3U\n#EXT-X-VERSION:6\n", mimetype="application/vnd.apple.mpegurl")

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
