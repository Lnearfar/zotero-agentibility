const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const Runtime = require("./runtime.js");

const PARENT = "PARENT23";
const ATTACHMENT = "ATTACH23";

function regular(key) {
  return { id: 1, key, libraryID: 1, deleted: false, itemTypeID: 1,
    isRegularItem: () => true, getAttachments: () => [], getCreators: () => [], getTags: () => [],
    getField: name => name === "title" ? "A title" : name === "date" ? "2026-01-01" : "",
    loadDataType: async () => {}, dateModified: "2026-01-01 00:00:00" };
}

function attachment(parentID) {
  return { id: 2, key: ATTACHMENT, libraryID: 1, deleted: false, parentItemID: parentID,
    isAttachment: () => true, getFilePathAsync: async () => "/tmp/paper.pdf",
    getTags: () => [{ tag: "pdf" }], getField: () => "Paper", attachmentLinkMode: 0,
    attachmentContentType: "application/pdf", dateModified: "2026-01-01 00:00:00",
    loadDataType: async () => {} };
}

async function testRuntime() {
  const writes = [];
  let observer;
  let section;
  const parent = regular(PARENT);
  const child = attachment(1);
  let exit;
  const exitPromise = new Promise(resolve => { exit = resolve; });
  const stdin = { write: data => { writes.push(JSON.parse(data)); return Promise.resolve(); }, close: async () => { exit({ exitCode: 0 }); } };
  const stdout = { chunks: [
    '{"event":"status","state":{"phase":"idle","heartbeat":"now","pending_items":0,"active_item_keys":[],"item_stats":{"PARENT23":{"passages":4}}',
    '}}\n',
    ""
  ], readString() { return Promise.resolve(this.chunks.shift()); } };
  const stderr = { chunks: [""], readString() { return Promise.resolve(this.chunks.shift()); } };
  const process = { stdin, stdout, stderr, wait: () => exitPromise, kill: () => exit({ exitCode: -1 }) };
  const Zotero = {
    debug: () => {}, logError: error => { throw error; }, Libraries: { userLibraryID: 1 },
    Items: {
      getAll: async () => [child],
      getAsync: async ids => Array.isArray(ids) ? [child] : ids === 1 ? parent : null
    },
    Notifier: { registerObserver: value => { observer = value; return "observer"; }, unregisterObserver: () => {} },
    ItemPaneManager: {
      registerSection: options => { section = options; return "pane"; }, unregisterSection: () => {}
    }
  };
  const runtime = Runtime.create({ Zotero, settings: JSON.parse(fs.readFileSync('../index-runtime.json', 'utf8')), Subprocess: { call: async options => {
    assert.deepStrictEqual(options.arguments, ["--json", "index", "worker", "--managed",
      "--data-dir", "/home/test/Zotero", "--port", "23119",
      "--config-dir", "/home/test/.config/zotero-agentibility",
      "--poll-seconds", "5", "--retry-seconds", "30", "--reconcile-seconds", "43200"]);
    assert.strictEqual(options.command, "/home/test/.local/bin/za-cli");
    return process;
  } }, executable: "/home/test/.local/bin/za-cli", dataDirectory: "/home/test/Zotero",
  httpPort: 23119, configDirectory: "/home/test/.config/zotero-agentibility" });
  await runtime.start();
  await new Promise(resolve => setTimeout(resolve, 0));
  const body = { textContent: "", style: {} };
  await section.onAsyncRender({ body, item: parent });
  assert.match(body.textContent, /Library worker: idle/);
  assert.match(body.textContent, /Searchable: Source · 4 passages/);
  child.parentItemID = null;
  await observer.notify("delete", "item", [2]);
  await new Promise(resolve => setTimeout(resolve, 80));
  assert.deepStrictEqual(writes.find(command => command.operation === "enqueue"),
    { operation: "enqueue", item_keys: [PARENT] });
  await runtime.stop();
  assert.deepStrictEqual(writes[writes.length - 1], { operation: "shutdown" });
}

async function testCatalog() {
  const item = regular(PARENT);
  item.getAttachments = () => [2];
  const child = attachment(1);
  const context = {
    Components: { classes: {}, interfaces: {} },
    ChromeUtils: { importESModule: () => ({ Services: {} }) },
    Zotero: {
      Libraries: { userLibraryID: 1 },
      ItemTypes: { getName: () => "journalArticle" },
      Items: {
        getAll: async () => [item],
        getAsync: async value => Array.isArray(value) ? [child] : null,
        getByLibraryAndKeyAsync: async (_library, key) => key === PARENT ? item : null
      }
    }
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("bootstrap.js", "utf8") + "\nthis.catalog = _indexCatalog; this.validateCatalog = _validateIndexCatalogArguments;", context);
  const result = await context.catalog({ item_keys: [PARENT] });
  assert.deepStrictEqual(JSON.parse(JSON.stringify(result)), { items: [{
    key: PARENT, itemID: 1, dateModified: "2026-01-01 00:00:00", typeName: "journalArticle",
    title: "A title", creators: [], year: "2026", doi: "", dateAdded: "",
    fields: { date: "2026-01-01", DOI: "", abstractNote: "", publicationTitle: "", url: "", extra: "" }, tags: [], attachments: [{
      key: ATTACHMENT, itemID: 2, typeName: "attachment", title: "Paper", linkMode: 0,
      contentType: "application/pdf", attachmentPath: "/tmp/paper.pdf", dateModified: "2026-01-01 00:00:00", tags: ["pdf"]
    }]
  }] });
  assert.throws(() => context.validateCatalog({ item_keys: [PARENT, PARENT] }), /distinct valid Zotero keys/);
}

Promise.resolve().then(testRuntime).then(testCatalog).then(() => console.log("Runtime behavior passed"));
