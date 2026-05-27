from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import urllib.parse
import re

app = FastAPI(
    title="Terabox Extraction API",
    description="Backend fetcher engine developed by M. Sufiyan Shaikhz (Darkened Coder)",
    version="2.0"
)

# ⚠️ YOUR CLOUDFLARE WORKER URL GOES HERE ⚠️
CLOUDFLARE_PROXY_URL = "https://teraboxdl.janialexa610.workers.dev/"

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
        raise ValueError("Invalid Terabox URL format.")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    })
    session.cookies.set("ndus", ndus_cookie, domain=".terabox.com")

    try:
        # 1. Web Tokens
        page_resp = session.get(clean_url)
        js_token_match = re.search(r'fn%28%22([A-Fa-f0-9]+)%22%29', page_resp.text)
        pcf_token_match = re.search(r'"pcftoken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)
        
        if not js_token_match:
            return None

        js_token = js_token_match.group(1)
        pcf_token = pcf_token_match.group(1) if pcf_token_match else ""

        # 2. Signatures
        info_resp = session.get(
            "https://dm.terabox.com/api/shorturlinfo",
            headers={"Referer": clean_url},
            params={
                "app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0",
                "jsToken": js_token, "pcftoken": pcf_token, "shorturl": api_surl, "root": "1"
            }
        ).json()
        
        if "sign" not in info_resp:
            return None

        # 3. Request Direct Link
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

        file_data = list_resp["list"][0]
        
        return {
            "dlink": file_data.get("dlink"),
            "filename": file_data.get("server_filename"),
            "size": file_data.get("size")
        }

    except Exception as e:
        print(f"Extraction Exception: {e}")
        return None

@app.get("/api/fetch")
def fetch_terabox_video(url: str, ndus: str):
    try:
        result = extract_dlink(url, ndus)
        
        if result and result.get("dlink"):
            raw_dlink = result["dlink"]
            filename = result["filename"]
            
            # Formulate the safe Cloudflare Proxy URL
            encoded_dlink = urllib.parse.quote(raw_dlink)
            encoded_ndus = urllib.parse.quote(ndus)
            
            # The URL that will actually play in third-party web players
            stream_url = f"{CLOUDFLARE_PROXY_URL}/?video={encoded_dlink}&ndus={encoded_ndus}"

            return {
                "success": True,
                "developer": "Darkened Coder",
                "filename": filename,
                "size": result["size"],
                "raw_download_url": raw_dlink, 
                "stream_url": stream_url # This is the magic link that plays everywhere
            }
        else:
            raise HTTPException(status_code=400, detail="Extraction failed.")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
