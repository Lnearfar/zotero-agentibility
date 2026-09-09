/* Zotero-Agentibility worker lifecycle, notifications, and Item pane console. */
var AgentibilityRuntime = (function () {
  "use strict";

  var KEY = /^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/;
  var CHUNK_SIZE = 100;

  function create(deps) {
    var settings = deps.settings;
    var MAX_LINE = settings.max_status_line_bytes;
    var MAX_BUFFER = settings.max_status_buffer_bytes;
    var MAX_RESTARTS = settings.restart_limit;
    var Zotero = deps.Zotero;
    var Subprocess = deps.Subprocess;
    var setTimer = deps.setTimeout || setTimeout;
    var clearTimer = deps.clearTimeout || clearTimeout;
    var worker = null;
    var launching = null;
    var writes = Promise.resolve();
    var stopping = false;
    var restartCount = 0;
    var restartTimer = null;
    var notifierID = null;
    var paneID = null;
    var refreshes = [];
    var parentKeys = Object.create(null);
    var pending = Object.create(null);
    var flushTimer = null;
    var state = { phase: "starting", pending_items: 0, pending_keys: [], active_item_keys: [], last_error: null };

    function log(message) {
      Zotero.debug("[Zotero-Agentibility] " + message);
    }

    function fault(message) {
      state = Object.assign({}, state, { phase: "fault", last_error: String(message) });
      refresh();
      log(message);
    }

    function refresh() {
      refreshes.slice().forEach(function (callback) {
        try { callback(); }
        catch (error) { Zotero.logError(error); }
      });
    }

    function enqueue(keys) {
      keys.forEach(function (key) {
        if (KEY.test(key)) pending[key] = true;
      });
      if (!flushTimer && Object.keys(pending).length) {
        flushTimer = setTimer(flush, settings.debounce_ms);
      }
    }

    async function send(command) {
      if (!worker || !worker.stdin) return false;
      var current = worker;
      try {
        writes = writes.catch(function () {}).then(function () {
          return current.stdin.write(JSON.stringify(command) + "\n");
        });
        await writes;
        return true;
      }
      catch (error) {
        if (!stopping) {
          fault("worker stdin: " + error.message);
          current.kill();
        }
        return false;
      }
    }

    async function flush() {
      flushTimer = null;
      var keys = Object.keys(pending);
      pending = Object.create(null);
      for (var offset = 0; offset < keys.length; offset += CHUNK_SIZE) {
        if (!await send({ operation: "enqueue", item_keys: keys.slice(offset, offset + CHUNK_SIZE) })) {
          keys.slice(offset).forEach(function (key) { pending[key] = true; });
          break;
        }
      }
    }

    function onStatus(message) {
      if (!message || message.event !== "status" || !message.state || typeof message.state !== "object") {
        fault("worker emitted an unsupported status message");
        return;
      }
      if (message.version !== undefined && message.version !== 1) {
        fault("worker protocol version " + message.version + " is unsupported");
        return;
      }
      state = Object.assign({}, state, message.state);
      refresh();
    }

    async function drain(pipe, output) {
      var buffer = "";
      try {
        for (;;) {
          var chunk = await pipe.readString();
          if (!chunk) break;
          buffer += chunk;
          if (buffer.length > MAX_BUFFER) {
            fault(output + " exceeded " + MAX_BUFFER + " bytes");
            buffer = "";
            continue;
          }
          var lines = buffer.split("\n");
          buffer = lines.pop();
          lines.forEach(function (line) {
            if (!line) return;
            if (line.length > MAX_LINE) {
              fault(output + " line exceeded " + MAX_LINE + " bytes");
              return;
            }
            if (output === "stdout") {
              try { onStatus(JSON.parse(line)); }
              catch (error) { fault("worker emitted invalid JSON status"); }
            }
            else {
              fault("worker stderr: " + line.slice(0, 512));
            }
          });
        }
        if (buffer) {
          if (output === "stdout") {
            try { onStatus(JSON.parse(buffer)); }
            catch (error) { fault("worker stdout ended with incomplete JSON"); }
          }
          else fault("worker stderr: " + buffer.slice(0, 512));
        }
      }
      catch (error) {
        if (!stopping) fault("worker " + output + " read: " + error.message);
      }
    }

    function scheduleRestart() {
      if (stopping || restartCount >= MAX_RESTARTS) {
        if (!stopping) fault("worker stopped after " + MAX_RESTARTS + " crashes");
        return;
      }
      var delay = settings.restart_delay_ms * Math.pow(2, restartCount++);
      state = Object.assign({}, state, { phase: "restarting", last_error: "worker exited; retry " + restartCount + "/" + MAX_RESTARTS });
      refresh();
      restartTimer = setTimer(function () { restartTimer = null; startWorker(); }, delay);
    }

    async function startWorker() {
      if (stopping || worker) return;
      try {
        state = Object.assign({}, state, { phase: "starting", last_error: null });
        refresh();
        launching = Subprocess.call({
          command: deps.executable,
          arguments: ["--json", "index", "worker", "--managed",
            "--data-dir", deps.dataDirectory, "--port", String(deps.httpPort),
            "--config-dir", deps.configDirectory,
            "--poll-seconds", String(settings.heartbeat_seconds),
            "--retry-seconds", String(settings.retry_seconds),
            "--reconcile-seconds", String(settings.reconcile_seconds)],
          stderr: "pipe"
        });
        worker = await launching;
        launching = null;
        if (stopping) return;
        var current = worker;
        drain(current.stdout, "stdout");
        drain(current.stderr, "stderr");
        current.wait().then(function (result) {
          if (worker === current) worker = null;
          if (!stopping) {
            fault("worker exited with code " + result.exitCode);
            scheduleRestart();
          }
        }, function (error) {
          if (worker === current) worker = null;
          if (!stopping) {
            fault("worker wait: " + error.message);
            scheduleRestart();
          }
        });
        flush();
      }
      catch (error) {
        launching = null;
        worker = null;
        fault("worker launch: " + error.message);
        scheduleRestart();
      }
    }

    async function parentForAttachment(item) {
      if (!item || !item.parentItemID) return null;
      var parent = await Zotero.Items.getAsync(item.parentItemID);
      return parent && !parent.deleted && parent.libraryID === Zotero.Libraries.userLibraryID
        && parent.isRegularItem && parent.isRegularItem() ? parent.key : null;
    }

    async function cacheParents() {
      var all = await Zotero.Items.getAll(Zotero.Libraries.userLibraryID, false, false);
      for (var i = 0; i < all.length; i++) {
        var item = all[i];
        if (item && item.isRegularItem && item.isRegularItem()) parentKeys[item.id] = item.key;
        if (item && item.isAttachment && item.isAttachment()) {
          var parent = await parentForAttachment(item);
          if (parent) parentKeys[item.id] = parent;
        }
      }
    }

    async function notify(event, type, ids) {
      if (type !== "item") return;
      var changed = await Zotero.Items.getAsync(ids);
      changed = Array.isArray(changed) ? changed : changed ? [changed] : [];
      var keys = ids.map(function (id) { return parentKeys[id]; }).filter(Boolean);
      for (var i = 0; i < changed.length; i++) {
        var item = changed[i];
        if (!item || item.libraryID !== Zotero.Libraries.userLibraryID) continue;
        if (item.isRegularItem && item.isRegularItem()) {
          parentKeys[item.id] = item.key;
          keys.push(item.key);
        }
        if (!item.isAttachment || !item.isAttachment()) continue;
        if (parentKeys[item.id]) keys.push(parentKeys[item.id]);
        var parent = await parentForAttachment(item);
        if (parent) parentKeys[item.id] = parent;
        else delete parentKeys[item.id];
        if (parent) keys.push(parent);
      }
      if (event === "delete") ids.forEach(function (id) { delete parentKeys[id]; });
      enqueue(keys);
    }

    function render(props) {
      var item = props.item;
      var itemKey = item && item.isRegularItem && item.isRegularItem() ? item.key
        : item ? parentKeys[item.id] : null;
      var stats = state.item_stats && itemKey ? state.item_stats[itemKey] : null;
      var error = state.errors && itemKey ? state.errors[itemKey] : null;
      var indexed = stats && stats.passages > 0;
      var source = stats && stats.source_kind === "markdown" ? "MD"
        : stats && stats.source_kind === "pdf" ? "PDF" : "Source";
      var active = (state.active_item_keys || []).includes(itemKey);
      var queued = (state.pending_keys || []).includes(itemKey);
      var selected = !itemKey ? "Select a literature item" : active ? "Indexing"
        : error ? (["SOURCE_NOT_FOUND", "SOURCE_MISSING"].includes(error.code) ? "Source missing" : "Failed")
          : queued ? "Queued" : indexed ? source + " indexed" : "Not indexed";
      var lines = [
        "This item: " + (itemKey || "—"),
        "Search status: " + selected,
        indexed ? "Searchable: " + source + " · " + stats.passages + " passages" : "Searchable: no indexed passages yet"
      ];
      if (indexed && stats.partial) lines.push("Coverage: partial");
      if (indexed && (queued || active || error)) lines.push("Previously indexed content remains searchable.");
      if (error) lines.push("Item error: " + error.code + " — " + error.message);
      if (queued) lines.push(error ? "Retry: queued" : "Refresh: queued");
      if (source === "MD" && indexed) lines.push("Markdown is indexed instead of PDF.");
      var errors = Object.keys(state.errors || {});
      lines.push("", "Library worker: " + (state.phase || "unknown"),
        "Library queue: " + (state.pending_items || 0),
        "Library errors: " + errors.length,
        "Library index: " + (state.item_count || 0) + " items / " + (state.count || 0) + " passages",
        "Heartbeat: " + (state.heartbeat ? new Date(state.heartbeat).toLocaleTimeString() : "unknown"),
        "Last pass: " + (state.last_updated ? new Date(state.last_updated).toLocaleTimeString() : "none"));
      errors.slice(0, 5).forEach(function (key) { lines.push(key + ": " + state.errors[key].code); });
      if (errors.length > 5) lines.push("… " + (errors.length - 5) + " more library errors");
      if (state.last_error) lines.push("Worker fault: " + (state.last_error.message || state.last_error));
      props.body.style.whiteSpace = "pre-wrap";
      props.body.style.lineHeight = "1.6";
      props.body.textContent = lines.join("\n");
    }

    function installConsole() {
      if (!Zotero.ItemPaneManager || paneID) return;
      paneID = Zotero.ItemPaneManager.registerSection({
        paneID: "agentibility-console",
        pluginID: "zotero-agentibility@local",
        header: { l10nID: "agentibility-console-header", icon: deps.resourceURI + "icons/console.svg", darkIcon: deps.resourceURI + "icons/console-dark.svg" },
        sidenav: { l10nID: "agentibility-console-sidenav", icon: deps.resourceURI + "icons/console.svg", darkIcon: deps.resourceURI + "icons/console-dark.svg" },
        onInit: function (props) {
          props.doc.l10n.addResourceIds(["agentibility.ftl"]);
          props.body.style.whiteSpace = "pre-wrap";
          props.body.agentibilityRefresh = props.refresh;
          refreshes.push(props.refresh);
        },
        onDestroy: function (props) {
          refreshes = refreshes.filter(function (callback) { return callback !== props.body.agentibilityRefresh; });
        },
        onItemChange: function (props) { props.setEnabled(true); },
        onRender: render
      });
    }

    return {
      async start() {
        await cacheParents();
        if (stopping) return;
        notifierID = Zotero.Notifier.registerObserver({ notify: notify }, ["item"], "zotero-agentibility");
        installConsole();
        await startWorker();
      },
      async stop() {
        stopping = true;
        if (restartTimer) clearTimer(restartTimer);
        if (flushTimer) clearTimer(flushTimer);
        if (notifierID) Zotero.Notifier.unregisterObserver(notifierID);
        notifierID = null;
        if (paneID) Zotero.ItemPaneManager.unregisterSection(paneID);
        paneID = null;
        refreshes = [];
        if (launching) {
          try { await launching; } catch (error) {}
        }
        if (!worker) return;
        var current = worker;
        var deadline;
        var graceful = async function () {
          await send({ operation: "shutdown" });
          try { await current.stdin.close(); } catch (error) {}
          await current.wait();
          return true;
        };
        var exited = await Promise.race([
          graceful(),
          new Promise(function (resolve) { deadline = setTimer(function () { resolve(false); }, settings.shutdown_timeout_ms); })
        ]);
        clearTimer(deadline);
        if (!exited) current.kill();
        await current.wait();
        worker = null;
      },
      notify: notify,
      status: function () { return state; },
      enqueue: enqueue,
      render: render
    };
  }

  return { create: create };
})();

if (typeof module !== "undefined") module.exports = AgentibilityRuntime;
