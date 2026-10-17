"""Build a complete disposition inventory from the pinned source Git tree. No source text is published."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument("source",type=Path)
args=parser.parse_args()
root=args.source.resolve()
commit="0a7c9d6696804ec26aa12f8eed68b55c9b3c0fcf"
actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
assert actual==commit,"source revision mismatch"
paths=subprocess.check_output(["git","ls-files"],cwd=root,text=True).splitlines()
pilot={"A1","A2","B12","C2","D3","D4","D5","D11","E4","F7","G7","H2"}
files=[]
for path in sorted(p for p in paths if p.lower().endswith(".md")):
 data=(root/path).read_bytes()
 code=re.match(r"([A-H]\d+)_",Path(path).name)
 topic=code.group(1) if code and not path.startswith("papers/") else None
 if topic in pilot: disposition="edited-english-pilot"
 elif topic: disposition="topic-awaiting-translation-and-review"
 elif "Al-O" in path: disposition="prediction-only-exclude-from-experimental-records"
 elif "AUDIT" in path.upper() or "DENOISE" in path.upper() or "VERIFICATION" in path.upper(): disposition="historical-audit-not-scientific-verification"
 elif path.startswith("papers/"): disposition="supporting-source-note-not-published"
 elif "overview" in path.lower(): disposition="overview-awaiting-review"
 else: disposition="editorial-policy-or-planning-not-published"
 files.append({"id":"file-"+hashlib.sha256(("JackZH26/jzis-superconductivity/"+path).encode()).hexdigest()[:16],"path":path,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data),"lineCount":len(data.decode("utf-8").splitlines()),"topicId":"scwiki-topic-"+topic.lower() if topic else None,"articleId":"scwiki-"+topic.lower() if topic else None,"disposition":disposition,"publicBody":topic in pilot,"scientificVerification":"not-established-by-file-presence-or-historical-audit"})
assert len(files)==282,len(files)
out={"schemaVersion":"1.0","repository":"JackZH26/jzis-superconductivity","commit":commit,"files":files,"correctionRegister":[{"id":"correction-prl-109-087001-material","affectedTopics":["C2","C10"],"doi":"10.1103/PhysRevLett.109.087001","incorrectAttribution":"BaFe2(As1-xPx)2","correctMaterial":"KFe2As2","evidenceUrl":"https://arxiv.org/abs/1201.3376","checkedAt":"2026-10-17","scope":"Authors' abstract and journal DOI identify KFe2As2; the abstract favors d-wave. It does not establish nodes in P-substituted Ba122."}]}
out["correctionRegister"].append({"id":"correction-nature07625-material","affectedTopics":["C2"],"doi":"10.1038/nature07625","incorrectAttribution":"Co-doped Ba122","correctMaterial":"Ba0.6K0.4Fe2As2","scope":"Bibliographic title/material identity; no new pairing assignment.","checkedAt":"2026-10-17"})
target=Path(__file__).resolve().parent.parent/"content/scwiki/source-manifest.json"
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
print(json.dumps({"files":len(files),"topics":sum(x["topicId"] is not None for x in files),"pilot":sum(x["publicBody"] for x in files)}))
