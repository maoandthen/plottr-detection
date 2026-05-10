import os, re
from datetime import date
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from neo4j import GraphDatabase

APP_ROOT = Path(__file__).parent.parent
STATIC_DIR = APP_ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Tenure · Plottr Ownership API")

try:
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
except:
    pass

def get_driver():
    if not hasattr(app.state, "driver"):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        if uri.startswith("neo4j://"):
            uri = uri.replace("neo4j://", "bolt://", 1)
        uri = re.sub(r"//neo4j:", "//localhost:", uri)
        app.state.driver = GraphDatabase.driver(
            uri, auth=(os.getenv("NEO4J_USER","neo4j"),
                      os.getenv("NEO4J_PASSWORD","plottr_secret")))
    return app.state.driver

def read_static(name):
    try:
        return (STATIC_DIR / name).read_text()
    except:
        return f"<html><body style='background:#0f0f0d;color:#f5f2eb;padding:2rem;font-family:monospace'>{name} not found. <a href='/' style='color:#b8972a'>Home</a></body></html>"

# ── PAGES ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return RedirectResponse(url="/search")

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return HTMLResponse(read_static("search.html"))

@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request, area: str = "SW1X"):
    return HTMLResponse(read_static("map.html"))

@app.get("/concentration", response_class=HTMLResponse)
async def concentration_page(request: Request, area: str = "SW1X"):
    return HTMLResponse(read_static("concentration.html"))

# ── API: CONCENTRATION ──────────────────────────────────────────────────

def get_concentration_live(area_code: str, min_titles: int = 1) -> dict:
    import re as _re
    area_code = area_code.upper().strip()
    try:
        with get_driver().session() as s:
            kpi = s.run("""
            MATCH (t:Title) WHERE t.postcode STARTS WITH $area
            WITH count(t) AS total
            OPTIONAL MATCH (t2:Title)-[:OWNED_BY]->(c2:Company) WHERE t2.postcode STARTS WITH $area
            WITH total, count(DISTINCT t2) AS corp
            OPTIONAL MATCH (t3:Title {source:"OCOD"})-[:OWNED_BY]->(oc) WHERE t3.postcode STARTS WITH $area
            RETURN total, corp, count(DISTINCT t3) AS foreign_t
            """, area=area_code).single()
            total = int(kpi["total"]) if kpi and kpi["total"] else 0
            corp = int(kpi["corp"]) if kpi and kpi["corp"] else 0
            foreign = int(kpi["foreign_t"]) if kpi and kpi["foreign_t"] else 0

            rows = s.run("""
            MATCH (t:Title)-[:OWNED_BY]->(c:Company)
            WHERE t.postcode STARTS WITH $area
            WITH c, count(DISTINCT t) AS tc, collect(DISTINCT t.source)[0] AS src
            WHERE tc >= $min_t
            RETURN c.name AS name, c.company_number AS crn,
                   c.status AS status, tc AS title_count, src
            ORDER BY tc DESC LIMIT 100
            """, area=area_code, min_t=min_titles).data()

            if not rows:
                return {"area":{"name":area_code,"code":area_code,"kind":"postcode","map_svg":None},
                       "stats":{"total_titles":0,"corporate_titles":0,"corporate_pct":0,
                               "top_10_titles":0,"top_10_pct":0,"foreign_titles":0,
                               "foreign_pct":0,"foreign_countries":0},
                       "filters":{"min_titles":min_titles,"ownership_type":None,"country":None},"top_owners":[],"owners":[],"pagination":{"from":1,"to":0,"total":0,"last_page":1}}

            max_t = rows[0]["title_count"] if rows else 1
            top10 = sum(o["title_count"] for o in rows[:10])

            def slug(o):
                if o.get("crn"): return o["crn"]
                return _re.sub(r"[^a-z0-9]+","-",(o.get("name") or "unknown").lower())[:50]

            owners = [{
                "name": o["name"] or "Unknown",
                "crn": o["crn"], "status": o["status"] or "",
                "title_count": int(o["title_count"]),
                "bar_pct": round(o["title_count"]/max_t*100,1),
                "area_pct": round(o["title_count"]/total*100,2) if total else 0.0,
                "foreign": o["src"]=="OCOD",
                "public": False,
                "jurisdiction": "Overseas" if o["src"]=="OCOD" else "",
                "registered_office":"","last_activity":"—","slug":slug(o),
            } for o in rows]

            return {
                "area":{"name":area_code,"code":area_code,"kind":"postcode district","map_svg":None},
                "stats":{"total_titles":total,"corporate_titles":corp,
                        "corporate_pct":round(corp/total*100,1) if total else 0,
                        "top_10_titles":top10,
                        "top_10_pct":round(top10/corp*100,1) if corp else 0,
                        "foreign_titles":foreign,
                        "foreign_pct":round(foreign/corp*100,1) if corp else 0,
                        "foreign_countries":0},
                "filters":{"min_titles":min_titles,"ownership_type":None,"country":None},
                "top_owners":owners[:10],"owners":owners,
                "pagination":{"from":1,"to":len(owners),"total":len(owners),"last_page":1},
            }
    except Exception as e:
        return {"error": str(e), "area":{"name":area_code,"code":area_code,"kind":"postcode","map_svg":None},
               "stats":{"total_titles":0,"corporate_titles":0,"corporate_pct":0,
                       "top_10_titles":0,"top_10_pct":0,"foreign_titles":0,
                       "foreign_pct":0,"foreign_countries":0},
               "filters":{},"top_owners":[],"owners":[],"pagination":{}}

@app.get("/api/concentration/{area_code}")
async def concentration_json(area_code: str, min_titles: int = 1):
    return JSONResponse(content=get_concentration_live(area_code, min_titles))

@app.get("/dashboard/ownership/concentration/{area_code}", response_class=HTMLResponse)
async def concentration_page_legacy(request: Request, area_code: str, min_titles: int = 1):
    return RedirectResponse(url=f"/concentration?area={area_code}")

# ── API: COMPANY DETAIL ──────────────────────────────────────────────────

@app.get("/api/company/{crn}")
async def company_detail(crn: str):
    try:
        with get_driver().session() as s:
            core = s.run("""
            MATCH (c:Company {company_number: $crn})
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
            WITH c, count(DISTINCT t) AS title_count,
                 collect(DISTINCT t.postcode)[0..8] AS postcodes,
                 collect(DISTINCT t.district)[0..5] AS districts,
                 collect(DISTINCT t.source)[0..2] AS sources
            RETURN c.company_number AS crn, c.name AS name,
                   c.status AS status, c.category AS category,
                   c.incorporation_date AS incorporated,
                   c.sic_text AS sic,
                   title_count, postcodes, districts, sources
            """, crn=crn).single()
            if not core:
                return JSONResponse(content={"error":"not found"}, status_code=404)

            pscs = s.run("""
            MATCH (p:Person)-[r:PSC_OF]->(c:Company {company_number: $crn})
            RETURN p.person_id AS person_id, p.name AS name,
                   p.dob_year AS dob_year, p.nationality AS nationality,
                   p.country_of_residence AS country_of_residence,
                   r.nature_of_control AS nature_of_control,
                   r.notified_on AS notified_on
            ORDER BY p.name LIMIT 20
            """, crn=crn).data()

            siblings = s.run("""
            MATCH (p:Person)-[:PSC_OF]->(c:Company {company_number: $crn})
            MATCH (p)-[:PSC_OF]->(sib:Company)
            WHERE sib.company_number <> $crn
            WITH sib, count(DISTINCT p) AS shared
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(sib)
            RETURN sib.company_number AS crn, sib.name AS name,
                   sib.status AS status, shared,
                   count(DISTINCT t) AS title_count
            ORDER BY title_count DESC LIMIT 8
            """, crn=crn).data()

            address = s.run("""
            MATCH (c:Company {company_number:$crn})-[:REGISTERED_AT]->(a:Address)
            RETURN a.postcode AS postcode, a.address_id AS address_id LIMIT 1
            """, crn=crn).single()

            flags = []
            st = core["status"] or ""
            if "OCOD" in (core["sources"] or []):
                flags.append({"code":"OVERSEAS","label":"Overseas incorporated","level":"medium"})
            if "Dissolved" in st or "Liquidation" in st:
                flags.append({"code":"DORMANT","label":st,"level":"high"})
            if "Administration" in st:
                flags.append({"code":"ADMIN","label":"In Administration","level":"high"})

            return JSONResponse(content={
                "crn":core["crn"],"name":core["name"],"status":core["status"],
                "category":core["category"],"incorporated":core["incorporated"],
                "sic":core["sic"],"title_count":core["title_count"],
                "postcodes":core["postcodes"],"districts":core["districts"],
                "address_postcode":address["postcode"] if address else None,
                "pscs":pscs,"siblings":siblings,"flags":flags,
                "risk_level":"high" if any(f["level"]=="high" for f in flags)
                           else "medium" if flags else "clean",
            })
    except Exception as e:
        return JSONResponse(content={"error":str(e)}, status_code=500)

# ── API: SEARCH ──────────────────────────────────────────────────────────

@app.get("/api/search/companies")
async def search_companies(q: str = "", limit: int = 8):
    if not q or len(q) < 2:
        return JSONResponse(content={"results":[]})
    try:
        qn = q.lower().strip()
        with get_driver().session() as s:
            rows = s.run("""
            MATCH (c:Company)
            WHERE c.name_normalised STARTS WITH $q
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
            WITH c, count(DISTINCT t) AS tc
            RETURN c.company_number AS crn, c.name AS name,
                   c.status AS status, c.incorporation_date AS incorporated,
                   tc AS title_count
            ORDER BY tc DESC LIMIT $lim
            """, q=qn, lim=limit).data()
            if len(rows) < 3:
                more = s.run("""
                MATCH (c:Company)
                WHERE c.name_normalised CONTAINS $q
                AND NOT c.name_normalised STARTS WITH $q
                OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
                WITH c, count(DISTINCT t) AS tc
                RETURN c.company_number AS crn, c.name AS name,
                       c.status AS status, c.incorporation_date AS incorporated,
                       tc AS title_count
                ORDER BY tc DESC LIMIT $lim
                """, q=qn, lim=limit-len(rows)).data()
                rows = rows + more
            return JSONResponse(content={"results":rows[:limit],"query":q})
    except Exception as e:
        return JSONResponse(content={"results":[],"error":str(e)})

@app.get("/api/search/persons")
async def search_persons(q: str = "", limit: int = 6):
    if not q or len(q) < 2:
        return JSONResponse(content={"results":[]})
    try:
        qn = q.lower().strip()
        with get_driver().session() as s:
            rows = s.run("""
            MATCH (p:Person)
            WHERE p.name_normalised CONTAINS $q
            OPTIONAL MATCH (p)-[:PSC_OF]->(c:Company)
            WITH p, count(DISTINCT c) AS cos
            RETURN p.person_id AS person_id, p.name AS name,
                   p.dob_year AS dob_year, p.nationality AS nationality,
                   p.country_of_residence AS country_of_residence,
                   cos AS companies_controlled
            ORDER BY cos DESC LIMIT $lim
            """, q=qn, lim=limit).data()
        return JSONResponse(content={"results":rows,"query":q})
    except Exception as e:
        return JSONResponse(content={"results":[],"error":str(e)})

# ── HEALTH ──────────────────────────────────────────────────────────────


@app.get("/api/person/{person_id}")
async def person_detail(person_id: str):
    try:
        with get_driver().session() as s:
            person = s.run("""
            MATCH (p:Person {person_id: $pid})
            RETURN p.person_id AS person_id, p.name AS name,
                   p.name_normalised AS name_normalised,
                   p.dob_year AS dob_year, p.nationality AS nationality,
                   p.country_of_residence AS country_of_residence
            """, pid=person_id).single()
            if not person:
                return JSONResponse(content={"error":"not found"}, status_code=404)
            
            companies = s.run("""
            MATCH (p:Person {person_id: $pid})-[r:PSC_OF]->(c:Company)
            OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c)
            WITH c, r, count(DISTINCT t) AS title_count,
                 collect(DISTINCT t.postcode)[0..5] AS postcodes
            RETURN c.company_number AS crn, c.name AS name,
                   c.status AS status, c.incorporation_date AS incorporated,
                   r.nature_of_control AS nature_of_control,
                   r.notified_on AS notified_on,
                   title_count, postcodes
            ORDER BY title_count DESC LIMIT 50
            """, pid=person_id).data()
            
            surname = " " + (person["name_normalised"] or "").split()[-1] if person.get("name_normalised") else ""
            family = s.run("""
            MATCH (p:Person)
            WHERE p.name_normalised ENDS WITH $surname AND p.person_id <> $pid
            OPTIONAL MATCH (p)-[:PSC_OF]->(c:Company)
            WITH p, count(DISTINCT c) AS cos WHERE cos > 0
            RETURN p.person_id AS person_id, p.name AS name,
                   p.dob_year AS dob_year, p.nationality AS nationality,
                   cos AS companies_controlled
            ORDER BY cos DESC LIMIT 8
            """, surname=surname, pid=person_id).data() if len(surname.strip()) >= 3 else []
            
            return JSONResponse(content={
                "person_id": person["person_id"], "name": person["name"],
                "dob_year": person["dob_year"], "nationality": person["nationality"],
                "country_of_residence": person["country_of_residence"],
                "companies_controlled": len(companies),
                "total_titles": sum(c.get("title_count",0) for c in companies),
                "surname": surname.strip(),
                "companies": companies, "family_cluster": family,
                "sanctions_flag": False, "pep_flag": False,
            })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/person", response_class=HTMLResponse)
async def person_page(request: Request):
    return HTMLResponse(read_static("person.html"))


@app.get("/company", response_class=HTMLResponse)
async def company_page(request: Request):
    return HTMLResponse(read_static("company.html"))



@app.get("/api/estate/{crn}")
async def estate_profile(crn: str):
    try:
        with get_driver().session() as s:
            core = s.run("""MATCH (c:Company {company_number:$crn}) 
                           OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(c) 
                           WITH c,count(DISTINCT t) AS tc,collect(DISTINCT t.postcode)[0..10] AS pc,collect(DISTINCT t.district)[0..6] AS dist,collect(DISTINCT t.source)[0..2] AS src 
                           RETURN c.company_number AS crn,c.name AS name,c.status AS status,c.category AS category,c.incorporation_date AS incorporated,c.sic_text AS sic,tc AS title_count,pc AS postcodes,dist AS districts,src AS sources""", crn=crn).single()
            if not core: 
                return JSONResponse(content={"error":"not found"},status_code=404)
            
            pscs = s.run("""MATCH (p:Person)-[r:PSC_OF]->(c:Company {company_number:$crn}) 
                           RETURN p.person_id AS person_id,p.name AS name,p.dob_year AS dob_year,p.nationality AS nationality,p.country_of_residence AS country_of_residence,r.nature_of_control AS nature_of_control,r.notified_on AS notified_on 
                           ORDER BY p.name LIMIT 20""", crn=crn).data()
            
            siblings = s.run("""MATCH (p:Person)-[:PSC_OF]->(c:Company {company_number:$crn}) 
                               MATCH (p)-[:PSC_OF]->(sib:Company) 
                               WHERE sib.company_number<>$crn 
                               WITH sib,count(DISTINCT p) AS shared 
                               OPTIONAL MATCH (t:Title)-[:OWNED_BY]->(sib) 
                               WITH sib,shared,count(DISTINCT t) AS tc,collect(DISTINCT t.postcode)[0..5] AS pc 
                               RETURN sib.company_number AS crn,sib.name AS name,sib.status AS status,shared,tc AS title_count,pc AS postcodes 
                               ORDER BY tc DESC LIMIT 12""", crn=crn).data()
            
            addr = s.run("MATCH (c:Company {company_number:$crn})-[:REGISTERED_AT]->(a:Address) RETURN a.postcode AS postcode LIMIT 1", crn=crn).single()
            
            st = core["status"] or ""
            flags = []
            if "OCOD" in (core["sources"] or []): 
                flags.append({"code":"OVERSEAS","label":"Overseas incorporated","level":"medium"})
            if any(x in st for x in ["Dissolved","Liquidation"]): 
                flags.append({"code":"DORMANT","label":st,"level":"high"})
            if "Administration" in st: 
                flags.append({"code":"ADMIN","label":"In Administration","level":"high"})
            if not pscs and (core["title_count"] or 0) > 5: 
                flags.append({"code":"NO_UBO","label":"No PSC declared","level":"medium"})
            
            return JSONResponse(content={
                "crn":core["crn"],"name":core["name"],"status":core["status"],"category":core["category"],
                "incorporated":core["incorporated"],"sic":core["sic"],"title_count":core["title_count"],
                "postcodes":core["postcodes"],"districts":core["districts"],
                "address_postcode":addr["postcode"] if addr else None,
                "pscs":pscs,"siblings":siblings,"flags":flags,
                "risk_level":"high" if any(f["level"]=="high" for f in flags) else "medium" if flags else "clean"
            })
    except Exception as e:
        return JSONResponse(content={"error":str(e)},status_code=500)


@app.get("/api/estate/{crn}/concentration")
async def estate_concentration(crn: str):
    try:
        with get_driver().session() as s:
            sibs = s.run("MATCH (p:Person)-[:PSC_OF]->(c:Company {company_number:$crn}) MATCH (p)-[:PSC_OF]->(sib:Company) RETURN collect(DISTINCT sib.company_number) AS crns", crn=crn).single()
            all_crns = [crn] + (sibs["crns"] if sibs else [])
            rows = s.run("""MATCH (t:Title)-[:OWNED_BY]->(c:Company) 
                           WHERE c.company_number IN $crns AND t.postcode IS NOT NULL 
                           WITH t.postcode AS postcode,count(DISTINCT t) AS cnt 
                           RETURN postcode,cnt AS count ORDER BY count DESC LIMIT 20""", crns=all_crns).data()
            return JSONResponse(content={"postcodes":rows,"entity_count":len(all_crns)})
    except Exception as e:
        return JSONResponse(content={"postcodes":[],"error":str(e)})


@app.get("/estate", response_class=HTMLResponse)
async def estate_page(request: Request, crn: str = ""):
    return HTMLResponse(read_static("estate.html"))



@app.get("/foreign-ownership",response_class=HTMLResponse)
async def foreign_ownership_page(request:Request):
 return HTMLResponse(read_static("foreign-ownership.html"))

@app.get("/api/risk-flags/{category}")
async def risk_flags_api(category:str):
 try:
 with get_driver().session() as s:
 if category=="nominee":
 rows=s.run("MATCH (c:Company)-[:REGISTERED_AT]->(a:Address) WHERE a.postcode IS NOT NULL WITH a,count(DISTINCT c) AS cc,collect(DISTINCT c.name)[0..4] AS sample WHERE cc>=50 RETURN a.postcode AS postcode,a.postcode AS address,cc AS company_count,sample ORDER BY cc DESC LIMIT 30").data()
 elif category=="dormant":
 rows=s.run("MATCH (t:Title)-[:OWNED_BY]->(c:Company) WHERE c.status IN ['Dissolved','Liquidation','Administration','Receivership','Converted/Closed'] WITH c,count(DISTINCT t) AS tc RETURN c.company_number AS crn,c.name AS name,c.status AS status,c.dissolution_date AS dissolution_date,tc AS title_count ORDER BY tc DESC LIMIT 50").data()
 elif category=="no-ubo":
 rows=s.run("MATCH (t:Title {source:'OCOD'})-[r:OWNED_BY]->(c:Company) WHERE NOT EXISTS {MATCH (p:Person)-[:PSC_OF]->(c)} WITH c,count(DISTINCT t) AS tc,coalesce(r.country_incorporated_in,'Overseas') AS jur RETURN c.company_number AS crn,c.name AS name,c.status AS status,jur AS jurisdiction,tc AS title_count ORDER BY tc DESC LIMIT 50").data()
 elif category=="hubs":
 rows=s.run("MATCH (t:Title)-[:OWNED_BY]->(c:Company) WITH c,count(DISTINCT t) AS tc,count(DISTINCT t.district) AS dc,collect(DISTINCT t.district)[0..6] AS districts WHERE dc>=5 AND tc>=10 RETURN c.company_number AS crn,c.name AS name,c.status AS status,tc AS title_count,dc AS district_count,districts ORDER BY dc DESC,tc DESC LIMIT 40").data()
 elif category=="network":
 rows=s.run("MATCH (p:Person)-[:PSC_OF]->(c:Company) WITH p,count(DISTINCT c) AS cos WHERE cos>=10 RETURN p.person_id AS person_id,p.name AS name,p.dob_year AS dob_year,p.nationality AS nationality,cos AS companies_controlled ORDER BY cos DESC LIMIT 50").data()
 else:
 return JSONResponse(content={"error":"unknown"},status_code=400)
 return JSONResponse(content={"results":rows,"category":category})
 except Exception as e:
 return JSONResponse(content={"results":[],"error":str(e)})

@app.get("/risk-intelligence",response_class=HTMLResponse)
async def risk_intel_page(request:Request):
 return HTMLResponse(read_static("risk-intelligence.html"))

@app.get("/person-network",response_class=HTMLResponse)
async def person_network_page(request:Request):
 return HTMLResponse(read_static("person-network.html"))


@app.get("/api/foreign-ownership/{area}")
async def foreign_ownership_api(area: str):
    area = area.upper().strip()
    try:
        with get_driver().session() as s:
            # Get basic stats
            stats_r = s.run("""MATCH (t:Title) WHERE t.postcode STARTS WITH $a 
                              WITH count(t) AS total 
                              OPTIONAL MATCH (t2:Title)-[:OWNED_BY]->(c) WHERE t2.postcode STARTS WITH $a 
                              WITH total,count(DISTINCT t2) AS corp 
                              OPTIONAL MATCH (t3:Title {source:'OCOD'})-[:OWNED_BY]->(oc) WHERE t3.postcode STARTS WITH $a 
                              RETURN total,corp,count(DISTINCT t3) AS ft""", a=area).single()
            
            total = int(stats_r["total"]) if stats_r and stats_r["total"] else 0
            corp = int(stats_r["corp"]) if stats_r and stats_r["corp"] else 0
            foreign = int(stats_r["ft"]) if stats_r and stats_r["ft"] else 0
            
            # Get jurisdictions
            juris = s.run("""MATCH (t:Title {source:'OCOD'})-[r:OWNED_BY]->(c:Company) 
                            WHERE t.postcode STARTS WITH $a 
                            WITH coalesce(r.country_incorporated_in,'Overseas') AS jurisdiction,
                                 count(DISTINCT t) AS title_count,
                                 count(DISTINCT c) AS entity_count 
                            RETURN jurisdiction,title_count,entity_count 
                            ORDER BY title_count DESC LIMIT 20""", a=area).data()
            
            # Get entities  
            entities = s.run("""MATCH (t:Title {source:'OCOD'})-[r:OWNED_BY]->(c:Company) 
                               WHERE t.postcode STARTS WITH $a 
                               WITH c,count(DISTINCT t) AS tc,coalesce(r.country_incorporated_in,'Overseas') AS jur 
                               RETURN c.company_number AS crn,c.name AS name,c.status AS status,tc AS title_count,jur AS jurisdiction 
                               ORDER BY tc DESC LIMIT 30""", a=area).data()
            
            return JSONResponse(content={
                "area": area,
                "stats": {
                    "total_titles": total,
                    "corporate_titles": corp, 
                    "foreign_titles": foreign,
                    "foreign_pct": round(foreign/corp*100,1) if corp else 0
                },
                "jurisdictions": juris,
                "entities": entities
            })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/foreign-ownership", response_class=HTMLResponse)
async def foreign_ownership_page(request: Request):
    return HTMLResponse(read_static("foreign-ownership.html"))


@app.get("/api/risk-flags/{category}")
async def risk_flags_api(category: str):
    try:
        with get_driver().session() as s:
            if category == "nominee":
                rows = s.run("""MATCH (c:Company)-[:REGISTERED_AT]->(a:Address) 
                               WHERE a.postcode IS NOT NULL 
                               WITH a,count(DISTINCT c) AS cc,collect(DISTINCT c.name)[0..4] AS sample 
                               WHERE cc>=50 
                               RETURN a.postcode AS postcode,a.postcode AS address,cc AS company_count,sample 
                               ORDER BY cc DESC LIMIT 30""").data()
            elif category == "dormant":
                rows = s.run("""MATCH (t:Title)-[:OWNED_BY]->(c:Company) 
                               WHERE c.status IN ['Dissolved','Liquidation','Administration','Receivership','Converted/Closed'] 
                               WITH c,count(DISTINCT t) AS tc 
                               RETURN c.company_number AS crn,c.name AS name,c.status AS status,c.dissolution_date AS dissolution_date,tc AS title_count 
                               ORDER BY tc DESC LIMIT 50""").data()
            elif category == "no-ubo":
                rows = s.run("""MATCH (t:Title {source:'OCOD'})-[r:OWNED_BY]->(c:Company) 
                               WHERE NOT EXISTS {MATCH (p:Person)-[:PSC_OF]->(c)} 
                               WITH c,count(DISTINCT t) AS tc,coalesce(r.country_incorporated_in,'Overseas') AS jur 
                               RETURN c.company_number AS crn,c.name AS name,c.status AS status,jur AS jurisdiction,tc AS title_count 
                               ORDER BY tc DESC LIMIT 50""").data()
            elif category == "hubs":
                rows = s.run("""MATCH (t:Title)-[:OWNED_BY]->(c:Company) 
                               WITH c,count(DISTINCT t) AS tc,count(DISTINCT t.district) AS dc,collect(DISTINCT t.district)[0..6] AS districts 
                               WHERE dc>=5 AND tc>=10 
                               RETURN c.company_number AS crn,c.name AS name,c.status AS status,tc AS title_count,dc AS district_count,districts 
                               ORDER BY dc DESC,tc DESC LIMIT 40""").data()
            elif category == "network":
                rows = s.run("""MATCH (p:Person)-[:PSC_OF]->(c:Company) 
                               WITH p,count(DISTINCT c) AS cos 
                               WHERE cos>=10 
                               RETURN p.person_id AS person_id,p.name AS name,p.dob_year AS dob_year,p.nationality AS nationality,cos AS companies_controlled 
                               ORDER BY cos DESC LIMIT 50""").data()
            else:
                return JSONResponse(content={"error": "unknown"}, status_code=400)
            
            return JSONResponse(content={"results": rows, "category": category})
    except Exception as e:
        return JSONResponse(content={"results": [], "error": str(e)})


@app.get("/risk-intelligence", response_class=HTMLResponse)
async def risk_intel_page(request: Request):
    return HTMLResponse(read_static("risk-intelligence.html"))


@app.get("/person-network", response_class=HTMLResponse)  
async def person_network_page(request: Request):
    return HTMLResponse(read_static("person-network.html"))


@app.get("/health")
async def health():
    try:
        with get_driver().session() as s:
            s.run("RETURN 1").single()
        return {"status":"ok","neo4j":"connected"}
    except Exception as e:
        return {"status":"degraded","error":str(e)}

# Legacy redirects
@app.get("/dashboard/ownership/estate/{slug}", response_class=HTMLResponse)
async def estate_legacy(slug: str):
    return RedirectResponse(url=f"/map?area=SW1X")

@app.get("/dashboard/ownership/foreign/{district}", response_class=HTMLResponse)
async def foreign_legacy(district: str):
    return RedirectResponse(url=f"/map?area=SW1X")
