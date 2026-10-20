#!/usr/bin/env python3
"""Independent weekly candidate retrieval. Results are private candidates, never auto-certified selections."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

UTC = dt.timezone.utc
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}

def atomic(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="."+path.name)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n"); file.flush(); os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def parse_arxiv(raw):
    root = ET.fromstring(raw)
    records = []
    for entry in root.findall("a:entry", NS):
        def text(name): return " ".join((entry.findtext(name, "", NS)).split())
        identifier = text("a:id").rsplit("/", 1)[-1]
        if not re.fullmatch(r"\d{4}\.\d{4,5}v\d+", identifier):
            raise ValueError("arXiv returned an error or unsupported identifier")
        doi = text("x:doi")
        records.append({
            "paperId": "doi:"+doi.lower() if doi else "arxiv:"+re.sub(r"v\d+$", "", identifier),
            "arxivId": identifier, "doi": doi or None, "title": text("a:title"),
            "authors": [a.findtext("a:name", "", NS) for a in entry.findall("a:author", NS)],
            "url": "https://arxiv.org/abs/"+identifier,
            "submittedAt": text("a:published"), "updatedAt": text("a:updated"),
            "abstractForReview": text("a:summary"), "journalReference": text("x:journal_ref") or None,
            "status": "candidate-unreviewed",
            "limits": "arXiv metadata is discovery evidence. A journal reference does not verify peer review, publisher identity or the scientific claim.",
        })
    return records

def collect(state_dir, days=14):
    state_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(UTC)
    local = now.astimezone(dt.timezone(dt.timedelta(hours=8)))
    week = "%04d-W%02d" % local.isocalendar()[:2]
    destination = state_dir/week
    destination.mkdir(exist_ok=True)
    result_file = destination/"candidates.json"
    if result_file.exists():
        return {"week": week, "status": "already-collected", "path": str(result_file)}
    attempt_file = destination/"attempt.json"
    if attempt_file.exists():
        previous=json.loads(attempt_file.read_text())
        if previous.get("retryNotBefore","")>now.isoformat():
            return {"week":week,"status":"source-backoff","retryNotBefore":previous["retryNotBefore"]}
    lock = state_dir/"collect.lock"
    lock.mkdir()  # no age-based takeover of interrupted workers
    atomic(lock/"owner.json", {"pid": os.getpid(), "startedAt": now.isoformat()})
    try:
        start = now-dt.timedelta(days=days)
        query = '(cat:cond-mat.supr-con OR ti:superconduct*) AND submittedDate:[%s TO %s]' % (start.strftime("%Y%m%d%H%M"), now.strftime("%Y%m%d%H%M"))
        url = "https://export.arxiv.org/api/query?"+urllib.parse.urlencode({
            "search_query": query, "start": 0, "max_results": 100,
            "sortBy": "submittedDate", "sortOrder": "descending"})
        request = urllib.request.Request(url, headers={"User-Agent": "SCWiki-Research-Editorial/1.0 (https://jzis.org/scwiki)"})
        with urllib.request.urlopen(request, timeout=40) as response:
            raw = response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024: raise ValueError("Candidate response exceeds limit")
        records = parse_arxiv(raw)
        # Save raw evidence privately; never put source abstracts on the public site.
        (destination/"arxiv-response.xml").write_bytes(raw)
        result = {"week": week, "collectedAt": now.isoformat(), "windowStart": start.isoformat(),
                  "source": url, "sourceSha256": hashlib.sha256(raw).hexdigest(),
                  "coverage": "At most 100 recent arXiv submissions; not exhaustive and not a publisher-literature survey.",
                  "reviewRequired": True, "candidates": records}
        atomic(result_file, result)
        atomic(destination/"attempt.json", {"status": "collected-for-review", "at": now.isoformat(), "count": len(records)})
        return {"week": week, "status": "collected-for-review", "count": len(records), "path": str(result_file)}
    except Exception as error:
        delay=3600 if isinstance(error,urllib.error.HTTPError) and error.code==429 else 300
        if isinstance(error,urllib.error.HTTPError) and error.headers:
            retry=error.headers.get("Retry-After","")
            if retry.isdigit():delay=max(delay,int(retry))
        atomic(destination/"attempt.json", {"status": "failed", "at": now.isoformat(), "error": str(error),
                                           "retryNotBefore":(now+dt.timedelta(seconds=delay)).isoformat(),
                                           "publishedContentChanged": False})
        raise
    finally:
        (lock/"owner.json").unlink(); lock.rmdir()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    try: print(json.dumps(collect(args.state_dir), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"status":"failed","error":str(error),"publishedContentChanged":False}));raise SystemExit(1)
