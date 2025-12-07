from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List
import asyncio
import httpx
import os
import logging
import re
from datetime import datetime, timedelta
import base64
from serpapi_pool import get_key, status as pool_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Pharmyrus API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Config:
    EPO_KEY = "G5wJypxeg0GXEJoMGP37tdK370aKxeMszGKAkD6QaR0yiR5X"
    EPO_SECRET = "zg5AJ0EDzXdJey3GaFNM8ztMVxHKXRrAihXH93iS5ZAzKPAPMFLuVUfiEuAqpdbz"
    INPI_URL = "https://crawler3-production.up.railway.app/api/data/inpi/patents"
    TIMEOUT = 30
    TIMEOUT_INPI = 60

_epo_token = None
_epo_token_expires = None

async def get_epo_token() -> Optional[str]:
    global _epo_token, _epo_token_expires
    now = datetime.now()
    if _epo_token and _epo_token_expires and now < _epo_token_expires:
        return _epo_token
    try:
        creds = f"{Config.EPO_KEY}:{Config.EPO_SECRET}"
        b64 = base64.b64encode(creds.encode()).decode()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://ops.epo.org/3.2/auth/accesstoken",
                headers={"Authorization": f"Basic {b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials"},
                timeout=Config.TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                _epo_token = data["access_token"]
                _epo_token_expires = now + timedelta(minutes=15)
                logger.info("✅ EPO token renewed")
                return _epo_token
    except Exception as e:
        logger.error(f"EPO error: {e}")
    return None

async def get_pubchem(molecule: str) -> Dict[str, Any]:
    try:
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{molecule}/synonyms/JSON"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=Config.TIMEOUT)
            if r.status_code != 200:
                return {"dev_codes": [], "cas": None}
            data = r.json()
            syns = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
            dev_codes = []
            cas = None
            for s in syns:
                if not s or len(s) > 20:
                    continue
                if re.match(r'^[A-Z]{2,5}[-\s]?\d{3,7}[A-Z]?$', s, re.I):
                    if s not in dev_codes:
                        dev_codes.append(s)
                if re.match(r'^\d{2,7}-\d{2}-\d$', s):
                    cas = s
            return {"dev_codes": dev_codes[:10], "cas": cas}
    except Exception as e:
        logger.error(f"PubChem error: {e}")
        return {"dev_codes": [], "cas": None}

async def search_inpi(molecule: str, dev_codes: List[str], cas: Optional[str]) -> List[Dict[str, Any]]:
    all_patents = []
    queries = [molecule, molecule.lower()]
    for code in dev_codes[:8]:
        queries.append(code)
    if cas:
        queries.append(cas)
    queries = queries[:10]
    try:
        async with httpx.AsyncClient() as client:
            for q in queries:
                try:
                    url = f"{Config.INPI_URL}?medicine={q}"
                    r = await client.get(url, timeout=Config.TIMEOUT_INPI)
                    if r.status_code == 200:
                        data = r.json()
                        patents = data.get("data", [])
                        if patents:
                            all_patents.extend(patents)
                    await asyncio.sleep(1)
                except:
                    continue
    except Exception as e:
        logger.error(f"INPI error: {e}")
    seen = set()
    unique = []
    for p in all_patents:
        pid = p.get("title", "").replace(" ", "")
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique

async def search_patents(molecule: str) -> Dict[str, Any]:
    start = datetime.now()
    logger.info(f"🔍 SEARCH: {molecule}")
    pubchem = await get_pubchem(molecule)
    dev_codes = pubchem["dev_codes"]
    cas = pubchem["cas"]
    inpi_patents = await search_inpi(molecule, dev_codes, cas)
    elapsed = (datetime.now() - start).total_seconds()
    return {
        "molecule": molecule,
        "dev_codes": dev_codes,
        "cas": cas,
        "patents": inpi_patents,
        "total": len(inpi_patents),
        "time": round(elapsed, 2)
    }

@app.get("/")
async def root():
    return {"status": "ok", "version": "4.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/api/v1/search")
async def search(molecule_name: str = Query(...)):
    try:
        result = await search_patents(molecule_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/serpapi/status")
async def serpapi_status():
    return JSONResponse(content=pool_status())

@app.get("/api/v1/serpapi/key")
async def serpapi_key():
    key = get_key()
    return {"key": key[:20] + "..." if key else None}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
