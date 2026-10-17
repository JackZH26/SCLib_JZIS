import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
test("committed SCWiki catalogue and search index match authored sources",()=>{
 const result=spawnSync(process.execPath,["scripts/scwiki-build.mjs","--check"],{encoding:"utf8"});
 assert.equal(result.status,0,result.stdout+result.stderr);
});
test("standalone packaging and E2E copies include content and scripts",()=>{
 const docker=readFileSync("Dockerfile","utf8"),server=readFileSync("tests/e2e/public-site-server.cjs","utf8"),config=readFileSync("next.config.js","utf8");
 assert.match(docker,/COPY --from=builder \/app\/content\/scwiki/);
 assert.match(docker,/COPY --from=builder \/app\/scripts/);
 assert.match(server,/"content", "scripts"/);
 assert.match(config,/outputFileTracingIncludes/);
});
