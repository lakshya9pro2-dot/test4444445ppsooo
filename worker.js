/**
 * Cloudflare Worker: Stream resolver + proxy
 *
 * Why the Worker resolves AND proxies: Streamtape links are locked to the IP that
 * requested them. Here the same Worker fetches the page and the video, so the IP matches.
 *
 * Env (Settings -> Variables):
 *   ORIGIN        e.g. https://test4444445ppsooo.onrender.com   (serves player.html + hls.min.js)
 *   PROXY_SECRET  any long random string (Secret) - signs proxy links so this is not an open proxy
 *
 * Routes:
 *   /                          HTML player (fetched from ORIGIN, links rewritten to this Worker)
 *   /api/link?st=ID&va=ID      -> JSON with the shareable html_link (add &format=text for plain text)
 *   /api/resolve?st=ID&va=ID   -> same JSON as the Python app, but every url is a Worker proxy url
 *   /p/st/<id>                 -> Streamtape mp4 (Range/seek supported)
 *   /p/hls?u=..&s=..           -> HLS playlists (rewritten) + segments
 *   /playlist.m3u8?va=ID       -> master playlist with multi audio, proxied
 *   /health                    -> ok
 *   anything else              -> passed through to ORIGIN
 */

const UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
const BROWSER_HEADERS = {
  "User-Agent": UA,
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.5",
};

const DEFAULT_ST = "0A2vDYQz3wIbPQ6";
const DEFAULT_VA = "d932127894f1";

const AUDIO_TRACKS = [
  { id: "original", name: "Original Audio (Fast)", language: "original", default: true, url: null },
  { id: "hindi", name: "Hindi (MS)", language: "hindi-(ms)", default: false, url: "https://m696yefd.s1q2105.com//audio/jCpnus1evj/index.m3u8" },
  { id: "telugu", name: "Telugu (MS)", language: "telugu-(ms)", default: false, url: "https://m696yefd.s1q2105.com//audio/sMFUCb6Pka/index.m3u8" },
];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
};

const log = (msg, extra) => console.log(`[extractor] ${msg}`, extra !== undefined ? JSON.stringify(extra) : "");

/* ----------------------------- helpers ----------------------------- */

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

function cleanId(val) {
  if (!val) return "";
  val = String(val).trim().replace("(id)", "").replace("%28id%29", "");
  if (val.includes("://")) val = val.replace(/\/+$/, "").split("/").pop().split("?")[0];
  return val.replace(/[^a-zA-Z0-9_\-]/g, "");
}

function parseIds(str) {
  let s;
  try { s = decodeURIComponent(str || ""); } catch { s = str || ""; }
  let st = "", va = "", m;

  m = s.match(/(?:st\?play=|\bst\/|\/st\/|[?&]st=|[?&]play=)([^/&?#\s]+)/i);
  if (m) st = cleanId(m[1]);
  else if ((m = s.match(/streamtape\.com\/v\/([a-zA-Z0-9_\-]+)/i))) st = cleanId(m[1]);

  m = s.match(/(?:va\?playd=|\bva\/|\/va\/|[?&]va=|[?&]playd=)([^/&?#\s]+)/i);
  if (m) va = cleanId(m[1]);
  else if ((m = s.match(/vidara\.to\/v\/([a-zA-Z0-9_\-]+)/i))) va = cleanId(m[1]);

  return [st, va];
}

/* --------------------- signing (prevents open proxy) --------------------- */

let _key = null;
async function hmacKey(env) {
  if (!env.PROXY_SECRET) throw new Error("PROXY_SECRET is not set on the Worker");
  if (!_key) {
    _key = crypto.subtle.importKey("raw", new TextEncoder().encode(env.PROXY_SECRET),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  }
  return _key;
}

async function sign(env, value) {
  const sig = await crypto.subtle.sign("HMAC", await hmacKey(env), new TextEncoder().encode(value));
  return [...new Uint8Array(sig)].slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function verify(env, value, sig) {
  const expected = await sign(env, value);
  if (!sig || sig.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ sig.charCodeAt(i);
  return diff === 0;
}

async function hlsProxyUrl(origin, env, target) {
  return `${origin}/p/hls?u=${encodeURIComponent(target)}&s=${await sign(env, target)}`;
}

/* ----------------------------- Streamtape ----------------------------- */

// Workers cannot eval(), so evaluate the "'str'+('str').substring(n)" token safely by hand.
function evalToken(expr) {
  const tokenRe = /(['"])((?:(?!\1).)*)\1\s*\)?((?:\.substring\(\s*\d+\s*(?:,\s*\d+\s*)?\)\s*)*)/g;
  let out = "";
  for (const m of expr.matchAll(tokenRe)) {
    let val = m[2];
    for (const sub of m[3].matchAll(/\.substring\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)/g)) {
      const start = parseInt(sub[1], 10);
      const end = sub[2] !== undefined ? parseInt(sub[2], 10) : val.length;
      val = val.substring(start, end);
    }
    out += val;
  }
  return out;
}

async function resolveStreamtape(idOrUrl) {
  const id = cleanId(idOrUrl);
  const pageUrl = `https://streamtape.com/v/${id}/`;
  log("Streamtape: GET", pageUrl);
  const res = await fetch(pageUrl, { headers: BROWSER_HEADERS });
  const html = await res.text();
  log("Streamtape: page", { status: res.status, bytes: html.length });
  if (!res.ok) {
    log("Streamtape: HTTP error (Cloudflare IP may be blocked)", html.slice(0, 300));
    throw new Error(`Streamtape page HTTP ${res.status}`);
  }

  let title = "";
  const tm = html.match(/<title>([\s\S]*?)<\/title>/i);
  if (tm) title = tm[1].trim().replace(/\s+at\s+Streamtape\.com.*$/i, "").trim();

  let m = html.match(/botlink['"]\)\.innerHTML\s*=\s*([^;]+);/) ||
          html.match(/getElementById\(['"](?:no)?robotlink['"]\)\.innerHTML\s*=\s*([^;]+);/);
  if (!m) {
    log("Streamtape: token not found", { botlink: html.includes("botlink"), captcha: /captcha/i.test(html), head: html.slice(0, 300) });
    throw new Error("Could not find media stream token in HTML");
  }

  const evaluated = evalToken(m[1].trim());
  if (!evaluated) throw new Error("Failed to evaluate media script token");

  let url;
  if (evaluated.startsWith("//")) url = `https:${evaluated}&stream=1`;
  else if (evaluated.startsWith("http")) url = `${evaluated}&stream=1`;
  else url = `https://${evaluated}&stream=1`;

  log("Streamtape: resolved OK", { id });
  return { id, title, url };
}

async function handleStreamtapeStream(request, id) {
  const { url } = await resolveStreamtape(id);
  const headers = { "User-Agent": UA, "Referer": "https://streamtape.com/", "Accept": "*/*" };
  const range = request.headers.get("Range");
  if (range) headers["Range"] = range;

  const up = await fetch(url, { method: request.method === "HEAD" ? "HEAD" : "GET", headers, redirect: "follow" });
  log("Streamtape: media upstream", { status: up.status, type: up.headers.get("Content-Type"), len: up.headers.get("Content-Length"), range });

  if (up.status >= 400) {
    const body = await up.text();
    log("Streamtape: media upstream error", body.slice(0, 200));
    return json({ status: up.status, msg: "Upstream refused", detail: body.slice(0, 200) }, up.status);
  }

  const h = new Headers(CORS);
  for (const k of ["Content-Length", "Content-Range", "Accept-Ranges"]) {
    if (up.headers.get(k)) h.set(k, up.headers.get(k));
  }
  if (!h.has("Accept-Ranges")) h.set("Accept-Ranges", "bytes");
  let ctype = up.headers.get("Content-Type") || "video/mp4";
  if (ctype.includes("text/html")) ctype = "video/mp4";
  h.set("Content-Type", ctype);
  return new Response(up.body, { status: up.status, headers: h });
}

/* ------------------------------- Vidara ------------------------------- */

async function resolveVidara(idOrUrl) {
  let main = "https://vidara.to";
  let code;
  if (idOrUrl.includes("://")) {
    const u = new URL(idOrUrl);
    main = u.origin;
    code = u.pathname.replace(/\/+$/, "").split("/").pop();
  } else {
    code = cleanId(idOrUrl);
  }
  log("Vidara: POST", { main, code });
  const res = await fetch(`${main}/api/stream`, {
    method: "POST",
    headers: { ...BROWSER_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ filecode: code, device: "web" }),
  });
  const text = await res.text();
  log("Vidara: response", { status: res.status, bytes: text.length });
  if (!res.ok) {
    log("Vidara: HTTP error", text.slice(0, 300));
    throw new Error(`Vidara API HTTP ${res.status}`);
  }
  const data = JSON.parse(text);
  if (!data.streaming_url) {
    log("Vidara: no streaming_url", Object.keys(data));
    throw new Error("Vidara returned no streaming_url");
  }
  return {
    id: code,
    title: data.title || "",
    url: data.streaming_url,
    thumbnail: data.thumbnail || null,
    subtitles: data.subtitles || null,
  };
}

/* ------------------------------ HLS proxy ------------------------------ */

async function rewritePlaylist(text, baseUrl, origin, env) {
  const out = [];
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (!t) { out.push(line); continue; }
    if (t.startsWith("#")) {
      let newLine = line;
      for (const m of [...line.matchAll(/URI="([^"]+)"/g)]) {
        const abs = new URL(m[1], baseUrl).toString();
        const prox = await hlsProxyUrl(origin, env, abs);
        newLine = newLine.replace(m[0], () => `URI="${prox}"`);
      }
      out.push(newLine);
    } else {
      out.push(await hlsProxyUrl(origin, env, new URL(t, baseUrl).toString()));
    }
  }
  return out.join("\n");
}

async function handleHls(request, env, url) {
  const target = url.searchParams.get("u") || "";
  const sig = url.searchParams.get("s") || "";
  if (!target || !(await verify(env, target, sig))) {
    log("hls: bad signature", target.slice(0, 80));
    return json({ status: 403, msg: "Bad signature" }, 403);
  }

  const headers = { "User-Agent": UA, "Referer": "https://vidara.to/", "Accept": "*/*" };
  const range = request.headers.get("Range");
  if (range) headers["Range"] = range;

  const up = await fetch(target, { method: request.method === "HEAD" ? "HEAD" : "GET", headers, redirect: "follow" });
  const ctype = up.headers.get("Content-Type") || "";
  log("hls: upstream", { status: up.status, type: ctype, target: target.slice(0, 100) });

  if (up.status >= 400) {
    const body = await up.text();
    log("hls: upstream error", body.slice(0, 200));
    return json({ status: up.status, msg: "Upstream refused", detail: body.slice(0, 200) }, up.status);
  }

  const isPlaylist = /mpegurl/i.test(ctype) || new URL(up.url || target).pathname.endsWith(".m3u8");
  if (isPlaylist && request.method !== "HEAD") {
    const text = await up.text();
    const body = text.trimStart().startsWith("#EXTM3U")
      ? await rewritePlaylist(text, up.url || target, url.origin, env)
      : text;
    return new Response(body, {
      status: 200,
      headers: { "Content-Type": "application/vnd.apple.mpegurl", "Cache-Control": "no-store", ...CORS },
    });
  }

  const h = new Headers(CORS);
  for (const k of ["Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"]) {
    if (up.headers.get(k)) h.set(k, up.headers.get(k));
  }
  return new Response(up.body, { status: up.status, headers: h });
}

async function handleMasterPlaylist(env, url) {
  const va = cleanId(url.searchParams.get("va")) || DEFAULT_VA;
  let video = "https://s13-25t.s1q2105.com/hls/XllfQzImUDsHoOts9WN4Bo8BhuzGNx8T/index_1998x1080.m3u8";
  try {
    const r = await resolveVidara(va);
    video = r.url.endsWith("master.m3u8") ? r.url.replace("master.m3u8", "index_1998x1080.m3u8") : r.url;
  } catch (e) {
    log("playlist: vidara lookup failed, using fallback", String(e));
  }
  const o = url.origin;
  const hi = await hlsProxyUrl(o, env, AUDIO_TRACKS[1].url);
  const te = await hlsProxyUrl(o, env, AUDIO_TRACKS[2].url);
  const vid = await hlsProxyUrl(o, env, video);
  const manifest = `#EXTM3U
#EXT-X-VERSION:6

#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Hindi (MS)",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="hindi-(ms)",URI="${hi}"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Telugu (MS)",DEFAULT=NO,AUTOSELECT=YES,LANGUAGE="telugu-(ms)",URI="${te}"

#EXT-X-STREAM-INF:BANDWIDTH=5000000,AVERAGE-BANDWIDTH=5000000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1998x1080,FRAME-RATE=30.000,AUDIO="audio"
${vid}
`;
  return new Response(manifest, {
    headers: { "Content-Type": "application/vnd.apple.mpegurl", "Cache-Control": "no-store", ...CORS },
  });
}

/* ------------------------------ /api/resolve ------------------------------ */

async function readIds(request, url) {
  let [st, va] = parseIds(url.pathname + url.search);
  if (request.method === "POST") {
    const data = await request.json().catch(() => ({}));
    st = st || data.st || data.play;
    va = va || data.va || data.playd;
  } else {
    st = st || url.searchParams.get("st");
    va = va || url.searchParams.get("va");
  }
  st = st ? cleanId(st) : "";
  va = va ? cleanId(va) : "";
  return [st, va];
}

async function handleResolve(request, env, url) {
  let [st, va] = await readIds(request, url);
  if (!st && !va) { st = DEFAULT_ST; va = DEFAULT_VA; }
  log("resolve", { st, va });

  const safe = async (fn, id) => {
    try { return await fn(id); }
    catch (e) { log("resolve: failed", { id, error: String(e) }); return { status: "error", error: String(e), id }; }
  };
  const [stRaw, vaRaw] = await Promise.all([
    st ? safe(resolveStreamtape, st) : null,
    va ? safe(resolveVidara, va) : null,
  ]);

  const o = url.origin;
  let stRes = stRaw, vaRes = vaRaw;

  if (stRaw && !stRaw.status) {
    stRes = {
      status: "success", source: "Primary Server", original_url: `/v/${stRaw.id}`,
      url: `${o}/p/st/${stRaw.id}`, text: stRaw.title, title: stRaw.title, stream_type: "mp4",
    };
  }
  if (vaRaw && !vaRaw.status) {
    vaRes = {
      status: "success", source: "Secondary Server", original_url: `/v/${vaRaw.id}`,
      url: await hlsProxyUrl(o, env, vaRaw.url), text: vaRaw.title, title: vaRaw.title,
      thumbnail: vaRaw.thumbnail, subtitles: vaRaw.subtitles, stream_type: "m3u8",
    };
  }

  const stOk = stRes?.status === "success" && !!stRes.url;
  const vaOk = vaRes?.status === "success" && !!vaRes.url;
  const mode = stOk && vaOk ? "dual" : stOk ? "primary_only" : vaOk ? "secondary_only" : "none";
  log("resolve: mode", mode);

  const audio_tracks = [];
  for (const t of AUDIO_TRACKS) {
    audio_tracks.push({ ...t, url: t.url ? await hlsProxyUrl(o, env, t.url) : null });
  }

  return json({
    status: stOk || vaOk ? "success" : "error",
    mode, st_id: st, va_id: va,
    primary: stRes, secondary: vaRes, st: stRes, va: vaRes,
    thumbnail: vaRes?.thumbnail || stRes?.thumbnail || null,
    subtitles: vaRes?.subtitles || [],
    audio_tracks,
  });
}

/* ------------------------------ /api/link ------------------------------ */

async function handleLink(request, url) {
  const [st, va] = await readIds(request, url);
  const qs = [st && `st=${st}`, va && `va=${va}`].filter(Boolean).join("&");
  const link = `${url.origin}/${qs ? "?" + qs : ""}`;
  if ((url.searchParams.get("format") || "").toLowerCase() === "text") {
    return new Response(link + "\n", { headers: { "Content-Type": "text/plain", ...CORS } });
  }
  return json({ status: "success", html_link: link, st_id: st, va_id: va });
}

/* ------------------------- pass-through to ORIGIN ------------------------- */

async function passToOrigin(request, env, url) {
  if (!env.ORIGIN) return new Response("ORIGIN variable is not set on the Worker", { status: 500 });
  const origin = env.ORIGIN.replace(/\/+$/, "");
  const target = origin + url.pathname + url.search;
  log("passthrough", target);
  const up = await fetch(new Request(target, request));
  const ctype = up.headers.get("Content-Type") || "";
  if (/text\/html|javascript/i.test(ctype)) {
    // If the player hardcodes the Render URL, point it at this Worker instead
    const text = (await up.text()).split(origin).join(url.origin);
    const h = new Headers(up.headers);
    h.delete("Content-Length");
    return new Response(text, { status: up.status, headers: h });
  }
  return up;
}

/* -------------------------------- router -------------------------------- */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const started = Date.now();
    try {
      if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

      let resp;
      if (path === "/health") resp = json({ status: "ok", service: "stream-proxy-worker" });
      else if (path.startsWith("/api/resolve")) resp = await handleResolve(request, env, url);
      else if (path === "/api/link") resp = await handleLink(request, url);
      else if (path.startsWith("/p/st/")) resp = await handleStreamtapeStream(request, cleanId(path.slice(6)));
      else if (path === "/p/hls") resp = await handleHls(request, env, url);
      else if (path === "/playlist.m3u8" || path === "/api/playlist.m3u8") resp = await handleMasterPlaylist(env, url);
      else resp = await passToOrigin(request, env, url);

      log(`${request.method} ${path}${url.search ? "?..." : ""} -> ${resp.status} (${Date.now() - started} ms)`);
      const out = new Response(resp.body, resp);
      for (const [k, v] of Object.entries(CORS)) if (!out.headers.has(k)) out.headers.set(k, v);
      return out;
    } catch (e) {
      log(`ERROR ${request.method} ${path}`, String(e && e.stack || e));
      return json({ status: "error", message: String(e && e.message || e) }, 500);
    }
  },
};
