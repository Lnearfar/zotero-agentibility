import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const parameterFile = resolve(root, "zotero-plugin.dev.json");
const scaffoldCli = resolve(root, "node_modules/zotero-plugin-scaffold/bin/zotero-plugin.mjs");
const minimumNode = [22, 8, 0];

function fail(message) {
  throw new Error(message);
}

function stringParameter(value, name) {
  if (typeof value !== "string" || value.length === 0)
    fail(`${name} must be a non-empty string in ${parameterFile}`);
  return value;
}

function pathParameter(value, name) {
  return resolve(root, stringParameter(value, name));
}

function stringArrayParameter(value, name) {
  if (!Array.isArray(value) || value.some(item => typeof item !== "string" || item.length === 0))
    fail(`${name} must be an array of non-empty strings in ${parameterFile}`);
  return value;
}

function integerParameter(value, name) {
  if (!Number.isInteger(value) || value < 1)
    fail(`${name} must be a positive integer in ${parameterFile}`);
  return value;
}

function loadParameters() {
  const data = JSON.parse(readFileSync(parameterFile, "utf8"));
  const zotero = data.zotero;
  const worker = data.worker;
  const devOnce = data.devOnce;
  if (!zotero || !worker || !devOnce)
    fail(`zotero, worker, and devOnce are required in ${parameterFile}`);

  const paths = {
    home: pathParameter(zotero.homePath, "zotero.homePath"),
    profile: pathParameter(zotero.profilePath, "zotero.profilePath"),
    data: pathParameter(zotero.dataPath, "zotero.dataPath"),
  };
  const scaffoldRoot = resolve(root, ".scaffold");
  for (const [name, path] of Object.entries(paths)) {
    const outside = relative(scaffoldRoot, path);
    if (outside === ".." || outside.startsWith(`..${sep}`) || outside === "")
      fail(`zotero.${name} must be a distinct path below ${scaffoldRoot}`);
  }
  if (new Set(Object.values(paths)).size !== Object.values(paths).length)
    fail("zotero.homePath, profilePath, and dataPath must be distinct");

  const [major, minor] = process.versions.node.split(".").map(Number);
  if (major < minimumNode[0] || (major === minimumNode[0] && minor < minimumNode[1]))
    fail(`Node ${minimumNode.join(".")} or newer is required; found ${process.versions.node}`);

  return {
    zotero: {
      binary: stringParameter(zotero.binaryPath, "zotero.binaryPath"),
      application: pathParameter(zotero.applicationPath, "zotero.applicationPath"),
      startArgs: stringArrayParameter(zotero.startArgs, "zotero.startArgs"),
      ...paths,
    },
    worker: {
      executable: pathParameter(worker.executablePath, "worker.executablePath"),
    },
    devOnce: {
      readyTimeoutMs: integerParameter(devOnce.readyTimeoutMs, "devOnce.readyTimeoutMs"),
      settleMs: integerParameter(devOnce.settleMs, "devOnce.settleMs"),
    },
  };
}

function runtimeEnvironment(parameters) {
  mkdirSync(parameters.zotero.home, { recursive: true });
  mkdirSync(parameters.zotero.data, { recursive: true });
  const home = parameters.zotero.home;
  const launcher = resolve(root, ".scaffold/zotero-launcher");
  const quote = value => `'${value.replaceAll("'", "'\\''")}'`;
  writeFileSync(launcher, `#!/bin/sh\nexec ${[resolve(root, parameters.zotero.binary), "-app", parameters.zotero.application].map(quote).join(" ")} "$@"\n`, { mode: 0o700 });
  return {
    ...process.env,
    HOME: home,
    XDG_CONFIG_HOME: resolve(home, ".config"),
    XDG_CACHE_HOME: resolve(home, ".cache"),
    XDG_DATA_HOME: resolve(home, ".local/share"),
    XDG_STATE_HOME: resolve(home, ".local/state"),
    ZOTERO_PLUGIN_ZOTERO_BIN_PATH: launcher,
    ZOTERO_PLUGIN_PROFILE_PATH: parameters.zotero.profile,
    ZOTERO_PLUGIN_DATA_DIR: parameters.zotero.data,
    // Scaffold's fallback is process-global. A no-op keeps shutdown scoped to
    // the child Zotero process that the runner owns.
    ZOTERO_PLUGIN_KILL_COMMAND: ":",
  };
}

function scaffoldArgs(command) {
  if (command === "build" || command === "serve")
    return [command];
  fail(`unknown developer command: ${command}`);
}

function runScaffold(command, parameters, stdio = "inherit") {
  if (!existsSync(scaffoldCli))
    fail("zotero-plugin-scaffold is not installed; run npm install first");

  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [scaffoldCli, ...scaffoldArgs(command)], {
      cwd: root,
      env: runtimeEnvironment(parameters),
      stdio,
    });
    child.once("error", reject);
    child.once("exit", (code) => resolvePromise(code ?? 1));
  });
}

function runOnce(parameters) {
  if (!existsSync(scaffoldCli))
    fail("zotero-plugin-scaffold is not installed; run npm install first");

  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [scaffoldCli, "serve"], {
      cwd: root,
      env: runtimeEnvironment(parameters),
      stdio: ["inherit", "pipe", "pipe"],
    });
    let ready = false;
    let stopping = false;
    let outputTail = "";
    let readyTimer;
    let settleTimer;

    const stop = () => {
      if (stopping)
        return;
      stopping = true;
      child.kill("SIGINT");
    };

    const inspect = (chunk) => {
      outputTail = `${outputTail}${chunk.toString()}`.slice(-256);
      if (!ready && outputTail.includes("Server Ready!")) {
        ready = true;
        process.stderr.write("Scaffold connected and installed the temporary add-on; waiting for native startup.\n");
        settleTimer = setTimeout(stop, parameters.devOnce.settleMs);
      }
    };

    child.stdout.on("data", (chunk) => {
      process.stdout.write(chunk);
      inspect(chunk);
    });
    child.stderr.on("data", (chunk) => {
      process.stderr.write(chunk);
      inspect(chunk);
    });
    child.once("error", reject);
    readyTimer = setTimeout(() => {
      if (!ready)
        process.stderr.write("Scaffold did not reach Server Ready before the configured timeout.\n");
      stop();
    }, parameters.devOnce.readyTimeoutMs);
    child.once("exit", (code) => {
      clearTimeout(readyTimer);
      clearTimeout(settleTimer);
      resolvePromise(ready && code === 0 ? 0 : 1);
    });
  });
}

async function main() {
  const command = process.argv[2];
  if (!command)
    fail("usage: node scripts/zotero-plugin-dev.mjs <build|serve|once>");
  const parameters = loadParameters();
  const code = command === "once"
    ? await runOnce(parameters)
    : await runScaffold(command, parameters);
  process.exitCode = code;
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
