from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import re

# Initialize the API with your professional branding
app = FastAPI(
    title="Terabox Extraction API",
    description="Backend fetcher engine developed by M. Sufiyan Shaikhz (Darkened Coder)",
    version="1.0"
)

# Allow your frontend web app to communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Change this to your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_dlink(share_url: str, ndus_cookie: str):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    })
    session.cookies.set("ndus", ndus_cookie, domain=".terabox.com")

    try:
        # 1. Parse URL
        surl_id = share_url.split("surl=")[-1] if "surl=" in share_url else share_url.split("/")[-1]
        api_surl = f"1{surl_id}" if not surl_id.startswith("1") else surl_id

        # 2. Get tokens
        page_resp = session.get(share_url)
        js_token_match = re.search(r'fn%28%22([A-Fa-f0-9]+)%22%29', page_resp.text)
        pcf_token_match = re.search(r'"pcftoken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)
        
        if not js_token_match:
            return None

        js_token = js_token_match.group(1)
        pcf_token = pcf_token_match.group(1) if pcf_token_match else ""

        # 3. Get Signatures
        info_resp = session.get(
            "https://dm.terabox.com/api/shorturlinfo",
            headers={"Referer": share_url},
            params={"app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0", "jsToken": js_token, "pcftoken": pcf_token, "shorturl": api_surl, "root": "1"}
        ).json()
        
        # 4. Get Final Link
        list_resp = session.get(
            "https://dm.terabox.com/share/list",
            params={"app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0", "jsToken": js_token, "pcftoken": pcf_token, "shorturl": surl_id, "sign": info_resp["sign"], "timestamp": info_resp["timestamp"], "shareid": info_resp["shareid"], "uk": info_resp["uk"], "page": "1", "num": "20", "root": "1"}
        ).json()

        return list_resp["list"][0]["dlink"]

    except Exception as e:
        print(f"Error: {e}")
        return None

# ==========================================
# API ENDPOINT
# ==========================================
@app.get("/api/fetch")
def fetch_terabox_video(url: str, ndus: str):
    """
    Pass the Terabox URL and your NDUS cookie as query parameters to get the direct stream link.
    """
    direct_link = extract_dlink(url, ndus)
    
    if direct_link:
        return {
            "success": True,
            "developer": "Darkened Coder",
            "dlink": direct_link
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to extract video link. Cookie might be invalid or IP blocked.")