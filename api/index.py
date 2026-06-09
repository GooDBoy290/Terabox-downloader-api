import re
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TeraBox Core Extraction Engine")

# Wire CORS to let your custom frontend communicate fluidly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TeraBoxRequest(BaseModel):
    url: str
    password: str = None

def clean_short_url(url: str) -> str:
    """Extracts the unique alphanumeric identifier from any TeraBox share URL format."""
    patterns = [
        r"s/([A-Za-z0-9_-]+)",
        r"surl=([A-Za-z0-9_-]+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return url.split("/")[-1]

# ─── THE ARCHITECT COOKIE STORAGE ───────────────────────────────────────────
# Paste your active 'ndus' session key extracted from your browser's Application tab here
NDUS_COOKIE = "YOUR_NDUS_COOKIE_HERE" 

def get_spoofed_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }

@app.post("/api/terabox")
async def extract_terabox_media(request: TeraBoxRequest):
    if not request.url:
        raise HTTPException(status_code=400, detail="Target share URL cannot be empty.")
        
    surl = clean_short_url(request.url)
    
    # Target endpoint for Meta-Listing API
    base_api_url = "https://www.terabox.com/share/list"
    
    params = {
        "app_id": "250528", # Default developer app id used by web clients
        "shorturl": surl,
        "root": "1"
    }
    
    if request.password:
        params["pwd"] = request.password

    cookies = {
        "ndus": NDUS_COOKIE
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await client.get(
                base_api_url, 
                params=params, 
                headers=get_spoofed_headers(), 
                cookies=cookies,
                timeout=15.0
            )
            
            if response.status_code != 200:
                raise ValueError(f"Upstream server rejected connection wrapper: {response.status_code}")
                
            payload = response.json()
            
            # Catch internal application errors returned as clean JSON
            if payload.get("errno") != 0:
                raise ValueError(f"TeraBox API Error Code {payload.get('errno')}: Verification failure or expired link.")

            file_list = payload.get("list", [])
            if not file_list:
                raise ValueError("The requested session returned an empty asset directory map.")

            # Target the structural data of the first identified item
            target_file = file_list[0]
            
            # Extract raw download links and clean the query strings down to direct CDNs
            raw_dlink = target_file.get("dlink", "")
            
            return {
                "success": True,
                "developer": "Darkened Coder",
                "meta": {
                    "filename": target_file.get("server_filename", "Unknown_File"),
                    "size_bytes": int(target_file.get("size", 0)),
                    "thumbnail": target_file.get("thumbs", {}).get("url3", "") or target_file.get("thumbs", {}).get("url1", ""),
                    "is_dir": bool(int(target_file.get("isdir", 0)))
                },
                "download_links": {
                    "direct_stream": raw_dlink,
                    "high_speed": raw_dlink.replace("api.terabox.com", "d.terabox.com") if raw_dlink else ""
                }
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Bypass routine collapsed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
