from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List
import asyncio
import httpx
import os
import logging
import re
from datetime import datetime
from serpapi_pool import get_key, status as pool_status

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Pharmyrus API", version="4.2-FULL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Config:
    INPI_URL = "https://crawler3-production.up.railway.app/api/data/inpi/patents"
    TIMEOUT = 30
    TIMEOUT_INPI = 60

# =====================================================
# PUBCHEM COMPLETO
# =====================================================
async def get_pubchem_full(molecule: str) -> Dict[str, Any]:
    """Busca dados COMPLETOS do PubChem"""
    result = {
        "dev_codes": [],
        "cas": None,
        "iupac": None,
        "molecular_formula": None,
        "molecular_weight": None,
        "smiles": None,
        "inchi": None,
        "inchi_key": None,
        "synonyms": []
    }
    
    try:
        # 1. Buscar sinônimos (dev codes, CAS)
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{molecule}/synonyms/JSON"
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=Config.TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                syns = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
                
                for s in syns:
                    if not s or len(s) > 40:
                        continue
                    
                    # Dev codes
                    if re.match(r'^[A-Z]{2,5}[-\s]?\d{3,7}[A-Z]?$', s, re.I) and s not in result["dev_codes"]:
                        result["dev_codes"].append(s)
                    
                    # CAS number
                    if re.match(r'^\d{2,7}-\d{2}-\d$', s) and not result["cas"]:
                        result["cas"] = s
                    
                    # Todos sinônimos (primeiros 50)
                    if len(result["synonyms"]) < 50 and len(s) >= 3:
                        result["synonyms"].append(s)
                
                logger.info(f"✅ PubChem Synonyms: {len(result['dev_codes'])} dev codes, CAS={result['cas']}")
        
        # 2. Buscar propriedades químicas completas
        url2 = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{molecule}/JSON"
        async with httpx.AsyncClient() as client:
            r2 = await client.get(url2, timeout=Config.TIMEOUT)
            if r2.status_code == 200:
                data2 = r2.json()
                compound = data2.get("PC_Compounds", [{}])[0]
                props = compound.get("props", [])
                
                for p in props:
                    label = p.get("urn", {}).get("label", "")
                    
                    if label == "IUPAC Name":
                        result["iupac"] = p.get("value", {}).get("sval", "")
                    elif label == "Molecular Formula":
                        result["molecular_formula"] = p.get("value", {}).get("sval", "")
                    elif label == "Molecular Weight":
                        result["molecular_weight"] = p.get("value", {}).get("sval", "")
                    elif label == "SMILES" and p.get("urn", {}).get("name") == "Canonical":
                        result["smiles"] = p.get("value", {}).get("sval", "")
                    elif label == "InChI" and p.get("urn", {}).get("name") == "Standard":
                        result["inchi"] = p.get("value", {}).get("sval", "")
                    elif label == "InChIKey" and p.get("urn", {}).get("name") == "Standard":
                        result["inchi_key"] = p.get("value", {}).get("sval", "")
                
                logger.info(f"✅ PubChem Properties: Formula={result['molecular_formula']}, MW={result['molecular_weight']}")
    
    except Exception as e:
        logger.error(f"❌ PubChem error: {e}")
    
    return result

# =====================================================
# WO NUMBERS - MÚLTIPLAS FONTES
# =====================================================
async def search_wo_numbers(molecule: str, dev_codes: List[str]) -> List[str]:
    """Busca números WO usando SerpAPI (Google)"""
    wo_numbers = []
    wo_pattern = re.compile(r'WO[\s-]?(\d{4})[\s/]?(\d{6})', re.I)
    
    # Queries estratégicas
    queries = [
        f"{molecule} patent WO2019",
        f"{molecule} patent WO2020",
        f"{molecule} patent WO2021",
        f"{molecule} Orion Corporation patent",
        f"{molecule} Bayer patent"
    ]
    
    # Adicionar dev codes
    for code in dev_codes[:3]:
        queries.append(f"{code} patent WO")
    
    logger.info(f"🔍 Searching {len(queries)} WO queries via SerpAPI...")
    
    try:
        async with httpx.AsyncClient() as client:
            for i, query in enumerate(queries):
                try:
                    key = get_key()
                    if not key:
                        logger.warning("⚠️ No SerpAPI key available")
                        break
                    
                    url = f"https://serpapi.com/search.json?engine=google&q={query}&api_key={key}&num=10"
                    r = await client.get(url, timeout=Config.TIMEOUT)
                    
                    if r.status_code == 200:
                        data = r.json()
                        results = data.get("organic_results", [])
                        
                        for res in results:
                            text = f"{res.get('title', '')} {res.get('snippet', '')} {res.get('link', '')}"
                            matches = wo_pattern.findall(text)
                            
                            for m in matches:
                                wo = f"WO{m[0]}{m[1]}"
                                if wo not in wo_numbers:
                                    wo_numbers.append(wo)
                                    logger.info(f"  ✅ Found WO: {wo}")
                        
                        logger.info(f"  Query {i+1}/{len(queries)}: {len(results)} results")
                    
                    await asyncio.sleep(0.5)
                
                except Exception as e:
                    logger.error(f"  ❌ Query {i+1} error: {e}")
                    continue
    
    except Exception as e:
        logger.error(f"❌ WO search error: {e}")
    
    logger.info(f"✅ Total WO numbers found: {len(wo_numbers)}")
    return wo_numbers

# =====================================================
# BR PATENTS VIA WO
# =====================================================
async def get_br_from_wo(wo_number: str) -> List[Dict[str, Any]]:
    """Busca patentes BR a partir de um WO number"""
    br_patents = []
    
    try:
        key = get_key()
        if not key:
            return []
        
        # 1. Buscar WO no Google Patents
        url = f"https://serpapi.com/search.json?engine=google_patents&q={wo_number}&api_key={key}&num=20"
        
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=Config.TIMEOUT)
            
            if r.status_code == 200:
                data = r.json()
                
                # Pegar serpapi_link se disponível
                results = data.get("organic_results", [])
                if results and results[0].get("serpapi_link"):
                    serpapi_link = results[0]["serpapi_link"] + f"&api_key={key}"
                    
                    # 2. Buscar worldwide applications
                    r2 = await client.get(serpapi_link, timeout=Config.TIMEOUT)
                    if r2.status_code == 200:
                        data2 = r2.json()
                        worldwide = data2.get("worldwide_applications", {})
                        
                        # Extrair patentes BR
                        for year, apps in worldwide.items():
                            if isinstance(apps, list):
                                for app in apps:
                                    doc_id = app.get("document_id", "")
                                    if doc_id.startswith("BR"):
                                        br_patents.append({
                                            "number": doc_id,
                                            "wo_source": wo_number,
                                            "title": app.get("title", ""),
                                            "link": f"https://patents.google.com/patent/{doc_id}"
                                        })
                                        logger.info(f"    ✅ Found BR: {doc_id} from {wo_number}")
    
    except Exception as e:
        logger.error(f"  ❌ Error processing {wo_number}: {e}")
    
    return br_patents

# =====================================================
# INPI SEARCH
# =====================================================
async def search_inpi(molecule: str, dev_codes: List[str], cas: Optional[str]) -> List[Dict[str, Any]]:
    """Busca patentes no INPI crawler"""
    all_patents = []
    
    queries = [molecule, molecule.lower()]
    for code in dev_codes[:8]:
        queries.append(code)
    if cas:
        queries.append(cas)
    
    queries = list(set(queries))[:12]
    
    logger.info(f"🔍 Searching {len(queries)} INPI queries...")
    
    try:
        async with httpx.AsyncClient() as client:
            for i, q in enumerate(queries):
                try:
                    url = f"{Config.INPI_URL}?medicine={q}"
                    r = await client.get(url, timeout=Config.TIMEOUT_INPI)
                    
                    if r.status_code == 200:
                        data = r.json()
                        patents = data.get("data", [])
                        
                        if patents:
                            all_patents.extend(patents)
                            logger.info(f"  ✅ INPI {i+1}/{len(queries)} [{q}]: {len(patents)} patents")
                        else:
                            logger.info(f"  ⚫ INPI {i+1}/{len(queries)} [{q}]: 0 patents")
                    
                    await asyncio.sleep(1)
                
                except Exception as e:
                    logger.error(f"  ❌ INPI query {i+1} error: {e}")
                    continue
    
    except Exception as e:
        logger.error(f"❌ INPI error: {e}")
    
    # Deduplicate
    seen = set()
    unique = []
    for p in all_patents:
        pid = p.get("title", "").replace(" ", "").replace("-", "").upper()
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(p)
    
    logger.info(f"✅ INPI unique patents: {len(unique)}")
    return unique

# =====================================================
# BUSCA COMPLETA
# =====================================================
async def search_patents_full(molecule: str) -> Dict[str, Any]:
    """Pipeline COMPLETO de busca de patentes"""
    start = datetime.now()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🚀 STARTING FULL SEARCH: {molecule}")
    logger.info(f"{'='*60}")
    
    # 1. PubChem completo
    logger.info("\n📋 STEP 1: PubChem")
    pubchem = await get_pubchem_full(molecule)
    
    # 2. Buscar WO numbers
    logger.info("\n📋 STEP 2: WO Numbers (SerpAPI)")
    wo_numbers = await search_wo_numbers(molecule, pubchem["dev_codes"])
    
    # 3. Buscar BR via WO (primeiros 5 WOs)
    logger.info("\n📋 STEP 3: BR Patents via WO")
    br_from_wo = []
    for wo in wo_numbers[:5]:
        logger.info(f"  Processing {wo}...")
        br_patents = await get_br_from_wo(wo)
        br_from_wo.extend(br_patents)
        await asyncio.sleep(1)
    
    # 4. Buscar INPI direto
    logger.info("\n📋 STEP 4: INPI Direct Search")
    inpi_patents = await search_inpi(molecule, pubchem["dev_codes"], pubchem["cas"])
    
    # 5. Combinar todos BR patents
    all_br = br_from_wo + inpi_patents
    
    # Deduplicate
    seen = set()
    unique_br = []
    for p in all_br:
        pid = p.get("number", p.get("title", "")).replace(" ", "").replace("-", "").upper()
        if pid and pid not in seen:
            seen.add(pid)
            unique_br.append(p)
    
    elapsed = (datetime.now() - start).total_seconds()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ SEARCH COMPLETE: {len(unique_br)} BR patents in {elapsed:.1f}s")
    logger.info(f"{'='*60}\n")
    
    # Resultado completo
    result = {
        "molecule": molecule,
        "pubchem": {
            "dev_codes": pubchem["dev_codes"],
            "cas": pubchem["cas"],
            "iupac": pubchem["iupac"],
            "molecular_formula": pubchem["molecular_formula"],
            "molecular_weight": pubchem["molecular_weight"],
            "smiles": pubchem["smiles"],
            "inchi_key": pubchem["inchi_key"]
        },
        "wo_numbers": wo_numbers,
        "br_patents": unique_br,
        "statistics": {
            "total_br_patents": len(unique_br),
            "wo_numbers_found": len(wo_numbers),
            "br_from_wo": len(br_from_wo),
            "br_from_inpi": len(inpi_patents),
            "dev_codes": len(pubchem["dev_codes"]),
            "execution_time": round(elapsed, 2)
        },
        "sources": {
            "pubchem": "✅" if pubchem["dev_codes"] else "⚫",
            "wo_search": "✅" if wo_numbers else "⚫",
            "google_patents": "✅" if br_from_wo else "⚫",
            "inpi_crawler": "✅" if inpi_patents else "⚫"
        },
        "comparison": {
            "expected": 8,
            "found": len(unique_br),
            "match_rate": f"{min(100, int((len(unique_br) / 8) * 100))}%",
            "status": "✅ Excellent" if len(unique_br) >= 6 else "⚠️ Low"
        }
    }
    
    return result

# =====================================================
# ENDPOINTS
# =====================================================
@app.get("/")
async def root():
    return {"status": "ok", "version": "4.2-FULL", "features": ["PubChem Full", "WO Search", "BR Patents", "INPI", "Statistics"]}

@app.get("/health")
async def health():
    return {"status": "healthy", "serpapi_pool": pool_status()}

@app.get("/api/v1/search")
async def search(molecule_name: str = Query(...)):
    """Busca COMPLETA de patentes com estatísticas"""
    try:
        result = await search_patents_full(molecule_name)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/serpapi/status")
async def serpapi_status():
    """Status do pool SerpAPI"""
    return JSONResponse(content=pool_status())

@app.get("/api/v1/serpapi/key")
async def serpapi_key():
    """Próxima key disponível"""
    key = get_key()
    return {"key": key[:20] + "..." if key else None, "full": key}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
