from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import urllib.parse

app = FastAPI(
    title="Terabox Recursive Extraction API",
    description="Backend fetcher engine developed by M. Sufiyan Shaikhz (Darkened Coder)",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

def normalize_terabox_url(raw_url: str):
    match = re.search(r'(?:/s/|surl=)([A-Za-z0-9_-]+)', raw_url)
    if not match: return None, None, None
    extracted_id = match.group(1)
    surl = extracted_id[1:] if extracted_id.startswith('1') else extracted_id
    api_surl = f"1{surl}" if not surl.startswith('1') else surl
    clean_url = f"https://dm.terabox.com/sharing/link?surl={surl}&clearCache=1"
    return clean_url, surl, api_surl

# THE NEW RECURSIVE CRAWLER
def extract_folder_contents(session, js_token, pcf_token, surl, sign, timestamp, shareid, uk, current_dir="/", depth=0):
    # Vercel timeout protection: limit recursion to 3 folders deep
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
            # It's a folder, dive deeper!
            sub_dir = item.get("path")
            extracted_files.extend(extract_folder_contents(
                session, js_token, pcf_token, surl, sign, timestamp, shareid, uk, sub_dir, depth + 1
            ))
        else:
            # It's a file, collect it
            extracted_files.append({
                "dlink": item.get("dlink"),
                "filename": item.get("server_filename"),
                "size": item.get("size")
            })
            
    return extracted_files

def extract_dlink(share_url: str, ndus_cookie: str):
    clean_url, surl, api_surl = normalize_terabox_url(share_url)
    if not clean_url: return {"error": True, "detail": "Invalid Terabox URL format."}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    })
    session.cookies.set("ndus", ndus_cookie, domain=".terabox.com")

    try:
        page_resp = session.get(clean_url)
        js_token_match = re.search(r'fn%28%22([A-Fa-f0-9]+)%22%29', page_resp.text) or \
                         re.search(r'window\.jsToken\s*=\s*["\']([A-Fa-f0-9]+)["\']', page_resp.text) or \
                         re.search(r'"jsToken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)
        pcf_token_match = re.search(r'"pcftoken"\s*:\s*"([A-Fa-f0-9]+)"', page_resp.text)
        
        if not js_token_match: return {"error": True, "detail": "Could not find jsToken. Cookie might be invalid."}
        js_token, pcf_token = js_token_match.group(1), pcf_token_match.group(1) if pcf_token_match else ""

        info_resp = session.get(
            "https://dm.terabox.com/api/shorturlinfo",
            headers={"Referer": clean_url},
            params={"app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0", "jsToken": js_token, "pcftoken": pcf_token, "shorturl": api_surl, "root": "1"}
        ).json()
        
        if "sign" not in info_resp: return {"error": True, "detail": f"Signature rejected. Errno: {info_resp.get('errno', 'Unknown')}"}

        # Trigger the recursive folder crawler starting at the root directory
        all_files = extract_folder_contents(
            session, js_token, pcf_token, surl, 
            info_resp["sign"], info_resp["timestamp"], 
            info_resp["shareid"], info_resp["uk"], current_dir="/"
        )

        if not all_files: return {"error": True, "detail": "No downloadable files found in this link or folder."}

        return {"error": False, "files": all_files}

    except Exception as e:
        return {"error": True, "detail": f"Server crash: {str(e)}"}

@app.get("/api/fetch")
def fetch_terabox_media(url: str, ndus: str):
    result = extract_dlink(url, ndus)
    if result.get("error"): raise HTTPException(status_code=400, detail=result["detail"])
    
    proxy_base = "https://teraboxdl.janialexa610.workers.dev/"
    processed_files = []
    
    for file in result["files"]:
        raw_dlink = file.get("dlink")
        if raw_dlink:
            stream_url = f"{proxy_base}?video={urllib.parse.quote(raw_dlink)}&ndus={urllib.parse.quote(ndus)}"
            processed_files.append({
                "filename": file.get("filename"),
                "size": file.get("size"),
                "raw_dlink": raw_dlink,
                "stream_url": stream_url
            })
            
    return {"success": True, "developer": "Darkened Coder", "data": processed_files}
