"""Bounded complete-run review files. No canonical or training qualification."""
from copy import deepcopy
import csv
import hashlib
import io
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from services import materials_proposal_review as review
from services.materials_proposal_storage import canonical

VERSION = "materials-proposal-export/1"
PRESSURE_VERSION = "materials-proposal-export/2"
VISUAL_VERSION = "materials-proposal-export/3"
PROJECTOR_VERSION = "materials-proposal-export/4"
DEVICE_VERSION = "materials-proposal-export/5"
MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_CSV_BYTES = 4 * 1024 * 1024
MAX_SCOPE_REFERENCES = 200000
COLUMNS = (
    "paper_id", "run_id", "result_id", "sample_id", "state_id", "protocol_id",
    "quantity_kind", "quantity_name_as_written", "value_status", "source_value", "relation",
    "value", "lower", "upper", "unit", "approximate", "uncertainty_json",
    "criterion", "criterion_as_written", "method", "observable", "origin", "source_role",
    "formula_as_written", "formula_status", "sample_identity", "composition_basis",
    "measurement_conditions_json", "review_status", "issue_codes_json", "result_pointer",
    "sample_pointer", "state_pointer", "protocol_pointer", "evidence_index_pointer",
)
NUMERIC_COLUMNS = {"value", "lower", "upper"}
PRESSURE_COLUMNS = (*COLUMNS, "pressure_declaration_json")
DEVICE_COLUMNS = (*PRESSURE_COLUMNS, "state_conditions_json")
PRESSURE_SCHEMAS = frozenset({"materials-ner/13", "materials-ner/14", "materials-ner/15"})
JSON_COLUMNS = {"uncertainty_json", "measurement_conditions_json", "issue_codes_json", "pressure_declaration_json", "state_conditions_json"}
README = """Materials complete retained-run review export

results.csv contains one row per result candidate version in this extraction run.
graph.json retains every scientific entity, field, normalization, issue and bound
source passage. Its result_evidence index links results to shared evidence by
ordinal; evidence counts are not counts of independent measurements. Alternate
runs are separate attempts. No candidate here is approved for training or release.

Complete means the retained run graph, not complete paper/supplement/figure reading.
See coverage, validation and source_documents for source access and unread scope.
An empty failed run has a header-only CSV and retains its failure in graph.json.
Missing CSV cells are absent projected values, never zero or proof of paper silence.
The unit column applies to value/lower/upper; source_value preserves source wording.
Ranges and inequalities have no fabricated scalar or midpoint. measurement_conditions_json
contains only state conditions explicitly assigned the measurement role; other
roles, formula alternatives, sample relations, definitions, non-detection targets,
sensitivities, windows, dependencies and task exclusions remain in graph.json.
Unknown pressure is not ambient. The export does not infer first-report status,
retraction status, a provider model revision or an extraction date. run.created_at
is the storage import timestamp. Available model/pipeline provenance is separate.
graph.json coverage.source_item_accounting preserves original-item dispositions,
missing/held items and model-proposed observation holds, including the original
candidate and its source quotes. A held candidate is absent from the current
results.csv but is not erased from the companion graph or approved for scientific
exclusion. Additional aliases do not count as recovery of held original items.

CSV uses UTF-8, a single header, comma delimiters, RFC 4180 quoting and CRLF records.
Import identifiers and source text as text in spreadsheets. Formula-leading text
and control/apostrophe-leading text receive one protective apostrophe; every change
is listed by CSV row and column in manifest.csv.escaped_cells. Remove that one prefix
only at listed coordinates to recover the exact projected source text. Numeric
negative values are numbers and are not text-escaped. graph.json is unescaped.
CSV pointers are JSON Pointers into graph.json. Evidence path is the original
extraction path; graph_pointer is null if that field cannot resolve in the retained
projection. Such evidence is preserved without pretending its binding is valid.

manifest.json gives byte counts and SHA-256 hashes for every companion file.
The archive is a private review export. Source redistribution permissions and
scientific/task qualification must be resolved separately before publication.
"""


def sha(raw):return hashlib.sha256(raw).hexdigest()


def bounded(raw, limit=MAX_UNCOMPRESSED_BYTES):
    if len(raw)>limit:raise review.ProposalUnavailable("proposal_export_size_limit")
    return raw


def encoded(value):return (canonical(value)+"\n").encode("utf-8")


def graph_pointer(path, entities):
    parts=path.split("/")[1:]
    if len(parts)<2:return None
    tokens=["entities",*parts[:2],"payload",*parts[2:]]
    node={"entities":entities}
    try:
        for token in tokens:
            token=token.replace("~1","/").replace("~0","~")
            node=node[int(token)] if isinstance(node,list) else node[token]
    except (KeyError,IndexError,ValueError,TypeError):return None
    return "/"+"/".join(tokens)


def complete_graph(packet, created):
    projection=review.detail_projection(packet,created)
    entities={g:review.display_rows(packet,g) for g in (*review.GROUPS,"results")}
    # Reading pages expose only resolved passages; the complete graph also retains
    # original candidate evidence, including unsupported/unresolved model bindings.
    for group,rows in entities.items():
        for row,original in zip(rows,packet["rows"].get(group,[])):
            if "evidence" in original["payload"]:row["payload"]["evidence"]=deepcopy(original["payload"]["evidence"])
    evidence=[];by_scope={};used=set();evidence_bytes=0
    for ordinal,item in enumerate(packet["evidence"]):
        entry=review.passage(packet,ordinal,item)
        entry["graph_pointer"]=graph_pointer(item["path"],entities)
        evidence_bytes+=len(encoded(entry))
        if evidence_bytes>MAX_UNCOMPRESSED_BYTES:raise review.ProposalUnavailable("proposal_export_evidence_limit")
        evidence.append(entry)
        prefix="/"+"/".join(item["path"].split("/")[1:3]);by_scope.setdefault(prefix,[]).append(ordinal)
    indexes=[];references=0
    for result in sorted(entities["results"],key=lambda r:r["local_id"]):
        scope=review.evidence_scope(packet,result["local_id"])
        ordinals=sorted({n for prefix in scope for n in by_scope.get(prefix,[])})
        references+=len(ordinals)
        if references>MAX_SCOPE_REFERENCES:raise review.ProposalUnavailable("proposal_export_scope_limit")
        used.update(ordinals)
        indexes.append(dict(result_id=result["local_id"],result_pointer="/entities"+result["source_path"],
                            scope_paths=scope,evidence_ordinals=ordinals))
    config=packet["receipt"]["config"]
    provenance={k:deepcopy(config[k]) for k in ("model","provider","reasoning","pipeline_version","validator_version",
        "registry_version","workflow","prompt_version","schema_sha256","implementation_sha256","parent_run_id") if k in config}
    receipt = packet['receipt']
    if receipt.get('structured_graph_authored_by_reader') is False:
        provenance.update(projection_author=deepcopy(receipt['projection_author']),
            structured_graph_authored_by_reader=False, projection_created_at=receipt['created_at'],
            reader=dict(model=receipt['reader_provenance']['config']['model'],
                reasoning=receipt['reader_provenance']['config']['reasoning'],
                attempt_id=receipt['reader_provenance']['attempt']['attempt_id'],
                raw_output_sha256=receipt['raw_output_sha256']))
    visual = receipt.get('visual_support') is not None
    return dict(version="materials-proposal-graph/2" if visual else "materials-proposal-graph/1",
        **({'visual_evidence_path': 'visual-evidence.json'} if visual else {}),
        **({'raw_model_graph_path':'raw-model-graph.json'} if 'projector_review' in projection['coverage'] else {}),
        scope="complete_retained_run",run=projection["run"],entities=entities,
        evidence=evidence,result_evidence=indexes,unscoped_evidence_ordinals=sorted(set(range(len(evidence)))-used),
        **{k:projection[k] for k in ("source_documents","coverage","validation","training_exclusions","authority")},
        extraction_provenance=provenance,training_assessment=deepcopy(packet["receipt"].get("training_assessment",{})))


def review_records(graph):
    groups=graph["entities"]
    pressure_native = graph['run']['extraction_version'] in PRESSURE_SCHEMAS
    index={g:{r["local_id"]:r for r in groups[g]} for g in ("samples","states","protocols")}
    rows=[]
    for ordinal,binding in enumerate(graph["result_evidence"]):
        r=groups["results"][int(binding["result_pointer"].split("/")[-1])];p=r["payload"]
        sample=index["samples"][p["sample_id"]];state=index["states"][p["state_id"]];protocol=index["protocols"][p["protocol_id"]]
        s=sample["payload"];q=p["quantity"];definition=p.get("definition",{})
        values=dict(paper_id=graph["run"]["work_id"],run_id=graph["run"]["run_id"],result_id=r["local_id"],
            sample_id=p["sample_id"],state_id=p["state_id"],protocol_id=p["protocol_id"],quantity_kind=p["quantity_kind"],
            quantity_name_as_written=p.get("quantity_name_raw"),value_status=q["status"],source_value=q.get("raw"),
            relation=q.get("relation"),value=q.get("value"),lower=q.get("lower"),upper=q.get("upper"),unit=q.get("unit"),
            approximate=q.get("approximate"),uncertainty_json=q.get("uncertainty"),criterion=definition.get("criterion"),
            criterion_as_written=definition.get("criterion_raw"),method=protocol["payload"].get("method"),
            observable=protocol["payload"].get("observable"),origin=p.get("origin"),source_role=p.get("source_role"),
            formula_as_written=s.get("formula_raw"),formula_status="reported" if s.get("formula_raw") is not None else s.get("formula_unavailability",{}).get("status","unresolved"),
            sample_identity=s.get("identity_resolution"),composition_basis=s.get("composition_basis"),
            measurement_conditions_json=[c for c in state["payload"].get("conditions",[]) if c.get("role")=="measurement"],
            review_status=r["review_status"],issue_codes_json=r["issues"],result_pointer=binding["result_pointer"],
            sample_pointer="/entities"+sample["source_path"],state_pointer="/entities"+state["source_path"],
            protocol_pointer="/entities"+protocol["source_path"],evidence_index_pointer=f"/result_evidence/{ordinal}")
        if pressure_native:
            values['pressure_declaration_json'] = deepcopy(state['payload'].get('pressure'))
        device_native = graph['run']['extraction_version']=='materials-ner/15'
        if device_native:
            values['state_conditions_json']=deepcopy(state['payload'].get('conditions',[]))
        expected_columns = DEVICE_COLUMNS if device_native else PRESSURE_COLUMNS if pressure_native else COLUMNS
        assert set(values)==set(expected_columns)
        rows.append(values)
    return rows


def csv_files(records, *, columns=COLUMNS):
    output=io.BytesIO()
    def append(values):
        row=io.StringIO(newline="");csv.writer(row,lineterminator="\r\n").writerow(values)
        raw=row.getvalue().encode("utf-8")
        if output.tell()+len(raw)>MAX_CSV_BYTES:raise review.ProposalUnavailable("proposal_export_csv_limit")
        output.write(raw)
    append(columns);escaped=[];expected=[]
    for row_number,record in enumerate(records,start=2):
        values=[];original=[]
        for column in columns:
            value=record[column]
            cell="" if value is None else canonical(value) if not isinstance(value,str) else value
            original.append(cell)
            head=cell.lstrip(" \t\r\n\ufeff")
            if isinstance(value,str) and cell and (cell[0]=="'" or ord(cell[0])<32 or head.startswith(("=","+","-","@"))):
                cell="'"+cell;escaped.append(dict(row=row_number,column=column))
            values.append(cell)
        append(values)
        expected.append(original)
    raw=output.getvalue();bounded(raw,MAX_CSV_BYTES)
    parsed=list(csv.reader(io.StringIO(raw.decode(),newline=""),strict=True));assert parsed[0]==list(columns)
    for cell in escaped:
        index=columns.index(cell["column"]);assert parsed[cell["row"]-1][index].startswith("'")
        parsed[cell["row"]-1][index]=parsed[cell["row"]-1][index][1:]
    review.require(parsed[1:]==expected,"proposal_csv_roundtrip_mismatch")
    return raw,dict(encoding="UTF-8",dialect="RFC4180",null_cell="",escape_policy="recorded_apostrophe_prefix/1",
        escaped_cells=escaped,columns=[dict(name=c,type="number_or_null" if c in NUMERIC_COLUMNS else "json_or_null" if c in JSON_COLUMNS else "boolean_or_null" if c=="approximate" else "text_or_null") for c in columns])


def package(packet, created):
    graph=complete_graph(packet,created);graph_raw=bounded(encoded(graph))
    pressure_native = graph['run']['extraction_version'] in PRESSURE_SCHEMAS
    version = PRESSURE_VERSION if pressure_native else VERSION
    visual = packet['receipt'].get('visual_support') is not None
    if visual: version = VISUAL_VERSION
    device_native = graph['run']['extraction_version']=='materials-ner/15'
    csv_raw,csv_contract=csv_files(review_records(graph), columns=DEVICE_COLUMNS if device_native else PRESSURE_COLUMNS if pressure_native else COLUMNS)
    readme = README + ('\npressure_declaration_json retains the source availability, regime, condition reference and literal basis.\nExplicit ambient pressure may have no numeric pressure condition; no zero is imputed.\nProcedure temperatures retain their roles in graph.json and are not measurement inputs by default.\n' if pressure_native else '')
    files={"graph.json":graph_raw,"results.csv":csv_raw,"README.txt":readme.encode()}
    if 'projector_review' in graph['coverage']:
        from services.materials_projector_review import captured
        captured(packet)
        version = PROJECTOR_VERSION
        # Exact original model bytes, including the invalid zero-row run. This
        # file is diagnostic, never a second set of accepted scientific rows.
        files['raw-model-graph.json'] = bounded(packet['raw_output'].encode())
        files['README.txt'] += ("\ncoverage.projector_review retains the authentic model identity, terminal outcome,\n"
            "assistant source findings and separate paper-completeness obligations.\n"
            "raw-model-graph.json is the exact original model response, including invalid graphs.\n"
            "Its objects are diagnostic output, not extra retained results or approved training rows.\n"
            "Source findings can identify scientific errors without changing the original graph.\n").encode()
    if visual:
        from services.materials_visual_evidence import export_files
        files.update(export_files(packet))
        files['README.txt'] += ("\nVisual evidence has kind=visual_region and a transcription, not an original PDF text quote.\n"
            "Its selector addresses retained OCR text; region coordinates are approximate guides on the original page.\n"
            "visual-evidence.json retains the assistant-selected OCR bindings, author, capture and optical provenance.\n"
            "source-images contains original rendered PNGs for inspection; these bytes also appear in the portable evidence sidecar.\n"
            "OCR confidence is not scientific confidence. Independent source and relation review remains required.\n").encode()
    if device_native:
        version=DEVICE_VERSION
        files['README.txt'] += ("\nstate_conditions_json retains every assigned state condition with its original role and source unit.\n"
            "Twist angles are not automatically preparation angles or trained features.\n"
            "Reported displacement fields have no inferred SI convention. Fit-intersection definitions retain their source wording.\n").encode()
    manifest=dict(version=version,scope="complete_retained_run",run=graph["run"],authority=review.AUTHORITY,
        counts={**{g:len(v) for g,v in graph["entities"].items()},"evidence":len(graph["evidence"]),
                "result_evidence_references":sum(len(x["evidence_ordinals"]) for x in graph["result_evidence"])},
        csv=csv_contract,files=[dict(name=n,bytes=len(b),sha256=sha(b)) for n,b in sorted(files.items())])
    files["manifest.json"]=encoded(manifest)
    if sum(map(len,files.values()))>MAX_UNCOMPRESSED_BYTES:raise review.ProposalUnavailable("proposal_export_total_limit")
    output=io.BytesIO()
    with ZipFile(output,"w",compression=ZIP_DEFLATED,compresslevel=9) as archive:
        for name,raw in sorted(files.items()):
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o600<<16
            archive.writestr(info,raw,compresslevel=9)
    raw=bounded(output.getvalue(),MAX_ARCHIVE_BYTES)
    descriptor=dict(version=version,scope="complete_retained_run",run=graph["run"],authority=review.AUTHORITY,
        filename=f"materials-review-{packet['run_id']}.zip",bytes=len(raw),sha256=sha(raw),counts=manifest["counts"],
        files=[dict(name=n,bytes=len(b),sha256=sha(b)) for n,b in sorted(files.items())])
    return descriptor,raw


async def run_export(db, actor_user_id, run_id):
    await review.admit(db,actor_user_id);await review.schema_ready(db)
    packet,created=await review.retained_packet(db,run_id)
    return package(packet,created)
