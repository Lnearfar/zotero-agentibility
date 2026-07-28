/*
 * Zotero-Paper-Agent bridge, version 0.3.0.
 *
 * Derived from cli-anything-zotero's zotero-cli-bridge/bootstrap.js and
 * substantially modified: arbitrary JavaScript execution was removed and
 * fixed-operation authentication, validation, and token handling were added.
 * Licensed under Apache-2.0; see LICENSE and UPSTREAM.md.
 */

var ENDPOINT = "/zotero-paper-agent/v1/operation";
var PROTOCOL = 1;
var VERSION = "0.3.0";
var MAX_BODY_BYTES = 4096;
var FULLTEXT_TAG = "zotero-cli:fulltext";
var SOURCE_TAG = "zotero-cli:source";
var ALLOWED_OPERATIONS = Object.freeze(["health", "fulltext_adopt"]);
var bearerToken = null;
var writeLocked = false;
var writeWaiters = [];
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

function _operationError(code, message, status, retryable, details) {
  var error = new Error(message);
  error.bridgeCode = code;
  error.httpStatus = status || 409;
  error.retryable = !!retryable;
  error.safeDetails = details || null;
  return error;
}

function _sendOperationError(handler, error) {
  var known = !!error.bridgeCode;
  if (!known) {
    Zotero.logError(new Error("Zotero-Paper-Agent internal write failure"));
  }
  var body = {
    ok: false,
    protocol: PROTOCOL,
    error: {
      code: known ? error.bridgeCode : "INTERNAL_ERROR",
      message: known ? error.message : "The Zotero write operation failed",
      retryable: known ? error.retryable : false
    }
  };
  if (known && error.safeDetails) body.error.details = error.safeDetails;
  _send(handler, known ? error.httpStatus : 500, body);
}

function _sameKeys(value, expected) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === expected.slice().sort().join(",");
}

function _validateAdoptArguments(args) {
  var keys = [
    "expected_path",
    "expected_sha256",
    "item_key",
    "markdown_attachment_key",
    "replace_attachment_keys",
    "session_id"
  ];
  if (!_sameKeys(args, keys)) {
    throw _operationError("BAD_ARGUMENTS", "fulltext_adopt arguments do not match the schema", 400);
  }
  var itemKey = /^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/;
  if (!itemKey.test(args.item_key) || !itemKey.test(args.markdown_attachment_key)) {
    throw _operationError("BAD_ARGUMENTS", "Item and attachment keys must be valid Zotero keys", 400);
  }
  if (typeof args.session_id !== "string"
      || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(args.session_id)
      || args.session_id === "." || args.session_id === "..") {
    throw _operationError("BAD_ARGUMENTS", "Session ID is invalid", 400);
  }
  if (typeof args.expected_path !== "string" || args.expected_path[0] !== "/"
      || args.expected_path.length > 2048 || args.expected_path.indexOf("\0") !== -1) {
    throw _operationError("BAD_ARGUMENTS", "Expected path must be a bounded absolute Linux path", 400);
  }
  if (typeof args.expected_sha256 !== "string"
      || !/^[0-9a-f]{64}$/.test(args.expected_sha256)) {
    throw _operationError("BAD_ARGUMENTS", "Expected SHA-256 is invalid", 400);
  }
  if (!Array.isArray(args.replace_attachment_keys)
      || args.replace_attachment_keys.length > 32) {
    throw _operationError("BAD_ARGUMENTS", "Replacement attachment keys must be a bounded array", 400);
  }
  var seen = Object.create(null);
  for (var i = 0; i < args.replace_attachment_keys.length; i++) {
    var key = args.replace_attachment_keys[i];
    if (typeof key !== "string" || !itemKey.test(key) || seen[key]) {
      throw _operationError("BAD_ARGUMENTS", "Replacement attachment keys must be unique Zotero keys", 400);
    }
    seen[key] = true;
  }
  return args;
}

function _acquireWriteLock() {
  if (!writeLocked) {
    writeLocked = true;
    return Promise.resolve();
  }
  if (writeWaiters.length >= 8) {
    return Promise.reject(_operationError("WRITE_BUSY", "Zotero write queue is full", 409, true));
  }
  return new Promise(function (resolve, reject) {
    var waiter = { resolve: resolve, timer: null };
    waiter.timer = setTimeout(function () {
      var index = writeWaiters.indexOf(waiter);
      if (index !== -1) writeWaiters.splice(index, 1);
      reject(_operationError("WRITE_BUSY", "Timed out waiting for the Zotero write lock", 409, true));
    }, 5000);
    writeWaiters.push(waiter);
  });
}

function _releaseWriteLock() {
  var waiter = writeWaiters.shift();
  if (waiter) {
    clearTimeout(waiter.timer);
    waiter.resolve();
    return;
  }
  writeLocked = false;
}

function _hasTag(item, name) {
  return item.getTags().some(function (tag) { return tag.tag === name; });
}

function _filename(item) {
  return String(item.attachmentFilename || "");
}

function _isMarkdownAttachment(item) {
  var contentType = String(item.attachmentContentType || "").toLowerCase();
  return contentType !== "application/pdf"
    && (_filename(item).toLowerCase().endsWith(".md")
      || contentType === "text/markdown" || contentType === "text/x-markdown");
}

function _rejectDistillation(item) {
  var filename = _filename(item).toLowerCase();
  if (filename === "distill.md" || filename === "probe_distill.md") {
    throw _operationError("INVALID_FULLTEXT_SOURCE", "Derived distillation cannot become Markdown Full Text", 409);
  }
}

function _sha256File(path) {
  var file = Zotero.File.pathToFile(path);
  if (!file.exists() || !file.isFile() || file.isSymlink()) {
    throw _operationError("ATTACHMENT_FILE_MISSING", "Attachment file is missing or unsafe", 409);
  }
  var input = Cc["@mozilla.org/network/file-input-stream;1"]
    .createInstance(Ci.nsIFileInputStream);
  var hash = Cc["@mozilla.org/security/hash;1"]
    .createInstance(Ci.nsICryptoHash);
  input.init(file, 0x01, 0, 0);
  try {
    hash.init(hash.SHA256);
    hash.updateFromStream(input, -1);
    var binary = hash.finish(false);
    var result = "";
    for (var i = 0; i < binary.length; i++) {
      result += binary.charCodeAt(i).toString(16).padStart(2, "0");
    }
    return result;
  }
  finally {
    input.close();
  }
}

async function _attachmentFile(item) {
  var path = await item.getFilePathAsync();
  if (!path) {
    throw _operationError("ATTACHMENT_FILE_MISSING", "Attachment file is missing", 409, false,
      { attachment_key: item.key });
  }
  var file = Zotero.File.pathToFile(path);
  if (!file.exists() || !file.isFile() || file.isSymlink()) {
    throw _operationError("ATTACHMENT_FILE_MISSING", "Attachment file is missing or unsafe", 409, false,
      { attachment_key: item.key });
  }
  return { path: file.path, filename: file.leafName };
}

function _prepareAuditFile() {
  var directory = _configDirectory();
  var file = directory.clone();
  file.append("audit.jsonl");
  if (!file.exists()) {
    var create = Cc["@mozilla.org/network/file-output-stream;1"]
      .createInstance(Ci.nsIFileOutputStream);
    create.init(file, 0x02 | 0x08 | 0x10, 0o600, 0);
    create.close();
  }
  if (file.isSymlink() || !file.isFile()) {
    throw _operationError("AUDIT_LOG_UNSAFE", "Audit log path is unsafe", 500);
  }
  file.permissions = 0o600;
  if ((file.permissions & 0o777) !== 0o600) {
    throw _operationError("AUDIT_LOG_UNSAFE", "Audit log permissions are unsafe", 500);
  }
  return file;
}

function _appendAudit(file, sessionId, operation, affectedKeys, result, errorCode) {
  var output = Cc["@mozilla.org/network/file-output-stream;1"]
    .createInstance(Ci.nsIFileOutputStream);
  output.init(file, 0x02 | 0x08 | 0x10, 0o600, 0);
  var data = JSON.stringify({
    time: new Date().toISOString(),
    sessionId: sessionId,
    operation: operation,
    affectedKeys: affectedKeys.filter(function (key, index, keys) {
      return keys.indexOf(key) === index;
    }),
    result: result,
    errorCode: errorCode || null
  }) + "\n";
  try {
    if (output.write(data, data.length) !== data.length) {
      throw new Error("short audit write");
    }
    output.flush();
  }
  finally {
    output.close();
  }
}

async function _reloadAfterRollback(parent, items) {
  try {
    await parent.reload(["primaryData", "childItems"], true);
  }
  catch (e) {}
  for (var i = 0; i < items.length; i++) {
    try {
      await items[i].reload(["primaryData", "tags"], true);
    }
    catch (e) {}
  }
}

async function _trashImported(item) {
  if (!item) return;
  try {
    await item.reload(["primaryData"], true);
    if (!item.deleted) await Zotero.Items.trashTx(item.id);
  }
  catch (e) {
    var error = _operationError("ROLLBACK_FAILED", "Could not move the failed imported attachment to Trash", 500, false,
      { attachment_key: item.key, rollback_result: "failed" });
    error.rollbackAttachmentKey = item.key;
    error.rollbackResult = "failed";
    throw error;
  }
}

async function _adoptFulltext(args) {
  var libraryID = Zotero.Libraries.userLibraryID;
  var parent = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.item_key);
  if (!parent || parent.deleted || !parent.isRegularItem() || parent.libraryID !== libraryID
      || !parent.isEditable()) {
    throw _operationError("ITEM_NOT_WRITABLE", "Literature Item is missing or not writable in My Library", 404,
      false, { item_key: args.item_key });
  }

  var source = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.markdown_attachment_key);
  if (!source || source.deleted || !source.isAttachment() || source.libraryID !== libraryID
      || source.parentItemID !== parent.id || !source.isEditable()) {
    throw _operationError("ATTACHMENT_NOT_WRITABLE", "Markdown attachment is missing or unrelated", 404,
      false, { attachment_key: args.markdown_attachment_key });
  }
  await source.loadDataType("tags");
  if (!_isMarkdownAttachment(source)) {
    throw _operationError("INVALID_FULLTEXT_SOURCE", "Selected attachment is not Markdown", 409);
  }
  _rejectDistillation(source);
  var sourceFile = await _attachmentFile(source);
  if (sourceFile.path !== args.expected_path) {
    throw _operationError("STALE_ATTACHMENT_PATH", "The selected Markdown attachment path changed after review", 409,
      false, { attachment_key: source.key });
  }
  if (_sha256File(sourceFile.path) !== args.expected_sha256) {
    throw _operationError("STALE_ATTACHMENT_HASH", "The selected Markdown attachment changed after review", 409,
      false, { attachment_key: source.key });
  }

  await parent.loadDataType("childItems");
  var children = await Zotero.Items.getAsync(parent.getAttachments(false));
  for (var i = 0; i < children.length; i++) await children[i].loadDataType("tags");
  var marked = children.filter(function (item) { return _hasTag(item, FULLTEXT_TAG); });
  var requiredReplacements = marked
    .filter(function (item) { return item.key !== source.key; })
    .map(function (item) { return item.key; }).sort();
  var providedReplacements = args.replace_attachment_keys.slice().sort();
  if (JSON.stringify(requiredReplacements) !== JSON.stringify(providedReplacements)) {
    throw _operationError("FULLTEXT_CONFLICT", "Explicit replacement keys do not match marked Full Text attachments", 409,
      false, { required_attachment_keys: requiredReplacements });
  }
  var replacements = [];
  for (var r = 0; r < providedReplacements.length; r++) {
    var replacement = children.find(function (item) { return item.key === providedReplacements[r]; });
    if (!replacement || !_hasTag(replacement, FULLTEXT_TAG) || !_isMarkdownAttachment(replacement)) {
      throw _operationError("FULLTEXT_CONFLICT", "Replacement attachment is missing or not marked Markdown Full Text", 409,
        false, { attachment_key: providedReplacements[r] });
    }
    _rejectDistillation(replacement);
    replacements.push(replacement);
  }

  var pdfs = children.filter(function (item) {
    return String(item.attachmentContentType || "").toLowerCase() === "application/pdf"
      || _filename(item).toLowerCase().endsWith(".pdf");
  });
  var taggedPdfs = pdfs.filter(function (item) { return _hasTag(item, SOURCE_TAG); });
  var sourceDocument;
  if (taggedPdfs.length === 1) sourceDocument = taggedPdfs[0];
  else if (taggedPdfs.length > 1 || pdfs.length > 1) {
    throw _operationError("AMBIGUOUS_SOURCE", "Multiple PDFs require exactly one marked Source Document", 409,
      false, { attachment_keys: pdfs.map(function (item) { return item.key; }) });
  }
  else if (pdfs.length === 1) sourceDocument = pdfs[0];
  else throw _operationError("SOURCE_NOT_FOUND", "No Source Document PDF was found", 409);

  var imported = null;
  var committed = false;
  var touched = [source].concat(replacements).concat([sourceDocument]);
  try {
    imported = await Zotero.Attachments.importFromFile({
      file: sourceFile.path,
      parentItemID: parent.id,
      title: "Markdown Full Text",
      fileBaseName: "fulltext",
      contentType: "text/markdown",
      saveOptions: { skipSelect: true }
    });
    var importedFile = await _attachmentFile(imported);
    if (imported.libraryID !== libraryID || imported.parentItemID !== parent.id
        || imported.attachmentLinkMode !== Zotero.Attachments.LINK_MODE_IMPORTED_FILE
        || imported.getField("title") !== "Markdown Full Text"
        || importedFile.filename !== "fulltext.md"
        || String(imported.attachmentContentType || "").toLowerCase() === "application/pdf"
        || _sha256File(importedFile.path) !== args.expected_sha256) {
      throw _operationError("IMPORTED_FULLTEXT_INVALID", "Imported Markdown Full Text failed validation", 500,
        false, { attachment_key: imported.key });
    }
    await imported.loadDataType("tags");
    await Zotero.DB.executeTransaction(async function () {
      await parent.reload(["primaryData", "childItems"], true);
      if (parent.deleted) {
        throw _operationError("STALE_ITEM", "Literature Item changed before the write committed", 409);
      }
      var finalChildren = await Zotero.Items.getAsync(parent.getAttachments(false));
      for (var c = 0; c < finalChildren.length; c++) {
        await finalChildren[c].reload(["primaryData", "tags"], true);
      }
      var finalSource = finalChildren.find(function (item) { return item.key === source.key; });
      if (!finalSource || !_isMarkdownAttachment(finalSource)) {
        throw _operationError("STALE_ITEM", "Selected Markdown attachment changed before commit", 409);
      }
      _rejectDistillation(finalSource);
      var finalSourceFile = await _attachmentFile(finalSource);
      if (finalSourceFile.path !== args.expected_path
          || _sha256File(finalSourceFile.path) !== args.expected_sha256) {
        throw _operationError("STALE_ATTACHMENT_HASH", "Selected Markdown attachment changed before commit", 409,
          false, { attachment_key: source.key });
      }
      var finalPdfs = finalChildren.filter(function (item) {
        return String(item.attachmentContentType || "").toLowerCase() === "application/pdf"
          || _filename(item).toLowerCase().endsWith(".pdf");
      });
      var finalTaggedPdfs = finalPdfs.filter(function (item) { return _hasTag(item, SOURCE_TAG); });
      var finalSourceDocument = finalTaggedPdfs.length === 1 ? finalTaggedPdfs[0]
        : finalTaggedPdfs.length === 0 && finalPdfs.length === 1 ? finalPdfs[0] : null;
      if (!finalSourceDocument || finalSourceDocument.key !== sourceDocument.key) {
        throw _operationError("AMBIGUOUS_SOURCE", "Source Document selection changed before commit", 409,
          false, { attachment_keys: finalPdfs.map(function (item) { return item.key; }) });
      }
      sourceDocument = finalSourceDocument;
      var finalMarked = finalChildren
        .filter(function (item) { return item.key !== imported.key && item.key !== source.key && _hasTag(item, FULLTEXT_TAG); })
        .map(function (item) { return item.key; }).sort();
      if (JSON.stringify(finalMarked) !== JSON.stringify(requiredReplacements)) {
        throw _operationError("FULLTEXT_CONFLICT", "Marked Full Text attachments changed before commit", 409,
          false, { required_attachment_keys: finalMarked });
      }
      for (var f = 0; f < requiredReplacements.length; f++) {
        var finalReplacement = finalChildren.find(function (item) {
          return item.key === requiredReplacements[f];
        });
        if (!finalReplacement || !_isMarkdownAttachment(finalReplacement)) {
          throw _operationError("FULLTEXT_CONFLICT", "Replacement attachment changed before commit", 409,
            false, { attachment_key: requiredReplacements[f] });
        }
        _rejectDistillation(finalReplacement);
      }
      imported.addTag(FULLTEXT_TAG, 0);
      await imported.save({ skipSelect: true });
      if (!_hasTag(sourceDocument, SOURCE_TAG)) {
        sourceDocument.addTag(SOURCE_TAG, 0);
        await sourceDocument.save({ skipSelect: true });
      }
      var trashIDs = [source.id].concat(replacements.map(function (item) { return item.id; }));
      await Zotero.Items.trash(trashIDs);
      if (!_hasTag(imported, FULLTEXT_TAG)) {
        throw new Error("new fulltext marker missing");
      }
    });
    committed = true;
  }
  catch (error) {
    if (!committed) {
      await _reloadAfterRollback(parent, touched);
      try {
        await _trashImported(imported);
        if (imported) {
          error.rollbackAttachmentKey = imported.key;
          error.rollbackResult = "trashed";
          error.safeDetails = Object.assign({}, error.safeDetails || {}, {
            rollback_attachment_key: imported.key,
            rollback_result: "trashed"
          });
        }
      }
      catch (rollbackError) {
        throw rollbackError;
      }
    }
    throw error;
  }

  return {
    item_key: parent.key,
    markdown_attachment_key: imported.key,
    adopted_attachment_key: source.key,
    trashed_attachment_keys: [source.key].concat(replacements.map(function (item) { return item.key; })),
    source_document_key: sourceDocument.key,
    sha256: args.expected_sha256
  };
}

async function _executeFulltextAdopt(args) {
  var auditFile = _prepareAuditFile();
  var locked = false;
  var affected = [args.item_key, args.markdown_attachment_key].concat(args.replace_attachment_keys);
  try {
    await _acquireWriteLock();
    locked = true;
    var result;
    try {
      result = await _adoptFulltext(args);
    }
    catch (error) {
      try {
        var failedKeys = error.rollbackAttachmentKey ? affected.concat([error.rollbackAttachmentKey]) : affected;
        var failureResult = error.rollbackResult === "failed" ? "failure_rollback_failed"
          : error.rollbackResult === "trashed" ? "failure_rolled_back" : "failure";
        _appendAudit(auditFile, args.session_id, "fulltext_adopt", failedKeys, failureResult,
          error.bridgeCode || "INTERNAL_ERROR");
      }
      catch (auditError) {
        throw _operationError("AUDIT_LOG_FAILED", "Write failed and the audit record could not be appended", 500);
      }
      throw error;
    }
    try {
      _appendAudit(auditFile, args.session_id, "fulltext_adopt",
        affected.concat([result.markdown_attachment_key, result.source_document_key]), "success", null);
    }
    catch (auditError) {
      throw _operationError("AUDIT_LOG_FAILED_AFTER_WRITE",
        "Full Text was adopted but the audit record could not be appended", 500, false,
        { item_key: result.item_key, markdown_attachment_key: result.markdown_attachment_key,
          trashed_attachment_keys: result.trashed_attachment_keys });
    }
    return result;
  }
  finally {
    if (locked) _releaseWriteLock();
  }
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

  if (!_sameKeys(request, ["arguments", "operation", "protocol"])) {
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
  if (request.operation === "health") {
    if (!_sameKeys(request.arguments, [])) {
      _send(handler, 400, _error("bad_arguments", "health arguments must be an empty object"));
      return;
    }
    _send(handler, 200, { ok: true, protocol: PROTOCOL, extension_version: VERSION });
    return;
  }

  var args;
  try {
    args = _validateAdoptArguments(request.arguments);
  }
  catch (error) {
    _sendOperationError(handler, error);
    return;
  }
  _executeFulltextAdopt(args).then(function (result) {
    _send(handler, 200, { ok: true, protocol: PROTOCOL, operation: "fulltext_adopt", result: result });
  }).catch(function (error) {
    _sendOperationError(handler, error);
  });
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

function _configDirectory() {
  if (Services.appinfo.OS !== "Linux") {
    throw new Error("This extension release supports Linux only");
  }
  var directory = Services.dirsvc.get("Home", Ci.nsIFile);
  directory.append(".config");
  _ensureDirectory(directory, 0o700, false);
  directory.append("zotero-paper-agent");
  _ensureDirectory(directory, 0o700, true);
  return directory;
}

function _loadOrCreateToken() {
  var file = _configDirectory();
  file = file.clone();
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
    Zotero.debug("[Zotero-Paper-Agent] bridge endpoint registered");
  }
  catch (e) {
    delete Zotero.Server.Endpoints[ENDPOINT];
    _removeServerHooks();
    bearerToken = null;
    bridgeEndpoint = null;
    Zotero.logError(new Error("Zotero-Paper-Agent bridge disabled: " + e.message));
  }
}

function shutdown() {
  delete Zotero.Server.Endpoints[ENDPOINT];
  _removeServerHooks();
  bearerToken = null;
  bridgeEndpoint = null;
  Zotero.debug("[Zotero-Paper-Agent] bridge endpoint removed");
}

function install() {}
function uninstall() {}
