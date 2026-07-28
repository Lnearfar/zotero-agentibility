/*
 * Zotero Agent Library bridge, version 0.1.1.
 *
 * Derived from cli-anything-zotero's zotero-cli-bridge/bootstrap.js and
 * substantially modified: arbitrary JavaScript execution was removed and
 * fixed-operation authentication, validation, and token handling were added.
 * Licensed under Apache-2.0; see LICENSE and UPSTREAM.md.
 */

var ENDPOINT = "/zotero-agent-library/v1/operation";
var PROTOCOL = 1;
var VERSION = "0.1.1";
var MAX_BODY_BYTES = 4096;
var ALLOWED_OPERATIONS = Object.freeze(["health"]);
var bearerToken = null;
var bridgeEndpoint = null;
var originalBodyData = null;
var originalHandleRequest = null;
var bridgeBodyData = null;
var bridgeHandleRequest = null;

var Cc = Components.classes;
var Ci = Components.interfaces;
var Services = ChromeUtils.importESModule(
  "resource://gre/modules/Services.sys.mjs"
).Services;

function _error(code, message) {
  return { ok: false, error: { code: code, message: message } };
}

function _send(handler, status, body) {
  handler._requestFinished(handler._generateResponse(
    status,
    { "Content-Type": "application/json", "Cache-Control": "no-store" },
    JSON.stringify(body)
  ));
}

function _authorized(value) {
  var expected = "Bearer " + bearerToken;
  if (typeof value !== "string" || value.length !== expected.length) {
    return false;
  }
  var difference = 0;
  for (var i = 0; i < expected.length; i++) {
    difference |= value.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return difference === 0;
}

function _handleBody(handler, raw) {
  var request;
  try {
    request = JSON.parse(raw);
  }
  catch (e) {
    _send(handler, 400, _error("bad_json", "Request body is not valid JSON"));
    return;
  }

  if (!request || typeof request !== "object" || Array.isArray(request)
      || Object.keys(request).sort().join(",") !== "arguments,operation,protocol") {
    _send(handler, 400, _error("bad_request", "Request body does not match the bridge schema"));
    return;
  }
  if (request.protocol !== PROTOCOL) {
    _send(handler, 400, _error("bad_protocol", "Unsupported bridge protocol"));
    return;
  }
  if (typeof request.operation !== "string"
      || ALLOWED_OPERATIONS.indexOf(request.operation) === -1) {
    _send(handler, 400, _error("unknown_operation", "Unknown operation"));
    return;
  }
  if (!request.arguments || typeof request.arguments !== "object"
      || Array.isArray(request.arguments) || Object.keys(request.arguments).length !== 0) {
    _send(handler, 400, _error("bad_arguments", "health arguments must be an empty object"));
    return;
  }

  _send(handler, 200, { ok: true, protocol: PROTOCOL, extension_version: VERSION });
}

function _installServerHooks() {
  var prototype = Zotero.Server && Zotero.Server.RequestHandler
    && Zotero.Server.RequestHandler.prototype;
  if (!prototype || typeof prototype._bodyData !== "function"
      || typeof prototype.handleRequest !== "function") {
    throw new Error("Unsupported Zotero local-server API");
  }

  originalBodyData = prototype._bodyData;
  originalHandleRequest = prototype.handleRequest;

  bridgeBodyData = function () {
    if (this.pathname !== ENDPOINT) {
      return originalBodyData.apply(this, arguments);
    }
    if (!_authorized(this.headers.authorization)) {
      _send(this, 403, _error("unauthorized", "Bearer authentication required"));
      return;
    }
    if (String(this.contentType || "").toLowerCase() !== "application/json") {
      _send(this, 400, _error("unsupported_media_type", "Content-Type must be application/json"));
      return;
    }
    if (this.bodyLength > MAX_BODY_BYTES) {
      _send(this, 400, _error("payload_too_large", "Request body exceeds 4096 bytes"));
      return;
    }
    var raw = "";
    try {
      if (this.bodyLength) {
        raw = Zotero.Server.networkStreamToString(
          this.request.bodyInputStream,
          this.bodyLength
        );
      }
    }
    catch (e) {
      _send(this, 400, _error("bad_json", "Request body is not valid UTF-8 JSON"));
      return;
    }
    _handleBody(this, raw);
  };

  bridgeHandleRequest = function () {
    if (this.request.path !== ENDPOINT) {
      return originalHandleRequest.apply(this, arguments);
    }

    var host = "";
    var authorization = "";
    try {
      host = this.request.getHeader("Host");
      authorization = this.request.getHeader("Authorization");
    }
    catch (e) {}
    if (!/^(?:127\.0\.0\.1|\[::1\]|localhost)(?::[0-9]+)?$/i.test(host)) {
      this.response.seizePower();
      _send(this, 400, _error("invalid_host", "Host must be localhost"));
      return;
    }
    if (this.request.method !== "POST") {
      this.response.seizePower();
      _send(this, 400, _error("unsupported_method", "Only POST is supported"));
      return;
    }
    if (!_authorized(authorization)) {
      this.response.seizePower();
      _send(this, 403, _error("unauthorized", "Bearer authentication required"));
      return;
    }

    // Zotero's server debug trace includes request headers. Redact the bearer
    // credential before that trace is emitted, then immediately restore debug.
    var debug = Zotero.debug;
    Zotero.debug = function (message) {
      if (typeof message === "string") {
        message = message.replace(
          /(^|\n)(Authorization\s*:\s*)[^\r\n]*/ig,
          "$1$2[redacted]"
        );
      }
      var args = Array.prototype.slice.call(arguments);
      args[0] = message;
      return debug.apply(this, args);
    };
    try {
      return originalHandleRequest.apply(this, arguments);
    }
    finally {
      Zotero.debug = debug;
    }
  };

  prototype._bodyData = bridgeBodyData;
  prototype.handleRequest = bridgeHandleRequest;
  if (prototype._bodyData !== bridgeBodyData
      || prototype.handleRequest !== bridgeHandleRequest) {
    throw new Error("Could not install safe Zotero local-server hooks");
  }
}

function _removeServerHooks() {
  var prototype = Zotero.Server && Zotero.Server.RequestHandler
    && Zotero.Server.RequestHandler.prototype;
  if (!prototype) return;
  if (prototype._bodyData === bridgeBodyData) prototype._bodyData = originalBodyData;
  if (prototype.handleRequest === bridgeHandleRequest) {
    prototype.handleRequest = originalHandleRequest;
  }
  originalBodyData = null;
  originalHandleRequest = null;
  bridgeBodyData = null;
  bridgeHandleRequest = null;
}

function _ensureDirectory(directory, mode, enforceMode) {
  if (!directory.exists()) {
    directory.create(Ci.nsIFile.DIRECTORY_TYPE, mode);
  }
  if (directory.isSymlink() || !directory.isDirectory()) {
    throw new Error("Bridge token directory is not a real directory");
  }
  if (enforceMode) directory.permissions = mode;
  var permissions = directory.permissions & 0o777;
  if ((enforceMode && permissions !== mode) || (!enforceMode && (permissions & 0o022))) {
    throw new Error("Bridge token directory permissions are unsafe");
  }
}

function _readToken(file) {
  var input = Cc["@mozilla.org/network/file-input-stream;1"]
    .createInstance(Ci.nsIFileInputStream);
  var converter = Cc["@mozilla.org/intl/converter-input-stream;1"]
    .createInstance(Ci.nsIConverterInputStream);
  input.init(file, 0x01, 0, 0);
  converter.init(input, "UTF-8", 128, 0);
  var token = "";
  var chunk = {};
  try {
    while (converter.readString(128, chunk)) token += chunk.value;
  }
  finally {
    converter.close();
  }
  if (!/^[0-9a-f]{64}\n?$/.test(token)) {
    throw new Error("Bridge token file has invalid contents");
  }
  return token.replace(/\n$/, "");
}

function _newToken() {
  var bytes = Cc["@mozilla.org/security/random-generator;1"]
    .createInstance(Ci.nsIRandomGenerator)
    .generateRandomBytes(32);
  var token = "";
  for (var i = 0; i < bytes.length; i++) {
    var value = typeof bytes === "string" ? bytes.charCodeAt(i) : bytes[i];
    token += value.toString(16).padStart(2, "0");
  }
  return token;
}

function _loadOrCreateToken() {
  if (Services.appinfo.OS !== "Linux") {
    throw new Error("This extension release supports Linux only");
  }

  var directory = Services.dirsvc.get("Home", Ci.nsIFile);
  directory.append(".config");
  _ensureDirectory(directory, 0o700, false);
  directory.append("zotero-agent-library");
  _ensureDirectory(directory, 0o700, true);

  var file = directory.clone();
  file.append("bridge-token");
  if (!file.exists()) {
    var token = _newToken();
    var output = Cc["@mozilla.org/network/file-output-stream;1"]
      .createInstance(Ci.nsIFileOutputStream);
    output.init(file, 0x02 | 0x08 | 0x80, 0o600, 0);
    try {
      var data = token + "\n";
      if (output.write(data, data.length) !== data.length) {
        throw new Error("Could not write complete bridge token");
      }
    }
    finally {
      output.close();
    }
  }

  if (file.isSymlink() || !file.isFile()) {
    throw new Error("Bridge token path is not a regular file");
  }
  file.permissions = 0o600;
  if ((file.permissions & 0o777) !== 0o600) {
    throw new Error("Could not establish mode 0600 on bridge token");
  }
  return _readToken(file);
}

function startup() {
  try {
    bearerToken = _loadOrCreateToken();
    _installServerHooks();

    bridgeEndpoint = function () {};
    bridgeEndpoint.prototype = {
      supportedMethods: ["POST"],
      supportedDataTypes: ["application/json"],
      permitBookmarklet: false,
      init: function () {
        return [500, "application/json", JSON.stringify(
          _error("server_error", "Safe request handler was not invoked")
        )];
      }
    };
    Zotero.Server.Endpoints[ENDPOINT] = bridgeEndpoint;
    Zotero.debug("[Zotero Agent Library] bridge endpoint registered");
  }
  catch (e) {
    delete Zotero.Server.Endpoints[ENDPOINT];
    _removeServerHooks();
    bearerToken = null;
    bridgeEndpoint = null;
    Zotero.logError(new Error("Zotero Agent Library bridge disabled: " + e.message));
  }
}

function shutdown() {
  delete Zotero.Server.Endpoints[ENDPOINT];
  _removeServerHooks();
  bearerToken = null;
  bridgeEndpoint = null;
  Zotero.debug("[Zotero Agent Library] bridge endpoint removed");
}

function install() {}
function uninstall() {}
