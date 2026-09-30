def choose_quality(qualities: dict[str,str], requested: str = "best") -> tuple[str,str]:
    if not qualities: raise ValueError("No downloadable qualities were exposed by the source")
    normalized={str(k).lower():v for k,v in qualities.items()}
    if requested.lower() in normalized: return requested, normalized[requested.lower()]
    pairs=[]
    for k,v in qualities.items():
        import re
        m=re.search(r"(\\d+)p", str(k))
        if m: pairs.append((int(m.group(1)), k, v))
    if pairs: _,k,v=max(pairs); return k,v
    k=next(iter(qualities)); return k,qualities[k]
