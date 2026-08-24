#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
VERSION=$(python3 -c 'import json; print(json.load(open("manifest.json"))["version"])')
XPI=${1:-build/zotero-agentibility-$VERSION.xpi}

require() {
  grep -Fq -- "$2" "$1" || {
    printf 'missing required text in %s: %s\n' "$1" "$2" >&2
    exit 1
  }
}

require manifest.json '"id": "zotero-agentibility@local"'
require manifest.json '"update_url": "https://github.com/Lnearfar/zotero-agentibility/releases/latest/download/updates.json"'
require manifest.json '"strict_min_version": "7.0"'
require manifest.json '"strict_max_version": "10.*"'
require bootstrap.js 'var ENDPOINT = "/zotero-agentibility/v1/operation";'
require bootstrap.js 'var PROTOCOL = 1;'
require bootstrap.js 'var VERSION = null;'
require bootstrap.js 'function startup({ version })'
require bootstrap.js 'VERSION = version;'
require bootstrap.js 'var MAX_BODY_BYTES = 4096;'
require bootstrap.js 'var ALLOWED_OPERATIONS = Object.freeze(["health", "fulltext_adopt", "fulltext_import", "metadata_resolve", "add_file"]);'
require bootstrap.js 'source_path'
require bootstrap.js 'add_file'
require bootstrap.js 'library_id'
require bootstrap.js '_findAttachmentsByHash'
require bootstrap.js 'Zotero.Utilities.Internal.md5Async'
require bootstrap.js '_acquireAddLock()'
require bootstrap.js 'Zotero.MIME.getMIMETypeFromFile(file)'
require bootstrap.js 'Zotero.MIME.sniffForMIMEType(sample)'
require bootstrap.js 'await item.eraseTx();'
require bootstrap.js 'IDENTICAL_ATTACHMENT_AMBIGUOUS'
require bootstrap.js 'outcome: "added_unrecognized"'
require bootstrap.js 'expected_path: importedFile.path'
require bootstrap.js 'new Zotero.Duplicates(libraryID)'
require bootstrap.js 'Zotero.RecognizeDocument._recognize'
require bootstrap.js 'Zotero.RecognizeDocument.canRecognize'
require bootstrap.js 'Zotero.Utilities.extractIdentifiers'
require bootstrap.js 'function _candidateData(candidate)'
require bootstrap.js 'candidate.getField(name)'
require bootstrap.js 'new Zotero.Translate.Search()'
require bootstrap.js 'Zotero.Utilities.cleanISBN'
require bootstrap.js 'Zotero.Utilities.toISBN13'
require bootstrap.js 'supportedMethods: ["POST"]'
require bootstrap.js 'supportedDataTypes: ["application/json"]'
require bootstrap.js 'extension_version: VERSION'
require bootstrap.js 'invalid_host'
require bootstrap.js 'unsupported_method'
require bootstrap.js 'unauthorized'
require bootstrap.js 'bad_json'
require bootstrap.js 'bad_protocol'
require bootstrap.js 'unknown_operation'
require bootstrap.js 'payload_too_large'
require bootstrap.js 'Zotero.Attachments.importFromFile'
require bootstrap.js 'Zotero.DB.executeTransaction'
require bootstrap.js 'Zotero.Items.trash'
require bootstrap.js 'hash.SHA256'
require bootstrap.js 'expectedAttachmentSha256'
require bootstrap.js 'isEPUBAttachment()'
require bootstrap.js 'application/epub+zip'
require bootstrap.js 'audit.jsonl'
if grep -Eq 'Zotero\.DB\.(queryAsync|executeSQL)|OS\.File\.(copy|move|write)|IOUtils\.write' bootstrap.js; then
  printf 'bootstrap.js contains prohibited direct database or storage writes\n' >&2
  exit 1
fi
if sed -n '/async function _cleanupAddedItems/,/function _sourceDocumentFromChildren/p' bootstrap.js | grep -Fq '_trashImported'; then
  printf 'add_file rollback must erase new items, not call _trashImported\n' >&2
  exit 1
fi
if sed -n '/var identifiers = candidate ?/,/var matches =/p' bootstrap.js | grep -Fq 'addTag(SOURCE_TAG'; then
  printf 'unrecognized document branch must not add the Source Document marker\n' >&2
  exit 1
fi
if sed -n '/async function _addFile(args)/,/async function _executeAddFile/p' bootstrap.js | grep -Eq '^[[:space:]]*contentType[[:space:]]*:'; then
  printf 'add_file import must let Zotero detect native MIME type\n' >&2
  exit 1
fi
if ! sed -n '/async function _executeAddFile(args)/,/function _prepareAuditFile/p' bootstrap.js \
    | grep -Fq 'await _acquireAddLock();'; then
  printf 'add_file must serialize intake flows before preflight and recognition\n' >&2
  exit 1
fi
node <<'NODE'
const fs = require("fs");
const text = fs.readFileSync("bootstrap.js", "utf8");
function body(name) {
  const start = text.indexOf(name);
  if (start < 0) throw new Error("missing " + name);
  let open = text.indexOf("{", start), depth = 0, quote = null, line = false, block = false;
  for (let i = open; i < text.length; i++) {
    const c = text[i], n = text[i + 1];
    if (line) { if (c === "\n") line = false; continue; }
    if (block) { if (c === "*" && n === "/") { block = false; i++; } continue; }
    if (quote) { if (c === "\\") i++; else if (c === quote) quote = null; continue; }
    if (c === "/" && n === "/") { line = true; i++; continue; }
    if (c === "/" && n === "*") { block = true; i++; continue; }
    if (c === '"' || c === "'" || c === "`") { quote = c; continue; }
    if (c === "{") depth++;
    if (c === "}" && --depth === 0) return text.slice(open, i + 1);
  }
  throw new Error("unbalanced " + name);
}
function requireText(haystack, needle, message) {
  if (!haystack.includes(needle)) throw new Error(message || ("missing " + needle));
}
const sourceValidation = body("async function _validateAddFilePath");
requireText(sourceValidation, "_sniffDocumentContentType(file)", "source validation trusts the filename MIME without magic-byte sniffing");
const importedValidation = body("async function _validateImportedDocument");
requireText(importedValidation, "detectedContentType !== contentType", "imported copy lacks magic-byte revalidation");
const hashScan = body("async function _findAttachmentsByHash");
requireText(hashScan, "attachmentHash", "MD5 prefilter was removed");
requireText(hashScan, "_sha256File(file.path)", "candidate SHA-256 verification missing");
requireText(body("async function _reuseAddedAttachment"), "_sha256File(existingFile.path)", "exact reuse lacks final SHA-256 revalidation");
requireText(body("async function _reuseStrongSource"), "_sha256File(sourceFile.path)", "Strong-ID reuse lacks final SHA-256 revalidation");
const add = body("async function _addFile(args)");
requireText(add, "RecognizeDocument._recognize", "add flow lost native recognition");
requireText(add, "_duplicateWarnings", "add flow lost duplicate warning scan");
requireText(add, "imported = await Zotero.Attachments.importFromFile", "imported item is not retained before validation/rollback");
requireText(add, "await _validateImportedDocument", "imported item validation missing");
if (add.includes("_acquireWriteLock")) throw new Error("add flow holds the global lock across scans/recognition");
const execute = body("async function _executeAddFile");
requireText(execute, "await _acquireAddLock()", "all add flows must be serialized for Strong-Identifier safety");
if (execute.includes("await _acquireWriteLock")) throw new Error("executeAddFile holds global lock across add flow");
if (text.includes("identityLocks")) throw new Error("per-hash guard cannot serialize different files with one Strong Identifier");
if (/isEPUBAttachment\(\)[\s\S]{0,160}addTag\(SOURCE_TAG/.test(text)) throw new Error("EPUB receives PDF-only Source Document tag");
console.log("Static identity/lock contract passed");
NODE
if ! sed -n '/async function _attachAddedToParent(/,/async function _reuseAddedAttachment/p' bootstrap.js \
    | grep -Fq 'if (imported.isPDFAttachment()) imported.addTag(SOURCE_TAG, 0);'; then
  printf 'parent PDF imports must receive the Source Document marker\n' >&2
  exit 1
fi
if sed -n '/async function _attachAddedToParent(/,/async function _reuseAddedAttachment/p' bootstrap.js \
    | grep -Fq 'imported.isEPUBAttachment()'; then
  printf 'parent EPUB imports must not receive the PDF-only Source Document marker\n' >&2
  exit 1
fi
if grep -Eq '(^|[^[:alnum:]_$])eval[[:space:]]*\(|new[[:space:]]+Function[[:space:]]*\(' bootstrap.js; then
  printf 'bootstrap.js contains dynamic code execution\n' >&2
  exit 1
fi

mkdir -p "$(dirname -- "$XPI")"
rm -f "$XPI"
zip -X -q "$XPI" manifest.json bootstrap.js LICENSE UPSTREAM.md
expected='manifest.json
bootstrap.js
LICENSE
UPSTREAM.md'
actual=$(unzip -Z1 "$XPI")
if [ "$actual" != "$expected" ]; then
  printf 'unexpected XPI contents:\n%s\n' "$actual" >&2
  exit 1
fi

HASH=$(sha256sum "$XPI" | cut -d' ' -f1)
cat > updates.json <<EOF
{
  "addons": {
    "zotero-agentibility@local": {
      "updates": [
        {
          "version": "$VERSION",
          "update_link": "https://github.com/Lnearfar/zotero-agentibility/releases/download/v$VERSION/zotero-agentibility-$VERSION.xpi",
          "update_hash": "sha256:$HASH",
          "applications": {
            "zotero": {
              "strict_min_version": "7.0",
              "strict_max_version": "10.*"
            }
          }
        }
      ]
    }
  }
}
EOF

printf 'Static validation passed\nBuilt %s\nUpdated updates.json\n%s\n' "$XPI" "$actual"
