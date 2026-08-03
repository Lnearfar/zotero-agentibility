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
require manifest.json '"strict_max_version": "9.*"'
require bootstrap.js 'var ENDPOINT = "/zotero-agentibility/v1/operation";'
require bootstrap.js 'var PROTOCOL = 1;'
require bootstrap.js 'var VERSION = null;'
require bootstrap.js 'function startup({ version })'
require bootstrap.js 'VERSION = version;'
require bootstrap.js 'var MAX_BODY_BYTES = 4096;'
require bootstrap.js 'var ALLOWED_OPERATIONS = Object.freeze(["health", "fulltext_adopt", "fulltext_import"]);'
require bootstrap.js 'source_path'
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
require bootstrap.js 'audit.jsonl'
if grep -Eq 'Zotero\.DB\.(queryAsync|executeSQL)|OS\.File\.(copy|move|write)|IOUtils\.write' bootstrap.js; then
  printf 'bootstrap.js contains prohibited direct database or storage writes\n' >&2
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
              "strict_max_version": "9.*"
            }
          }
        }
      ]
    }
  }
}
EOF

printf 'Static validation passed\nBuilt %s\nUpdated updates.json\n%s\n' "$XPI" "$actual"
