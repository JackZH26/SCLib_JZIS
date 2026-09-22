import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import ts from "typescript";

const root = fileURLToPath(new URL("../", import.meta.url));
function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(file) : /\.[jt]sx?$/.test(entry.name) ? [file] : [];
  });
}
const files = ["app", "components", "lib"].flatMap(directory => sourceFiles(path.join(root, directory)));

test("default UI has no embedded Chinese copy; query regexes and comments remain supported", () => {
  const violations = [];
  for (const file of files) {
    const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
    function visit(node) {
      const isText = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node) || ts.isJsxText(node);
      if (isText && /\p{Script=Han}/u.test(node.text)) violations.push(`${path.relative(root, file)}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  assert.deepEqual(violations, [], "Translate authored UI text, not multilingual input handling.");
});

test("date and number display explicitly uses an English locale", () => {
  const violations = [];
  for (const file of files) {
    const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
    function visit(node) {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && /^toLocale(String|DateString|TimeString)$/.test(node.expression.name.text)) {
        const locale = node.arguments[0];
        if (!locale || !ts.isStringLiteral(locale) || !/^en(?:-|$)/.test(locale.text)) violations.push(path.relative(root, file));
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  assert.deepEqual(violations, []);
});

test("document language and metadata remain English", () => {
  const layout = readFileSync(path.join(root, "app/layout.tsx"), "utf8");
  assert.match(layout, /<html lang="en"/);
  assert.match(layout, /locale:\s*"en_US"/);
});
