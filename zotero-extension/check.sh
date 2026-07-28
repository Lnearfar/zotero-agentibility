#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
XPI=${1:-build/zotero-agent-library-0.1.0.xpi}

require() {
  grep -Fq -- "$2" "$1" || {
    printf 'missing required text in %s: %s\n' "$1" "$2" >&2
    exit 1
  }
}

require manifest.json '"version": "0.1.0"'
require manifest.json '"id": "zotero-agent-library@local"'
require manifest.json '"strict_min_version": "7.0"'
if grep -Fqi 'update_url' manifest.json; then
  printf 'manifest.json must not contain an update URL\n' >&2
  exit 1
fi

require bootstrap.js 'var ENDPOINT = "/zotero-agent-library/v1/operation";'
require bootstrap.js 'var PROTOCOL = 1;'
require bootstrap.js 'var MAX_BODY_BYTES = 4096;'
require bootstrap.js 'var ALLOWED_OPERATIONS = Object.freeze(["health"]);'
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

printf 'Static validation passed\nBuilt %s\n%s\n' "$XPI" "$actual"
