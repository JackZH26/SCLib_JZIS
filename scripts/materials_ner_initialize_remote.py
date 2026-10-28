"""Initialize only the private NER namespace using the existing migration job credential.

The secret stays on the VPS and is mounted read-only into an ephemeral container.
The current application image, network and runtime role are inspected there.
No API restart or public Alembic revision update occurs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess

REPO = Path(__file__).resolve().parents[1]
HOST_PROGRAM = r'''
import json,subprocess,sys,os
try:
    schema=json.load(sys.stdin)["schema_code"]
    app=json.loads(subprocess.run(["docker","inspect","sclib-api"],capture_output=True,text=True,check=True).stdout)[0]
    networks=list(app["NetworkSettings"]["Networks"])
    if len(networks)!=1:
        raise ValueError("ambiguous application network")
    role=subprocess.run(["docker","exec","sclib-api","python","-c",
        "import os; from sqlalchemy.engine import make_url; print(make_url(os.environ['DATABASE_URL']).username)"],
        capture_output=True,text=True,check=True).stdout.strip()
    secret="/etc/sclib/credentials/migration-database-url"
    if not os.path.isfile(secret) or not os.access(secret,os.R_OK):
        raise ValueError("dedicated migration credential unavailable")
    job=r"""
import json,os
from sqlalchemy import create_engine,text
from services.schema_lifecycle import migration_lock,sync_url,_database_url
try:
    engine=create_engine(sync_url(_database_url(migration=True)))
    with engine.connect() as connection:
        with migration_lock(connection):
            with connection.begin():
                connection.execute(text("SET LOCAL lock_timeout='10s'"))
                connection.execute(text("SET LOCAL statement_timeout='45s'"))
                connection.execute(text("SELECT pg_advisory_xact_lock(924601)"))
                exists=connection.execute(text("SELECT to_regclass('materials_ner_v1.schema_version')")).scalar()
                if not exists:
                    for sql in initialize_statements(): connection.execute(text(sql))
                fingerprint=connection.execute(text("SELECT fingerprint FROM materials_ner_v1.schema_version WHERE version='materials-ner-proposals/1'")).scalar()
                if fingerprint!=FINGERPRINT: raise ValueError("schema fingerprint mismatch")
                quoted=connection.dialect.identifier_preparer.quote(runtime_role)
                connection.execute(text("GRANT USAGE ON SCHEMA materials_ner_v1 TO "+quoted))
                connection.execute(text("GRANT SELECT,INSERT ON ALL TABLES IN SCHEMA materials_ner_v1 TO "+quoted))
                counts={name:connection.execute(text("SELECT count(*) FROM materials_ner_v1."+name)).scalar() for name in TABLES}
                current=list(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars())
    engine.dispose()
    print(json.dumps({"ok":True,"schema_fingerprint":fingerprint,"tables":counts,
        "public_alembic_revision":current,"public_alembic_changed":False,
        "runtime_grants":["schema_usage","select","insert"],"scientific_acceptance":False}))
except Exception as error:
    print(json.dumps({"ok":False,"error_class":type(error).__name__,
        "sqlstate":getattr(getattr(error,"orig",None),"sqlstate",None)}))
    raise SystemExit(1)
"""
    code="exec(compile("+repr(schema)+",'<frozen-ner-schema>','exec')); runtime_role="+repr(role)+"; exec(compile("+repr(job)+",'<dedicated-migration-job>','exec'))"
    result=subprocess.run(["docker","run","--rm","--pull","never","--network",networks[0],
        "--mount","type=bind,source="+secret+",target=/run/secrets/sclib-migration-database-url,readonly",
        "--env","SCLIB_MIGRATION_DATABASE_URL_FILE=/run/secrets/sclib-migration-database-url",
        "--entrypoint","python",app["Image"],"-c",code],capture_output=True,timeout=180)
    if result.stdout: sys.stdout.buffer.write(result.stdout)
    else: print(json.dumps({"ok":False,"error_class":"migration_container_failed"}))
    raise SystemExit(result.returncode)
except Exception as error:
    print(json.dumps({"ok":False,"error_class":type(error).__name__}))
    raise SystemExit(1)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise ValueError("receipt already exists")
    command = shlex.join(["python3", "-c", HOST_PROGRAM])
    request = {"schema_code": (REPO / "api/models/materials_ner_proposals_v1.py").read_text()}
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                             args.ssh_host, command], input=json.dumps(request).encode(),
                            capture_output=True, timeout=240)
    data = json.loads(result.stdout or b'{"ok":false,"error_class":"transport_failure"}')
    args.receipt.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    import os
    with args.receipt.open("x") as stream:
        os.chmod(args.receipt, 0o600)
        json.dump(data, stream, sort_keys=True)
    print(json.dumps(data))
    return int(result.returncode != 0 or not data.get("ok"))


if __name__ == "__main__":
    raise SystemExit(main())
