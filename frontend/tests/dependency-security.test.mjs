import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

// Use a separate process so intentional prototype pollution cannot leak into
// application tests. Check both the direct and Markdown plugin renderer paths.
test('math renderers ignore inherited trust and block external-resource commands', () => {
  const child = spawnSync(process.execPath, ['--input-type=module', '-e', String.raw`
    import assert from 'node:assert/strict';
    import { createRequire } from 'node:module';
    const require = createRequire(import.meta.url);
    const pluginRequire = createRequire(require.resolve('rehype-katex'));
    for (const katex of [require('katex'), pluginRequire('katex')]) {
      Object.prototype.trust = true;
      try {
        for (const tex of ['\\href{https://renderer-check.invalid}{x}', '\\includegraphics{https://renderer-check.invalid/a.png}']) {
          const html = katex.renderToString(tex, {strict:'ignore',throwOnError:false});
          assert.doesNotMatch(html, /<(?:a|img)\b/i);
          assert.doesNotMatch(html, /(?:href|src)=["']https:/i);
        }
        const math = katex.renderToString('E=\\sqrt{\\xi^2+\\Delta^2}');
        assert.match(math, /<math\b/);
        assert.doesNotMatch(math, /katex-error/);
      } finally { delete Object.prototype.trust; }
    }
  `], {encoding:'utf8',timeout:10000});
  assert.equal(child.status, 0, child.stderr || child.stdout);
});
