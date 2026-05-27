from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import urllib.parse

app = FastAPI(
    title="Terabox Extraction API",
    description="Backend fetcher engine developed by M. Sufiyan Shaikhz (Darkened Coder)",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def normalize_terabox_url(raw_url: str):
    match = re.search(r'(?:/s/|surl=)([A-Za-z0-9_-]+)', raw_url)
    if not match:
        return None, None, None
        
    extracted_id = match.group(1)
    surl = extracted_id[1:] if extracted_id.startswith('1') else extracted_id
    api_surl = f"1{surl}" if not surl.startswith('1') else surl
    clean_url = f"https://dm.terabox.com/sharing/link?surl={surl}&clearCache=1"
    
    return clean_url, surl, api_surl

def extract_dlink(share_url: str, ndus_cookie: str):
    clean_url, surl, api_surl = normalize_terabox_url(share_url)
    
    if not clean_url:
        return {"error": True, "detail": "Invalid Terabox URL format."}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })
    session.cookies.set("ndus", ndus_cookie, domain=".terabox.com")

    try:
        # STEP 1: Smart Token Extraction (Checking multiple patterns)
        page_resp = session.get(clean_url)
        
        # Check Pattern A (URL Encoded)
        js_token_match = re.search(r'fn%28%22([A-Fa-f0-9]+)%22%29', page_resp.text)
        # Check Pattern B (Standard JS)
        if not js_token_match:
            js_token_match = re.search(r'window\.jsToken\s*=\s*["\']([A-Fa-f0-9]+)["\']', page_resp.text)
        # Check Pattern C (JSON Object)
        if not js_token_match:
            js_token_match = re.search(r'"jsToken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)

        pcf_token_match = re.search(r'"pcftoken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)
        
        if not js_token_match:
            return {"error": True, "detail": "Could not find jsToken. The HTML layout might have changed or cookie is invalid."}

        js_token = js_token_match.group(1)
        pcf_token = pcf_token_match.group(1) if pcf_token_match else ""

        # STEP 2: Fetch Signatures
        info_resp = session.get(
            "https://dm.terabox.com/api/shorturlinfo",
            headers={"Referer": clean_url},
            params={
                "app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0",
                "jsToken": js_token, "pcftoken": pcf_token, "shorturl": api_surl, "root": "1"
            }
        ).json()
        
        if "sign" not in info_resp:
            errno = info_resp.get("errno", "Unknown")
            return {"error": True, "detail": f"Terabox API rejected signature request. Errno: {errno}"}

        # STEP 3: Request Final Link
        list_resp = session.get(
            "https://dm.terabox.com/share/list",
            headers={"Referer": clean_url},
            params={
                "app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0",
                "jsToken": js_token, "pcftoken": pcf_token, "shorturl": surl, 
                "sign": info_resp["sign"], "timestamp": info_resp["timestamp"], 
                "shareid": info_resp["shareid"], "uk": info_resp["uk"], 
                "page": "1", "num": "20", "root": "1"
            }
        ).json()

        # Check if the list is empty (can happen with folders or restricted files)
        if "list" not in list_resp or not list_resp["list"]:
            errno = list_resp.get("errno", "Unknown")
            return {"error": True, "detail": f"No files found in payload. Errno: {errno}"}

        file_data = list_resp["list"][0]
        
        return {
            "error": False,
            "dlink": file_data.get("dlink"),
            "filename": file_data.get("server_filename"), 
            "size": file_data.get("size")
        }

    except Exception as e:
        return {"error": True, "detail": f"Server crash: {str(e)}"}

@app.get("/api/fetch")
def fetch_terabox_video(url: str, ndus: str):
    result = extract_dlink(url, ndus)
    
    if result.get("error"):
        # We now throw a 400 error but include the EXACT reason it failed
        raise HTTPException(status_code=400, detail=result["detail"])
        
    raw_dlink = result["dlink"]
    
    # ⚠️ REMEMBER TO PASTE YOUR CLOUDFLARE URL HERE ⚠️
    proxy_base = "https://teraboxdl.janialexa610.workers.dev/"
    stream_url = f"{proxy_base}?video={urllib.parse.quote(raw_dlink)}&ndus={urllib.parse.quote(ndus)}"
    
    return {
        "success": True,
        "developer": "Darkened Coder",
        "filename": result["filename"],
        "size": result["size"],
        "raw_dlink": raw_dlink,
        "stream_url": stream_url
    }
