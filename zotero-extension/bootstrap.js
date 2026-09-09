/*
 * Zotero-Agentibility bridge.
 *
 * Derived from cli-anything-zotero's zotero-cli-bridge/bootstrap.js and
 * substantially modified: arbitrary JavaScript execution was removed and
 * fixed-operation authentication, validation, and token handling were added.
 * Licensed under Apache-2.0; see LICENSE and UPSTREAM.md.
 */

var ENDPOINT = "/zotero-agentibility/v1/operation";
var PROTOCOL = 1;
var VERSION = null;
var MAX_BODY_BYTES = 4096;
var FULLTEXT_TAG = "za-cli:md";
var SOURCE_TAG = "za-cli:pdf";
var ALLOWED_OPERATIONS = Object.freeze(["health", "fulltext_adopt", "fulltext_import", "metadata_resolve", "add_file", "index_catalog"]);
var bearerToken = null;
var writeLocked = false;
var writeWaiters = [];
var addLocked = false;
var addWaiters = [];
var bridgeEndpoint = null;
var originalBodyData = null;
var originalHandleRequest = null;
var bridgeBodyData = null;
var bridgeHandleRequest = null;
var agentibilityRuntime = null;
var extensionRunning = false;

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
    Zotero.logError(new Error("Zotero-Agentibility internal write failure"));
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

function _validateFulltextArguments(args, operation) {
  var importing = operation === "fulltext_import";
  var keys = importing
    ? ["expected_sha256", "item_key", "replace_attachment_keys", "source_path"]
    : ["expected_path", "expected_sha256", "item_key", "markdown_attachment_key",
      "replace_attachment_keys"];
  if (!_sameKeys(args, keys)) {
    throw _operationError("BAD_ARGUMENTS", operation + " arguments do not match the schema", 400);
  }
  var itemKey = /^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/;
  if (!itemKey.test(args.item_key)
      || (!importing && !itemKey.test(args.markdown_attachment_key))) {
    throw _operationError("BAD_ARGUMENTS", "Item and attachment keys must be valid Zotero keys", 400);
  }
  var path = importing ? args.source_path : args.expected_path;
  if (typeof path !== "string" || path[0] !== "/"
      || path.length > 2048 || path.indexOf("\0") !== -1) {
    throw _operationError("BAD_ARGUMENTS", "Full Text source path must be a bounded absolute Linux path", 400);
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

function _validateAddFileArguments(args) {
  var keys = ["collection_key", "expected_sha256", "library_id", "parent_item_key", "source_path"];
  if (!_sameKeys(args, keys)) {
    throw _operationError("BAD_ARGUMENTS", "add_file arguments do not match the schema", 400);
  }
  var itemKey = /^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/;
  if (!Number.isInteger(args.library_id) || args.library_id < 1) {
    throw _operationError("BAD_ARGUMENTS", "Library ID must be a positive integer", 400);
  }
  if (args.collection_key !== null
      && (typeof args.collection_key !== "string" || !itemKey.test(args.collection_key))) {
    throw _operationError("BAD_ARGUMENTS", "Collection Key must be a valid Zotero key or null", 400);
  }
  if (args.parent_item_key !== null
      && (typeof args.parent_item_key !== "string" || !itemKey.test(args.parent_item_key))) {
    throw _operationError("BAD_ARGUMENTS", "Parent Item Key must be a valid Zotero key or null", 400);
  }
  if (typeof args.source_path !== "string" || args.source_path[0] !== "/"
      || args.source_path.length > 2048 || args.source_path.indexOf("\0") !== -1
      || !/\.(?:pdf|epub)$/i.test(args.source_path)) {
    throw _operationError("BAD_ARGUMENTS", "Add source must be a bounded absolute PDF or EPUB path", 400);
  }
  if (typeof args.expected_sha256 !== "string"
      || !/^[0-9a-f]{64}$/.test(args.expected_sha256)) {
    throw _operationError("BAD_ARGUMENTS", "Expected SHA-256 is invalid", 400);
  }
  return args;
}

function _validateMetadataArguments(args) {
  var keys = ["attachment_key", "expected_path", "expected_sha256", "markdown_path", "markdown_sha256"];
  if (!_sameKeys(args, keys)) {
    throw _operationError("BAD_ARGUMENTS", "metadata_resolve arguments do not match the schema", 400);
  }
  if (!/^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/.test(args.attachment_key)) {
    throw _operationError("BAD_ARGUMENTS", "Attachment Key must be a valid Zotero key", 400);
  }
  if (typeof args.expected_path !== "string" || args.expected_path[0] !== "/"
      || args.expected_path.length > 2048 || args.expected_path.indexOf("\0") !== -1
      || typeof args.expected_sha256 !== "string"
      || !/^[0-9a-f]{64}$/.test(args.expected_sha256)) {
    throw _operationError("BAD_ARGUMENTS", "Document path or SHA-256 is invalid", 400);
  }
  var noMarkdown = args.markdown_path === null && args.markdown_sha256 === null;
  var validMarkdown = typeof args.markdown_path === "string" && args.markdown_path[0] === "/"
    && args.markdown_path.length <= 2048 && args.markdown_path.indexOf("\0") === -1
    && args.markdown_path.toLowerCase().endsWith(".md")
    && typeof args.markdown_sha256 === "string" && /^[0-9a-f]{64}$/.test(args.markdown_sha256);
  if (!noMarkdown && !validMarkdown) {
    throw _operationError("BAD_ARGUMENTS", "Markdown path and SHA-256 must both be valid or null", 400);
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

async function _withWriteLock(operation) {
  await _acquireWriteLock();
  try {
    return await operation();
  }
  finally {
    _releaseWriteLock();
  }
}

function _acquireAddLock() {
  if (!addLocked) {
    addLocked = true;
    return Promise.resolve();
  }
  if (addWaiters.length >= 8) {
    return Promise.reject(_operationError("WRITE_BUSY", "Document add queue is full", 409, true));
  }
  return new Promise(function (resolve, reject) {
    var waiter = { resolve: resolve, timer: null };
    waiter.timer = setTimeout(function () {
      var index = addWaiters.indexOf(waiter);
      if (index !== -1) addWaiters.splice(index, 1);
      reject(_operationError("WRITE_BUSY", "Timed out waiting for document intake", 409, true));
    }, 5000);
    addWaiters.push(waiter);
  });
}

function _releaseAddLock() {
  var waiter = addWaiters.shift();
  if (waiter) {
    clearTimeout(waiter.timer);
    waiter.resolve();
    return;
  }
  addLocked = false;
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

function _rejectDistillationFilename(filename) {
  filename = String(filename || "").toLowerCase();
  if (filename === "distill.md" || filename === "probe_distill.md") {
    throw _operationError("INVALID_FULLTEXT_SOURCE", "Derived distillation cannot become Markdown Full Text", 409);
  }
}

function _rejectDistillation(item) {
  _rejectDistillationFilename(_filename(item));
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

function _strongIdentifiers(text) {
  var found = Object.create(null);
  Zotero.Utilities.extractIdentifiers(String(text || "")).forEach(function (identifier) {
    var kind = Object.keys(identifier)[0];
    var value = identifier[kind];
    if (kind === "ISBN") value = Zotero.Utilities.toISBN13(Zotero.Utilities.cleanISBN(value));
    if (kind === "DOI") value = Zotero.Utilities.cleanDOI(value).toLowerCase();
    if (kind === "arXiv") value = value.replace(/v\d+$/i, "");
    var key = kind + ":" + String(value).toLowerCase();
    var query = {};
    query[kind] = value;
    found[key] = { key: key, query: query };
  });
  return Object.keys(found).map(function (key) { return found[key]; });
}

function _candidateData(candidate) {
  if (!candidate || typeof candidate.getField !== "function") return candidate || {};
  function field(name) {
    try { return candidate.getField(name) || ""; }
    catch (error) { return ""; }
  }
  return {
    DOI: field("DOI"),
    ISBN: field("ISBN"),
    extra: field("extra"),
    url: field("url"),
    archiveID: field("archiveID"),
    title: field("title")
  };
}

function _candidateIdentifierText(candidate) {
  var data = _candidateData(candidate);
  return [data.DOI, data.ISBN, data.extra, data.url, data.archiveID].filter(Boolean).join("\n");
}

function _itemIdentifierText(item) {
  return _candidateIdentifierText(item);
}

function _identifierKeys(identifiers) {
  var keys = Object.create(null);
  (identifiers || []).forEach(function (identifier) {
    keys[identifier.key] = identifier;
  });
  return keys;
}

async function _activeLibraryItems(libraryID) {
  var items = await Zotero.Items.getAll(libraryID, false, false);
  if (!Array.isArray(items)) items = items ? [items] : [];
  return items.filter(function (item) {
    return item && !item.deleted && item.libraryID === libraryID;
  });
}

async function _activeStoredDocumentFile(item) {
  if (!item || !item.isAttachment || !item.isAttachment()
      || item.attachmentLinkMode !== Zotero.Attachments.LINK_MODE_IMPORTED_FILE
      || (!item.isPDFAttachment() && !item.isEPUBAttachment())) {
    return null;
  }
  if (item.parentItemID) {
    var parent = await Zotero.Items.getAsync(item.parentItemID);
    if (!parent || parent.deleted) return null;
  }
  try {
    var path = await item.getFilePathAsync();
    if (!path) return null;
    var file = Zotero.File.pathToFile(path);
    if (!file.exists() || !file.isFile() || file.isSymlink()) return null;
    return file;
  }
  catch (error) {
    return null;
  }
}

async function _findStrongIdentifierMatches(libraryID, candidate, excludeID) {
  var wanted = _identifierKeys(_strongIdentifiers(_itemIdentifierText(candidate)));
  var keys = Object.keys(wanted);
  if (!keys.length) return [];
  var matches = [];
  var items = await _activeLibraryItems(libraryID);
  for (var i = 0; i < items.length; i++) {
    var item = items[i];
    if (item.id === excludeID || !item.isRegularItem || !item.isRegularItem()) continue;
    var identifiers = _strongIdentifiers(_itemIdentifierText(item));
    for (var j = 0; j < identifiers.length; j++) {
      if (wanted[identifiers[j].key]) {
        matches.push({ item: item, identifier: wanted[identifiers[j].key] });
        break;
      }
    }
  }
  return matches;
}

async function _findAttachmentsByHash(libraryID, md5, fileSize, expectedSha256) {
  var items = await _activeLibraryItems(libraryID);
  var matches = [];
  for (var i = 0; i < items.length; i++) {
    var item = items[i];
    var file = await _activeStoredDocumentFile(item);
    if (!file || Number(file.fileSize) !== Number(fileSize)) continue;
    try {
      var attachmentHash = await item.attachmentHash;
      if (attachmentHash && String(attachmentHash).toLowerCase() === String(md5).toLowerCase()
          && _sha256File(file.path) === expectedSha256) {
        matches.push(item);
      }
    }
    catch (error) {
      Zotero.debug("[Zotero-Agentibility] skipping unreadable attachment hash");
    }
  }
  return matches;
}

async function _attachmentSha256(item) {
  try {
    var file = await _attachmentFile(item);
    return _sha256File(file.path);
  }
  catch (error) {
    return null;
  }
}

async function _sourceDocument(item) {
  await item.loadDataType("childItems");
  var children = await Zotero.Items.getAsync(item.getAttachments(false));
  if (!Array.isArray(children)) children = children ? [children] : [];
  for (var i = 0; i < children.length; i++) await children[i].loadDataType("tags");
  return _sourceDocumentFromChildren(children);
}

async function _addCollectionMembership(item, collection) {
  if (!collection) return false;
  var liveCollection = Zotero.Collections.getByLibraryAndKey(item.libraryID, collection.key);
  if (!liveCollection || liveCollection.deleted || liveCollection.libraryID !== item.libraryID) {
    throw _operationError("COLLECTION_NOT_FOUND", "Collection changed before the write committed", 409,
      false, { collection_key: collection.key });
  }
  collection = liveCollection;
  await item.loadDataType("collections");
  if (item.getCollections().indexOf(collection.id) !== -1) return false;
  item.addToCollection(collection.id);
  await item.save();
  return true;
}

async function _duplicateWarnings(libraryID, item) {
  var warnings = [];
  try {
    var duplicates = new Zotero.Duplicates(libraryID);
    await duplicates.getSearchObject();
    var ids = duplicates.getSetItemsByItemID(item.id).filter(function (id) { return id !== item.id; });
    var candidates = await Zotero.Items.getAsync(ids);
    if (!Array.isArray(candidates)) candidates = candidates ? [candidates] : [];
    candidates.filter(function (candidate) {
      return candidate && !candidate.deleted && candidate.isRegularItem && candidate.isRegularItem();
    }).forEach(function (candidate) {
      warnings.push({
        code: "POSSIBLE_DUPLICATE",
        item_key: candidate.key,
        title: candidate.getField("title") || ""
      });
    });
  }
  catch (error) {
    warnings.push({ code: "DUPLICATE_CHECK_UNAVAILABLE" });
  }
  return warnings;
}

function _titleMatchesMarkdown(candidate, markdown) {
  var data = _candidateData(candidate);
  function normalize(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  }
  var title = normalize(data.title);
  return title.length >= 16 && normalize(String(markdown || "").slice(0, 32768)).indexOf(title) !== -1;
}

async function _discardMetadataCandidate(candidate) {
  try {
    await candidate.reload(["primaryData", "childItems"], true);
    if (candidate.getAttachments().length || candidate.getNotes().length) throw new Error("candidate gained children");
    await candidate.eraseTx();
  }
  catch (error) {
    throw _operationError("ROLLBACK_FAILED", "Could not remove the rejected metadata candidate", 500,
      false, { candidate_item_key: candidate.key, rollback_result: "failed" });
  }
}

async function _attachMetadataCandidate(attachment, candidate, args) {
  if (candidate.id) await candidate.loadDataType("collections");
  await Zotero.DB.executeTransaction(async function () {
    await attachment.reload(["primaryData", "tags", "collections"], true);
    if (attachment.deleted || attachment.parentItemID) {
      throw _operationError("STALE_DOCUMENT", "Standalone document changed before commit", 409);
    }
    var finalFile = await _attachmentFile(attachment);
    if (finalFile.path !== args.expected_path || _sha256File(finalFile.path) !== args.expected_sha256) {
      throw _operationError("STALE_DOCUMENT", "Standalone document changed before commit", 409);
    }
    attachment.getCollections().forEach(function (collectionID) { candidate.addToCollection(collectionID); });
    await candidate.save();
    attachment.parentID = candidate.id;
    if (attachment.isPDFAttachment() && !_hasTag(attachment, SOURCE_TAG)) {
      attachment.addTag(SOURCE_TAG, 0);
    }
    await attachment.save();
  });
}

async function _translateIdentifier(identifier) {
  var translate = new Zotero.Translate.Search();
  translate.setIdentifier(identifier.query);
  var translators = await translate.getTranslators();
  if (!translators.length) return null;
  translate.setTranslator(translators);
  var ambiguous = false;
  translate.setHandler("select", function (translation, items, callback) {
    var keys = Object.keys(items || {});
    ambiguous = keys.length !== 1;
    callback(ambiguous ? {} : items);
  });
  var results = await translate.translate({ libraryID: false, saveAttachments: false });
  if (ambiguous || results.length !== 1) return null;
  return _strongIdentifiers(_candidateIdentifierText(results[0])).some(function (item) {
    return item.key === identifier.key;
  }) ? results[0] : null;
}

async function _resolveMetadata(args) {
  var libraryID = Zotero.Libraries.userLibraryID;
  var attachment = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.attachment_key);
  if (!attachment || attachment.deleted || !attachment.isAttachment() || attachment.parentItemID
      || attachment.libraryID !== libraryID || !attachment.isEditable()
      || !Zotero.RecognizeDocument.canRecognize(attachment)) {
    throw _operationError("UNRECOGNIZED_DOCUMENT_NOT_FOUND",
      "Active standalone PDF or EPUB is missing or not writable in My Library", 404,
      false, { attachment_key: args.attachment_key });
  }
  var sourceFile = await _attachmentFile(attachment);
  if (sourceFile.path !== args.expected_path || _sha256File(sourceFile.path) !== args.expected_sha256) {
    throw _operationError("STALE_DOCUMENT", "Standalone document changed after review", 409,
      false, { attachment_key: attachment.key });
  }

  var markdown = null;
  var markdownIdentifiers = [];
  if (args.markdown_path) {
    var markdownFile = Zotero.File.pathToFile(args.markdown_path);
    if (!markdownFile.exists() || !markdownFile.isFile() || markdownFile.isSymlink()
        || markdownFile.path !== args.markdown_path || markdownFile.fileSize > 50 * 1024 * 1024
        || _sha256File(markdownFile.path) !== args.markdown_sha256) {
      throw _operationError("STALE_MARKDOWN", "Markdown fallback changed after review", 409);
    }
    markdown = await Zotero.File.getContentsAsync(markdownFile.path);
    markdownIdentifiers = _strongIdentifiers(markdown);
  }

  var nativeParent = null;
  try {
    nativeParent = await Zotero.RecognizeDocument._recognize(attachment);
  }
  catch (error) {
    Zotero.debug("[Zotero-Agentibility] native metadata recognition did not resolve " + attachment.key);
  }
  if (nativeParent) {
    if (_strongIdentifiers(_candidateIdentifierText(nativeParent)).length) {
      try {
        await _withWriteLock(function () {
          return _attachMetadataCandidate(attachment, nativeParent, args);
        });
      }
      catch (error) {
        await _withWriteLock(function () { return _discardMetadataCandidate(nativeParent); });
        throw error;
      }
      return { attachment_key: attachment.key, parent_item_key: nativeParent.key, resolution: "native" };
    }
    await _withWriteLock(function () { return _discardMetadataCandidate(nativeParent); });
  }

  if (!markdown || markdownIdentifiers.length !== 1) {
    throw _operationError("METADATA_UNRESOLVED",
      "Native recognition failed and Markdown did not contain exactly one Strong Identifier", 409,
      false, { identifier_count: markdownIdentifiers.length });
  }
  var translated = await _translateIdentifier(markdownIdentifiers[0]);
  if (!translated || !_titleMatchesMarkdown(translated, markdown)) {
    throw _operationError("METADATA_UNRESOLVED",
      "The unique Markdown identifier did not resolve to a matching title", 409);
  }

  var candidate = new Zotero.Item();
  candidate.libraryID = libraryID;
  candidate.fromJSON(typeof translated.toJSON === "function" ? translated.toJSON() : translated);
  await _withWriteLock(function () {
    return _attachMetadataCandidate(attachment, candidate, args);
  });
  return { attachment_key: attachment.key, parent_item_key: candidate.key, resolution: "markdown_identifier" };
}

async function _executeMetadataResolve(args) {
  var auditFile = _prepareAuditFile();
  var result;
  try {
    result = await _resolveMetadata(args);
  }
  catch (error) {
    try {
      await _withWriteLock(function () {
        _appendAudit(auditFile, "metadata_resolve", [args.attachment_key], "failure",
          error.bridgeCode || "INTERNAL_ERROR");
      });
    }
    catch (auditError) {
      throw _operationError("AUDIT_LOG_FAILED", "Metadata resolution failed and audit logging also failed", 500);
    }
    throw error;
  }
  try {
    await _withWriteLock(function () {
      _appendAudit(auditFile, "metadata_resolve",
        [result.attachment_key, result.parent_item_key], "success", null);
    });
  }
  catch (auditError) {
    throw _operationError("AUDIT_LOG_FAILED_AFTER_WRITE",
      "Metadata was resolved but the audit record could not be appended", 500, false,
      { attachment_key: result.attachment_key, parent_item_key: result.parent_item_key });
  }
  return result;
}

async function _addFileContext(args) {
  var libraryID = Zotero.Libraries.userLibraryID;
  if (args.library_id !== libraryID) {
    throw _operationError("LIBRARY_UNSUPPORTED", "Only My Library is supported by this operation", 409,
      false, { library_id: libraryID });
  }
  var collection = null;
  if (args.collection_key !== null) {
    collection = Zotero.Collections.getByLibraryAndKey(libraryID, args.collection_key);
    if (!collection || collection.deleted || collection.libraryID !== libraryID) {
      throw _operationError("COLLECTION_NOT_FOUND", "Collection is missing from My Library", 404,
        false, { collection_key: args.collection_key });
    }
  }
  var parent = null;
  if (args.parent_item_key !== null) {
    parent = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.parent_item_key);
    if (!parent || parent.deleted || !parent.isRegularItem() || parent.libraryID !== libraryID
        || !parent.isEditable()) {
      throw _operationError("PARENT_ITEM_NOT_FOUND", "Parent Literature Item is missing or not writable in My Library", 404,
        false, { parent_item_key: args.parent_item_key });
    }
  }
  return { libraryID: libraryID, collection: collection, parent: parent };
}

function _isAddFileContentType(contentType) {
  contentType = String(contentType || "").toLowerCase();
  return contentType === "application/pdf" || contentType === "application/epub+zip";
}

async function _sniffDocumentContentType(file) {
  var sample = await Zotero.File.getSample(file);
  return String(Zotero.MIME.sniffForMIMEType(sample) || "").toLowerCase();
}

async function _validateAddFilePath(args) {
  var file;
  try {
    file = Zotero.File.pathToFile(args.source_path);
  }
  catch (error) {
    throw _operationError("DOCUMENT_FILE_MISSING", "Document source path is invalid", 409);
  }
  if (!file.exists() || !file.isFile() || file.isSymlink() || file.path !== args.source_path) {
    throw _operationError("STALE_SOURCE_PATH", "Document source is missing, unsafe, or changed after review", 409);
  }
  if (_sha256File(file.path) !== args.expected_sha256) {
    throw _operationError("STALE_SOURCE_HASH", "Document source changed after review", 409);
  }
  var declaredContentType;
  var contentType;
  try {
    declaredContentType = String(await Zotero.MIME.getMIMETypeFromFile(file) || "").toLowerCase();
    contentType = await _sniffDocumentContentType(file);
  }
  catch (error) {
    throw _operationError("INVALID_DOCUMENT_SOURCE", "Zotero could not detect a PDF or EPUB source", 409);
  }
  if (!_isAddFileContentType(contentType) || declaredContentType !== contentType) {
    throw _operationError("INVALID_DOCUMENT_SOURCE", "Document magic bytes do not match a native PDF or EPUB", 409,
      false, { content_type: contentType || null });
  }
  return { file: file, contentType: contentType };
}

async function _validateImportedDocument(item, args, libraryID, contentType, expectedAttachmentSha256) {
  await item.reload(["primaryData"], true);
  var file = await _attachmentFile(item);
  var attachmentSha256 = _sha256File(file.path);
  var detectedContentType = await _sniffDocumentContentType(Zotero.File.pathToFile(file.path));
  if (item.libraryID !== libraryID
      || item.attachmentLinkMode !== Zotero.Attachments.LINK_MODE_IMPORTED_FILE
      || String(item.attachmentContentType || "").toLowerCase() !== contentType
      || detectedContentType !== contentType
      || attachmentSha256 !== expectedAttachmentSha256
      || attachmentSha256 !== args.expected_sha256) {
    throw _operationError("IMPORTED_DOCUMENT_INVALID", "Imported document failed validation", 500,
      false, { attachment_key: item.key });
  }
  return file;
}

async function _eraseAddedItem(item) {
  if (!item) return;
  await item.reload(["primaryData"], true);
  if (!item.deleted) await item.eraseTx();
}

async function _cleanupAddedItems(imported, candidate) {
  var firstError = null;
  try {
    await _eraseAddedItem(imported);
  }
  catch (error) {
    firstError = error;
  }
  try {
    if (candidate) await _discardMetadataCandidate(candidate);
  }
  catch (error) {
    firstError = firstError || error;
  }
  if (firstError) throw firstError;
}

function _sourceDocumentFromChildren(children) {
  var documents = children.filter(function (child) {
    return child && !child.deleted
      && child.isFileAttachment && child.isFileAttachment()
      && (child.isPDFAttachment() || child.isEPUBAttachment());
  });
  var pdfs = documents.filter(function (child) { return child.isPDFAttachment(); });
  var markedPdfs = pdfs.filter(function (child) { return _hasTag(child, SOURCE_TAG); });
  if (markedPdfs.length === 1) return markedPdfs[0];
  if (markedPdfs.length > 1) return { ambiguous: true, items: documents };
  if (documents.length === 1) return documents[0];
  return documents.length > 1 ? { ambiguous: true, items: documents } : null;
}

async function _attachAddedToParent(
  imported, parent, collection, args, libraryID, contentType, expectedAttachmentSha256
) {
  var selectedSourceKey = null;
  await Zotero.DB.executeTransaction(async function () {
    await parent.reload(["primaryData", "collections", "childItems"], true);
    await imported.reload(["primaryData", "tags"], true);
    var liveCollection = collection && Zotero.Collections.getByLibraryAndKey(libraryID, collection.key);
    if (parent.deleted || parent.libraryID !== libraryID || !parent.isRegularItem()
        || !parent.isEditable() || imported.deleted || imported.libraryID !== libraryID
        || imported.parentItemID || (collection && (!liveCollection || liveCollection.deleted))) {
      throw _operationError("STALE_ITEM", "Document or parent changed before the write committed", 409);
    }
    await _validateImportedDocument(
      imported, args, libraryID, contentType, expectedAttachmentSha256
    );
    var children = await Zotero.Items.getAsync(parent.getAttachments(false));
    if (!Array.isArray(children)) children = children ? [children] : [];
    for (var i = 0; i < children.length; i++) await children[i].loadDataType("tags");
    var source = _sourceDocumentFromChildren(children);
    if (!source) {
      selectedSourceKey = imported.key;
      if (imported.isPDFAttachment()) imported.addTag(SOURCE_TAG, 0);
    }
    else if (!source.ambiguous) {
      selectedSourceKey = source.key;
    }
    imported.parentID = parent.id;
    await imported.save({ skipSelect: true });
    if (collection && parent.getCollections().indexOf(collection.id) === -1) {
      parent.addToCollection(collection.id);
      await parent.save({ skipSelect: true });
    }
  });
  return { parent_changed: true, source_document_key: selectedSourceKey };
}

async function _reuseAddedAttachment(existing, requestedParent, collection, args) {
  await existing.reload(["primaryData", "collections"], true);
  if (existing.deleted || existing.libraryID !== args.library_id || !existing.isAttachment()
      || !existing.isEditable()
      || existing.attachmentLinkMode !== Zotero.Attachments.LINK_MODE_IMPORTED_FILE
      || (!existing.isPDFAttachment() && !existing.isEPUBAttachment())) {
    throw _operationError("ATTACHMENT_IDENTITY_CONFLICT", "Stored attachment changed before exact reuse", 409,
      false, { attachment_key: existing.key });
  }
  var existingFile = await _attachmentFile(existing);
  if (_sha256File(existingFile.path) !== args.expected_sha256) {
    throw _operationError("ATTACHMENT_IDENTITY_CONFLICT", "Stored attachment failed SHA-256 identity revalidation", 409,
      false, { attachment_key: existing.key });
  }
  var existingParent = null;
  if (existing.parentItemID) {
    existingParent = await Zotero.Items.getAsync(existing.parentItemID);
    if (!existingParent) {
      throw _operationError("ATTACHMENT_IDENTITY_CONFLICT", "Stored attachment parent is missing", 409,
        false, { attachment_key: existing.key });
    }
    await existingParent.reload(["primaryData"], true);
    if (existingParent.deleted || existingParent.libraryID !== args.library_id
        || !existingParent.isRegularItem() || !existingParent.isEditable()) {
      throw _operationError("ATTACHMENT_IDENTITY_CONFLICT", "Stored attachment parent changed before exact reuse", 409,
        false, { attachment_key: existing.key, parent_item_key: existingParent.key });
    }
  }
  if (requestedParent) {
    await requestedParent.reload(["primaryData"], true);
    if (requestedParent.deleted || requestedParent.libraryID !== args.library_id
        || !requestedParent.isRegularItem() || !requestedParent.isEditable()) {
      throw _operationError("PARENT_ITEM_NOT_FOUND", "Parent changed before the write committed", 409);
    }
  }
  if (requestedParent && (!existingParent || existingParent.id !== requestedParent.id)) {
    throw _operationError("ATTACHMENT_PARENT_CONFLICT", "Identical attachment already belongs to another Literature Item", 409,
      false, { attachment_key: existing.key, parent_item_key: existingParent ? existingParent.key : null });
  }
  var target = existingParent || existing;
  var parentChanged = await _addCollectionMembership(target, collection);
  return {
    outcome: "reused",
    library_id: args.library_id,
    attachment_key: existing.key,
    parent_item_key: existingParent ? existingParent.key : null,
    collection_key: args.collection_key,
    resolution: "attachment_hash",
    parent_changed: parentChanged
  };
}

async function _reuseStrongSource(source, matched, collection, args, identifier, incomingSha256) {
  await matched.reload(["primaryData", "childItems"], true);
  if (matched.deleted || matched.libraryID !== args.library_id
      || !matched.isRegularItem() || !matched.isEditable()) {
    throw _operationError("PARENT_ITEM_NOT_FOUND", "Existing Literature Item changed before reuse", 409);
  }
  var liveSource = await _sourceDocument(matched);
  var sourceFile = liveSource && !liveSource.ambiguous
    ? await _attachmentFile(liveSource) : null;
  var sourceSha256 = sourceFile ? _sha256File(sourceFile.path) : null;
  if (!liveSource || liveSource.ambiguous || liveSource.key !== source.key
      || !sourceSha256 || sourceSha256 !== incomingSha256) {
    throw _operationError("SOURCE_DOCUMENT_CONFLICT", "Strong Identifier already has a different Source Document", 409,
      false, {
        identifier: identifier.key,
        existing_item_key: matched.key,
        existing_source_document_key: liveSource && !liveSource.ambiguous ? liveSource.key : null
      });
  }
  return {
    outcome: "reused",
    library_id: args.library_id,
    attachment_key: liveSource.key,
    parent_item_key: matched.key,
    collection_key: args.collection_key,
    resolution: "strong_identifier",
    source_document_key: liveSource.key,
    parent_changed: await _addCollectionMembership(matched, collection),
    warnings: []
  };
}

async function _addFile(args) {
  var context = await _addFileContext(args);
  var sourceReview = await _validateAddFilePath(args);
  var sourceSha256 = args.expected_sha256;
  var nativeHash = await Zotero.Utilities.Internal.md5Async(sourceReview.file.path);
  var existingMatches = await _findAttachmentsByHash(
    context.libraryID, nativeHash, sourceReview.file.fileSize, sourceSha256
  );
  if (existingMatches.length > 1) {
    throw _operationError("IDENTICAL_ATTACHMENT_AMBIGUOUS",
      "Identical active PDF or EPUB attachments have multiple matches", 409, false,
      { attachment_keys: existingMatches.map(function (item) { return item.key; }) });
  }
  if (existingMatches.length === 1) {
    return _withWriteLock(async function () {
      await _validateAddFilePath(args);
      return _reuseAddedAttachment(existingMatches[0], context.parent, context.collection, args);
    });
  }

  var imported = null;
  var candidate = null;
  var committed = false;
  var erasedIncomingKey = null;
  try {
    await _withWriteLock(async function () {
      var liveSourceReview = await _validateAddFilePath(args);
      if (liveSourceReview.contentType !== sourceReview.contentType) {
        throw _operationError("STALE_SOURCE_PATH", "Document source type changed after review", 409);
      }
      var importOptions = {
        file: liveSourceReview.file.path,
        libraryID: context.libraryID,
        saveOptions: { skipSelect: true }
      };
      if (!context.parent && context.collection) {
        var liveCollection = Zotero.Collections.getByLibraryAndKey(context.libraryID, context.collection.key);
        if (!liveCollection || liveCollection.deleted || liveCollection.libraryID !== context.libraryID) {
          throw _operationError("COLLECTION_NOT_FOUND", "Collection changed before the write committed", 409);
        }
        importOptions.collections = [liveCollection.id];
      }
      imported = await Zotero.Attachments.importFromFile(importOptions);
      await _validateImportedDocument(
        imported, args, context.libraryID, sourceReview.contentType, sourceSha256
      );
    });
    var importedFile = await _attachmentFile(imported);

    if (context.parent) {
      var parentAttachment = await _withWriteLock(function () {
        return _attachAddedToParent(
          imported, context.parent, context.collection, args, context.libraryID,
          sourceReview.contentType, sourceSha256
        );
      });
      committed = true;
      return {
        outcome: "added",
        library_id: args.library_id,
        attachment_key: imported.key,
        parent_item_key: context.parent.key,
        collection_key: args.collection_key,
        resolution: "parent",
        source_document_key: parentAttachment.source_document_key,
        parent_changed: parentAttachment.parent_changed,
        warnings: []
      };
    }

    try {
      candidate = await Zotero.RecognizeDocument._recognize(imported);
    }
    catch (error) {
      Zotero.debug("[Zotero-Agentibility] native document recognition did not resolve " + imported.key);
    }

    var identifiers = candidate ? _strongIdentifiers(_itemIdentifierText(candidate)) : [];
    if (!candidate || identifiers.length === 0) {
      if (candidate) {
        await _withWriteLock(function () { return _discardMetadataCandidate(candidate); });
        candidate = null;
      }
      await _withWriteLock(function () { return Zotero.DB.executeTransaction(async function () {
        await imported.reload(["primaryData"], true);
        if (imported.deleted || imported.parentItemID) {
          throw _operationError("STALE_DOCUMENT", "Standalone document changed before commit", 409);
        }
        await _validateImportedDocument(
          imported, args, context.libraryID, sourceReview.contentType, sourceSha256
        );
      }); });
      committed = true;
      return {
        outcome: "added_unrecognized",
        library_id: args.library_id,
        attachment_key: imported.key,
        parent_item_key: null,
        collection_key: args.collection_key,
        resolution: null,
        parent_changed: false,
        warnings: []
      };
    }

    var matches = await _findStrongIdentifierMatches(context.libraryID, candidate, candidate.id);
    if (matches.length > 1) {
      await _withWriteLock(function () { return _discardMetadataCandidate(candidate); });
      candidate = null;
      throw _operationError("STRONG_IDENTIFIER_CONFLICT", "Strong Identifier matches multiple existing Literature Items", 409,
        false, {
          identifier: matches[0].identifier.key,
          incoming_attachment_key: imported.key,
          existing_item_keys: matches.map(function (match) { return match.item.key; })
        });
    }
    if (matches.length === 1) {
      var matched = matches[0].item;
      var source = await _sourceDocument(matched);
      var sourceHash = source && !source.ambiguous
        ? await _attachmentSha256(source) : null;
      if (source && !source.ambiguous && sourceHash
          && sourceHash === sourceSha256) {
        var erasedKey = imported.key;
        var sourceReuse = await _withWriteLock(async function () {
          await _discardMetadataCandidate(candidate);
          candidate = null;
          await _eraseAddedItem(imported);
          imported = null;
          erasedIncomingKey = erasedKey;
          return _reuseStrongSource(
            source, matched, context.collection, args, matches[0].identifier, sourceSha256
          );
        });
        committed = true;
        return sourceReuse;
      }
      if (source && (source.ambiguous || !sourceHash
          || sourceHash !== sourceSha256)) {
        await _withWriteLock(function () { return _discardMetadataCandidate(candidate); });
        candidate = null;
        throw _operationError("SOURCE_DOCUMENT_CONFLICT", "Strong Identifier already has a different Source Document", 409,
          false, {
            identifier: matches[0].identifier.key,
            existing_item_key: matched.key,
            existing_source_document_key: source.ambiguous
              ? null : source.key,
            incoming_attachment_key: imported.key
          });
      }
      await _withWriteLock(function () { return _discardMetadataCandidate(candidate); });
      candidate = null;
      var reusedAttachment = await _withWriteLock(function () {
        return _attachAddedToParent(
          imported, matched, context.collection, args, context.libraryID,
          sourceReview.contentType, sourceSha256
        );
      });
      committed = true;
      return {
        outcome: "reused",
        library_id: args.library_id,
        attachment_key: imported.key,
        parent_item_key: matched.key,
        collection_key: args.collection_key,
        resolution: "strong_identifier",
        source_document_key: reusedAttachment.source_document_key,
        parent_changed: reusedAttachment.parent_changed,
        warnings: []
      };
    }

    if (!context.collection) {
      await _withWriteLock(async function () {
        await candidate.loadDataType("collections");
        candidate.setCollections([]);
      });
    }
    var attachmentArgs = {
      expected_path: importedFile.path,
      expected_sha256: args.expected_sha256
    };
    await _withWriteLock(function () {
      return _attachMetadataCandidate(imported, candidate, attachmentArgs);
    });
    var warnings = await _duplicateWarnings(context.libraryID, candidate);
    committed = true;
    return {
      outcome: "added",
      library_id: args.library_id,
      attachment_key: imported.key,
      parent_item_key: candidate.key,
      collection_key: args.collection_key,
      resolution: "native",
      parent_changed: true,
      warnings: warnings
    };
  }
  catch (error) {
    if (!committed && (imported || candidate || erasedIncomingKey)) {
      try {
        if (imported || candidate) {
          await _withWriteLock(function () { return _cleanupAddedItems(imported, candidate); });
        }
      }
      catch (rollbackError) {
        throw _operationError("ROLLBACK_FAILED", "Could not roll back the failed document add", 500,
          false, {
            attachment_key: imported ? imported.key : erasedIncomingKey,
            parent_item_key: candidate ? candidate.key : null,
            rollback_result: "failed"
          });
      }
      if (error && typeof error === "object") {
        error.safeDetails = Object.assign({}, error.safeDetails || {}, {
          rollback_attachment_key: imported ? imported.key : erasedIncomingKey,
          rollback_result: "erased"
        });
      }
    }
    throw error;
  }
}

async function _executeAddFile(args) {
  var auditFile = _prepareAuditFile();
  var addFlowLocked = false;
  try {
    await _acquireAddLock();
    addFlowLocked = true;
    var result;
    try {
      result = await _addFile(args);
    }
    catch (error) {
      try {
        var failureDetails = error.safeDetails || {};
        await _withWriteLock(function () {
          _appendAudit(auditFile, "add_file", [
            args.parent_item_key, args.collection_key,
            failureDetails.attachment_key, failureDetails.incoming_attachment_key,
            failureDetails.existing_item_key, failureDetails.existing_source_document_key
          ], "failure", error.bridgeCode || "INTERNAL_ERROR");
        });
      }
      catch (auditError) {
        throw _operationError("AUDIT_LOG_FAILED", "Document add failed and the audit record could not be appended", 500);
      }
      throw error;
    }
    try {
      await _withWriteLock(function () {
        _appendAudit(auditFile, "add_file", [
          result.attachment_key, result.parent_item_key, args.collection_key
        ], "success", null);
      });
    }
    catch (auditError) {
      throw _operationError("AUDIT_LOG_FAILED_AFTER_WRITE", "Document was added but the audit record could not be appended", 500,
        false, {
          outcome: result.outcome,
          attachment_key: result.attachment_key,
          parent_item_key: result.parent_item_key,
          collection_key: result.collection_key
        });
    }
    return result;
  }
  finally {
    if (addFlowLocked) _releaseAddLock();
  }
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

function _appendAudit(file, operation, affectedKeys, result, errorCode) {
  var output = Cc["@mozilla.org/network/file-output-stream;1"]
    .createInstance(Ci.nsIFileOutputStream);
  output.init(file, 0x02 | 0x08 | 0x10, 0o600, 0);
  var data = JSON.stringify({
    time: new Date().toISOString(),
    operation: operation,
    affectedKeys: affectedKeys.filter(function (key, index, keys) {
      return typeof key === "string" && key && keys.indexOf(key) === index;
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

async function _writeFulltext(args) {
  var libraryID = Zotero.Libraries.userLibraryID;
  var parent = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.item_key);
  if (!parent || parent.deleted || !parent.isRegularItem() || parent.libraryID !== libraryID
      || !parent.isEditable()) {
    throw _operationError("ITEM_NOT_WRITABLE", "Literature Item is missing or not writable in My Library", 404,
      false, { item_key: args.item_key });
  }

  var source = null;
  var sourceFile;
  if (args.markdown_attachment_key) {
    source = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.markdown_attachment_key);
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
    sourceFile = await _attachmentFile(source);
    if (sourceFile.path !== args.expected_path) {
      throw _operationError("STALE_ATTACHMENT_PATH", "The selected Markdown attachment path changed after review", 409,
        false, { attachment_key: source.key });
    }
    if (_sha256File(sourceFile.path) !== args.expected_sha256) {
      throw _operationError("STALE_ATTACHMENT_HASH", "The selected Markdown attachment changed after review", 409,
        false, { attachment_key: source.key });
    }
  }
  else {
    var localFile;
    try {
      localFile = Zotero.File.pathToFile(args.source_path);
    }
    catch (error) {
      throw _operationError("FULLTEXT_FILE_MISSING", "Markdown import source path is invalid", 409);
    }
    if (!localFile.exists() || !localFile.isFile() || localFile.isSymlink()) {
      throw _operationError("FULLTEXT_FILE_MISSING", "Markdown import source is missing or unsafe", 409);
    }
    sourceFile = { path: localFile.path, filename: localFile.leafName };
    if (sourceFile.path !== args.source_path) {
      throw _operationError("STALE_SOURCE_PATH", "Markdown import source path changed after review", 409);
    }
    if (!sourceFile.filename.toLowerCase().endsWith(".md")) {
      throw _operationError("INVALID_FULLTEXT_SOURCE", "Import source must be a Markdown file", 409);
    }
    _rejectDistillationFilename(sourceFile.filename);
    if (_sha256File(sourceFile.path) !== args.expected_sha256) {
      throw _operationError("STALE_SOURCE_HASH", "Markdown import source changed after review", 409);
    }
  }

  await parent.loadDataType("childItems");
  var children = await Zotero.Items.getAsync(parent.getAttachments(false));
  for (var i = 0; i < children.length; i++) await children[i].loadDataType("tags");
  var marked = children.filter(function (item) { return _hasTag(item, FULLTEXT_TAG); });
  var requiredReplacements = marked
    .filter(function (item) { return !source || item.key !== source.key; })
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

  var documents = children.filter(function (item) {
    var contentType = String(item.attachmentContentType || "").toLowerCase();
    var filename = _filename(item).toLowerCase();
    return contentType === "application/pdf" || contentType === "application/epub+zip"
      || filename.endsWith(".pdf") || filename.endsWith(".epub");
  });
  var pdfs = documents.filter(function (item) {
    return item.isPDFAttachment();
  });
  var taggedPdfs = pdfs.filter(function (item) { return _hasTag(item, SOURCE_TAG); });
  var sourceDocument;
  if (taggedPdfs.length === 1) sourceDocument = taggedPdfs[0];
  else if (taggedPdfs.length > 1 || documents.length > 1) {
    throw _operationError("AMBIGUOUS_SOURCE", "Multiple PDF or EPUB documents require one marked PDF Source Document", 409,
      false, { attachment_keys: documents.map(function (item) { return item.key; }) });
  }
  else if (documents.length === 1) sourceDocument = documents[0];
  else throw _operationError("SOURCE_NOT_FOUND", "No Source Document PDF or EPUB was found", 409);

  var imported = null;
  var committed = false;
  var touched = (source ? [source] : []).concat(replacements).concat([sourceDocument]);
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
      if (source) {
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
      }
      else if (_sha256File(sourceFile.path) !== args.expected_sha256) {
        throw _operationError("STALE_SOURCE_HASH", "Markdown import source changed before commit", 409);
      }
      var finalDocuments = finalChildren.filter(function (item) {
        var contentType = String(item.attachmentContentType || "").toLowerCase();
        var filename = _filename(item).toLowerCase();
        return contentType === "application/pdf" || contentType === "application/epub+zip"
          || filename.endsWith(".pdf") || filename.endsWith(".epub");
      });
      var finalPdfs = finalDocuments.filter(function (item) { return item.isPDFAttachment(); });
      var finalTaggedPdfs = finalPdfs.filter(function (item) { return _hasTag(item, SOURCE_TAG); });
      var finalSourceDocument = finalTaggedPdfs.length === 1 ? finalTaggedPdfs[0]
        : finalTaggedPdfs.length === 0 && finalDocuments.length === 1 ? finalDocuments[0] : null;
      if (!finalSourceDocument || finalSourceDocument.key !== sourceDocument.key) {
        throw _operationError("AMBIGUOUS_SOURCE", "Source Document selection changed before commit", 409,
          false, { attachment_keys: finalDocuments.map(function (item) { return item.key; }) });
      }
      sourceDocument = finalSourceDocument;
      var finalMarked = finalChildren
        .filter(function (item) {
          return item.key !== imported.key && (!source || item.key !== source.key) && _hasTag(item, FULLTEXT_TAG);
        })
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
      if (sourceDocument.isPDFAttachment() && !_hasTag(sourceDocument, SOURCE_TAG)) {
        sourceDocument.addTag(SOURCE_TAG, 0);
        await sourceDocument.save({ skipSelect: true });
      }
      var trashIDs = replacements.map(function (item) { return item.id; });
      if (source) trashIDs.unshift(source.id);
      if (trashIDs.length) await Zotero.Items.trash(trashIDs);
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
    adopted_attachment_key: source ? source.key : null,
    trashed_attachment_keys: (source ? [source.key] : []).concat(replacements.map(function (item) { return item.key; })),
    source_document_key: sourceDocument.key,
    sha256: args.expected_sha256
  };
}

async function _executeFulltextWrite(operation, args) {
  var auditFile = _prepareAuditFile();
  var locked = false;
  var affected = [args.item_key].concat(
    args.markdown_attachment_key ? [args.markdown_attachment_key] : [],
    args.replace_attachment_keys
  );
  try {
    await _acquireWriteLock();
    locked = true;
    var result;
    try {
      result = await _writeFulltext(args);
    }
    catch (error) {
      try {
        var failedKeys = error.rollbackAttachmentKey ? affected.concat([error.rollbackAttachmentKey]) : affected;
        var failureResult = error.rollbackResult === "failed" ? "failure_rollback_failed"
          : error.rollbackResult === "trashed" ? "failure_rolled_back" : "failure";
        _appendAudit(auditFile, operation, failedKeys, failureResult,
          error.bridgeCode || "INTERNAL_ERROR");
      }
      catch (auditError) {
        throw _operationError("AUDIT_LOG_FAILED", "Write failed and the audit record could not be appended", 500);
      }
      throw error;
    }
    try {
      _appendAudit(auditFile, operation,
        affected.concat([result.markdown_attachment_key, result.source_document_key]), "success", null);
    }
    catch (auditError) {
      throw _operationError("AUDIT_LOG_FAILED_AFTER_WRITE",
        "Full Text was written but the audit record could not be appended", 500, false,
        { item_key: result.item_key, markdown_attachment_key: result.markdown_attachment_key,
          trashed_attachment_keys: result.trashed_attachment_keys });
    }
    return result;
  }
  finally {
    if (locked) _releaseWriteLock();
  }
}

function _validateIndexCatalogArguments(args) {
  if (!_sameKeys(args, ["item_keys"])) {
    throw _operationError("BAD_ARGUMENTS", "index_catalog arguments do not match the schema", 400);
  }
  if (args.item_keys === null) return args;
  if (!Array.isArray(args.item_keys) || args.item_keys.length > 100) {
    throw _operationError("BAD_ARGUMENTS", "item_keys must be null or an array of at most 100 keys", 400);
  }
  var seen = Object.create(null);
  for (var i = 0; i < args.item_keys.length; i++) {
    if (typeof args.item_keys[i] !== "string"
        || !/^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/.test(args.item_keys[i])
        || seen[args.item_keys[i]]) {
      throw _operationError("BAD_ARGUMENTS", "item_keys must contain distinct valid Zotero keys", 400);
    }
    seen[args.item_keys[i]] = true;
  }
  return args;
}

function _catalogCreator(creator) {
  if (creator.name) return String(creator.name);
  return [creator.firstName, creator.lastName].filter(Boolean).join(" ");
}

async function _catalogAttachment(item) {
  await item.loadDataType("tags");
  var path = null;
  try { path = await item.getFilePathAsync(); }
  catch (error) {}
  return {
    key: item.key,
    itemID: item.id,
    typeName: "attachment",
    title: item.getField("title") || "",
    linkMode: item.attachmentLinkMode,
    contentType: item.attachmentContentType || "",
    attachmentPath: path || "",
    dateModified: item.dateModified,
    tags: item.getTags().map(function (tag) { return tag.tag; })
  };
}

async function _catalogItem(item) {
  await item.loadDataType("childItems");
  await item.loadDataType("tags");
  var attachments = await Zotero.Items.getAsync(item.getAttachments(false));
  attachments = Array.isArray(attachments) ? attachments : attachments ? [attachments] : [];
  var result = [];
  for (var i = 0; i < attachments.length; i++) {
    if (attachments[i] && !attachments[i].deleted && attachments[i].isAttachment()) {
      result.push(await _catalogAttachment(attachments[i]));
    }
  }
  var date = item.getField("date") || "";
  var year = (String(date).match(/(?:18|19|20)\d{2}/) || [null])[0];
  return {
    key: item.key,
    itemID: item.id,
    dateModified: item.dateModified,
    typeName: Zotero.ItemTypes.getName(item.itemTypeID),
    title: item.getField("title") || "",
    creators: item.getCreators().map(_catalogCreator).filter(Boolean),
    year: year || "",
    doi: item.getField("DOI") || "",
    dateAdded: item.dateAdded || "",
    fields: {
      date: date,
      DOI: item.getField("DOI") || "",
      abstractNote: item.getField("abstractNote") || "",
      publicationTitle: item.getField("publicationTitle") || "",
      url: item.getField("url") || "",
      extra: item.getField("extra") || ""
    },
    tags: item.getTags().map(function (tag) { return tag.tag; }),
    attachments: result
  };
}

async function _indexCatalog(args) {
  var libraryID = Zotero.Libraries.userLibraryID;
  var items;
  if (args.item_keys === null) {
    items = await Zotero.Items.getAll(libraryID, false, false);
  }
  else {
    items = [];
    for (var i = 0; i < args.item_keys.length; i++) {
      var item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, args.item_keys[i]);
      if (item) items.push(item);
    }
  }
  var result = [];
  for (var j = 0; j < items.length; j++) {
    var candidate = items[j];
    if (candidate && !candidate.deleted && candidate.libraryID === libraryID
        && candidate.isRegularItem && candidate.isRegularItem()) {
      result.push(await _catalogItem(candidate));
    }
  }
  return { items: result };
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
    args = request.operation === "index_catalog"
      ? _validateIndexCatalogArguments(request.arguments)
      : request.operation === "metadata_resolve"
        ? _validateMetadataArguments(request.arguments)
        : request.operation === "add_file"
          ? _validateAddFileArguments(request.arguments)
          : _validateFulltextArguments(request.arguments, request.operation);
  }
  catch (error) {
    _sendOperationError(handler, error);
    return;
  }
  var operation = request.operation === "index_catalog"
    ? _indexCatalog(args)
    : request.operation === "metadata_resolve"
      ? _executeMetadataResolve(args)
      : request.operation === "add_file"
        ? _executeAddFile(args)
        : _executeFulltextWrite(request.operation, args);
  operation.then(function (result) {
    _send(handler, 200, { ok: true, protocol: PROTOCOL, operation: request.operation, result: result });
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
  directory.append("zotero-agentibility");
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

function _workerExecutable() {
  var configured = Services.prefs.getStringPref("extensions.zotero-agentibility.zaCliPath", "");
  if (configured) return configured;
  var home = Services.dirsvc.get("Home", Ci.nsIFile);
  home.append(".local");
  home.append("bin");
  home.append("za-cli");
  return home.path;
}

async function _startWorkerRuntime(rootURI) {
  var uri = String(rootURI && (rootURI.spec || rootURI) || "");
  if (!uri) throw new Error("Extension resource URI is unavailable");
  await Zotero.Server.init();
  if (!extensionRunning) return;
  Services.scriptloader.loadSubScript(uri + "runtime.js", this);
  var subprocess = ChromeUtils.importESModule("resource://gre/modules/Subprocess.sys.mjs").Subprocess;
  var configChannel = ChromeUtils.importESModule("resource://gre/modules/NetUtil.sys.mjs").NetUtil.newChannel({
    uri: uri + "index-runtime.json", loadUsingSystemPrincipal: true
  });
  agentibilityRuntime = AgentibilityRuntime.create({
    Zotero: Zotero,
    resourceURI: uri,
    settings: JSON.parse(await Zotero.File.getContentsAsync(configChannel)),
    Subprocess: subprocess,
    executable: _workerExecutable(),
    dataDirectory: Zotero.DataDirectory.dir,
    httpPort: Zotero.Server.port,
    configDirectory: _configDirectory().path
  });
  await agentibilityRuntime.start();
}

async function startup({ version, rootURI }) {
  try {
    extensionRunning = true;
    VERSION = version;
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
    await _startWorkerRuntime(rootURI).catch(function (error) {
      Zotero.logError(new Error("Zotero-Agentibility worker disabled: " + error.message));
    });
    Zotero.debug("[Zotero-Agentibility] bridge endpoint registered");
  }
  catch (e) {
    delete Zotero.Server.Endpoints[ENDPOINT];
    _removeServerHooks();
    bearerToken = null;
    bridgeEndpoint = null;
    Zotero.logError(new Error("Zotero-Agentibility bridge disabled: " + e.message));
  }
}

async function shutdown() {
  extensionRunning = false;
  var runtime = agentibilityRuntime;
  agentibilityRuntime = null;
  if (runtime) {
    try { await runtime.stop(); }
    catch (error) { Zotero.logError(error); }
  }
  delete Zotero.Server.Endpoints[ENDPOINT];
  _removeServerHooks();
  VERSION = null;
  bearerToken = null;
  bridgeEndpoint = null;
  Zotero.debug("[Zotero-Agentibility] bridge endpoint removed");
}

function install() {}
function uninstall() {}
