from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
import requests
import httpx
import re
import urllib.parse
import asyncio

app = FastAPI(
    title="Terabox Recursive Extraction API",
    description="Backend fetcher engine developed by M. Sufiyan Shaikhz (Darkened Coder)",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Type"],
)

# ─────────────────────────────────────────────
#  DESKTOP USER-AGENT (matches token generation)
# ─────────────────────────────────────────────
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

CHUNK_SIZE = 1024 * 1024  # 1 MB chunks


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def normalize_terabox_url(raw_url: str):
    match = re.search(r'(?:/s/|surl=)([A-Za-z0-9_-]+)', raw_url)
    if not match:
        return None, None, None
    extracted_id = match.group(1)
    surl = extracted_id[1:] if extracted_id.startswith('1') else extracted_id
    api_surl = f"1{surl}" if not surl.startswith('1') else surl
    clean_url = f"https://dm.terabox.com/sharing/link?surl={surl}&clearCache=1"
    return clean_url, surl, api_surl


def _make_session(ndus_cookie: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": DESKTOP_UA,
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })
    session.cookies.set("ndus", ndus_cookie, domain=".terabox.com")
    return session


def extract_folder_contents(session, js_token, pcf_token, surl, sign, timestamp,
                             shareid, uk, current_dir="/", depth=0):
    if depth > 3:
        return []

    params = {
        "app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0",
        "jsToken": js_token, "pcftoken": pcf_token, "shorturl": surl,
        "sign": sign, "timestamp": timestamp,
        "shareid": shareid, "uk": uk,
        "page": "1", "num": "100",
        "dir": current_dir,
        "root": "1" if current_dir == "/" else "0"
    }

    resp = session.get("https://dm.terabox.com/share/list", params=params).json()
    items = resp.get("list", [])
    extracted_files = []

    for item in items:
        if str(item.get("isdir", "0")) == "1":
            sub_dir = item.get("path")
            extracted_files.extend(
                extract_folder_contents(
                    session, js_token, pcf_token, surl, sign, timestamp,
                    shareid, uk, sub_dir, depth + 1
                )
            )
        else:
            extracted_files.append({
                "dlink":    item.get("dlink"),
                "filename": item.get("server_filename"),
                "size":     item.get("size")
            })

    return extracted_files


def extract_dlink(share_url: str, ndus_cookie: str):
    clean_url, surl, api_surl = normalize_terabox_url(share_url)
    if not clean_url:
        return {"error": True, "detail": "Invalid Terabox URL format."}

    session = _make_session(ndus_cookie)

    try:
        page_resp = session.get(clean_url)
        js_token_match = (
            re.search(r'fn%28%22([A-Fa-f0-9]+)%22%29', page_resp.text) or
            re.search(r'window\.jsToken\s*=\s*["\']([A-Fa-f0-9]+)["\']', page_resp.text) or
            re.search(r'"jsToken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)
        )
        pcf_token_match = re.search(r'"pcftoken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)

        if not js_token_match:
            return {"error": True, "detail": "Could not find jsToken. Cookie might be invalid."}

        js_token  = js_token_match.group(1)
        pcf_token = pcf_token_match.group(1) if pcf_token_match else ""

        info_resp = session.get(
            "https://dm.terabox.com/api/shorturlinfo",
            headers={"Referer": clean_url},
            params={
                "app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0",
                "jsToken": js_token, "pcftoken": pcf_token,
                "shorturl": api_surl, "root": "1"
            }
        ).json()

        if "sign" not in info_resp:
            return {"error": True, "detail": f"Signature rejected. Errno: {info_resp.get('errno', 'Unknown')}"}

        all_files = extract_folder_contents(
            session, js_token, pcf_token, surl,
            info_resp["sign"], info_resp["timestamp"],
            info_resp["shareid"], info_resp["uk"],
            current_dir="/"
        )

        if not all_files:
            return {"error": True, "detail": "No downloadable files found in this link or folder."}

        return {"error": False, "files": all_files}

    except Exception as e:
        return {"error": True, "detail": f"Server crash: {str(e)}"}


# ─────────────────────────────────────────────
#  EXISTING FETCH ENDPOINT
# ─────────────────────────────────────────────
@app.get("/api/fetch")
def fetch_terabox_media(url: str, ndus: str):
    result = extract_dlink(url, ndus)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["detail"])

    processed_files = []
    for file in result["files"]:
        raw_dlink = file.get("dlink")
        if raw_dlink:
            # Build the internal proxy URL so mobile browsers always use the proxy
            stream_url = f"/api/stream?dlink={urllib.parse.quote(raw_dlink)}&ndus={urllib.parse.quote(ndus)}"
            processed_files.append({
                "filename":   file.get("filename"),
                "size":       file.get("size"),
                "raw_dlink":  raw_dlink,
                "stream_url": stream_url,   # ← always use the proxy
            })

    return {"success": True, "developer": "Darkened Coder", "data": processed_files}


# ─────────────────────────────────────────────
#  NEW: RANGE-AWARE STREAMING PROXY ENDPOINT
# ─────────────────────────────────────────────
@app.get("/api/stream")
@app.head("/api/stream")
async def stream_video(request: Request, dlink: str, ndus: str):
    """
    Mobile-compatible video streaming proxy.

    - Forwards the browser's Range header to TeraBox verbatim.
    - Spoofs a desktop User-Agent so TeraBox doesn't reject the token.
    - Streams data in 1 MB chunks — never buffers the full file.
    - Returns 206 Partial Content with correct Content-Range so iOS/Android
      seek bars and adaptive playback work natively.
    """
    decoded_dlink = urllib.parse.unquote(dlink)

    # Headers to forward upstream (desktop UA to match token origin)
    upstream_headers = {
        "User-Agent":      DESKTOP_UA,
        "Accept":          "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.terabox.com/",
        "Origin":          "https://www.terabox.com",
        "Sec-Fetch-Dest":  "video",
        "Sec-Fetch-Mode":  "cors",
        "Sec-Fetch-Site":  "cross-site",
        "Connection":      "keep-alive",
    }

    # Forward any Range header the mobile browser sent
    client_range = request.headers.get("range")
    if client_range:
        upstream_headers["Range"] = client_range

    # Cookie: ndus is the only one required for authenticated dlinks
    cookies = {"ndus": ndus}

    # ── HEAD request: return metadata without a body ──────────────────────
    if request.method == "HEAD":
        try:
            head_resp = requests.head(
                decoded_dlink,
                headers=upstream_headers,
                cookies=cookies,
                allow_redirects=True,
                timeout=15
            )
            response_headers = {
                "Accept-Ranges":  "bytes",
                "Content-Type":   head_resp.headers.get("Content-Type", "video/mp4"),
                "Content-Length": head_resp.headers.get("Content-Length", ""),
            }
            return Response(status_code=head_resp.status_code, headers=response_headers)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Upstream HEAD failed: {e}")

    # ── GET request: stream the video ─────────────────────────────────────
    try:
        upstream = requests.get(
            decoded_dlink,
            headers=upstream_headers,
            cookies=cookies,
            stream=True,          # critical: don't buffer in memory
            allow_redirects=True,
            timeout=30
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Could not reach TeraBox: {e}")

    # Propagate non-2xx errors cleanly
    if upstream.status_code not in (200, 206):
        raise HTTPException(
            status_code=upstream.status_code,
            detail=f"TeraBox returned HTTP {upstream.status_code}"
        )

    # ── Build response headers ────────────────────────────────────────────
    content_type   = upstream.headers.get("Content-Type", "video/mp4")
    content_length = upstream.headers.get("Content-Length")
    content_range  = upstream.headers.get("Content-Range")
    accept_ranges  = upstream.headers.get("Accept-Ranges", "bytes")

    response_headers = {
        "Accept-Ranges": accept_ranges,
        "Content-Type":  content_type,
        # Cache-Control: allow CDN/browser to cache segments aggressively
        "Cache-Control": "public, max-age=3600",
        # Required for cross-origin video playback on mobile
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
    }

    if content_length:
        response_headers["Content-Length"] = content_length
    if content_range:
        response_headers["Content-Range"] = content_range

    # Determine correct HTTP status code
    status_code = 206 if (client_range or upstream.status_code == 206) else 200

    # ── Async generator: stream 1 MB chunks lazily ───────────────────────
    def iter_chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        iter_chunks(),
        status_code=status_code,
        headers=response_headers,
        media_type=content_type,
    )
