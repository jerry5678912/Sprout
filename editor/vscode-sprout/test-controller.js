const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

function execFile(command, args, cwd) {
  return new Promise((resolve) => {
    childProcess.execFile(command, args, { cwd, maxBuffer: 8 * 1024 * 1024 }, (error, stdout, stderr) => {
      resolve({ error, stdout, stderr });
    });
  });
}

function workspaceFor(vscode, uri) {
  return vscode.workspace.getWorkspaceFolder(uri) || vscode.workspace.workspaceFolders?.[0];
}

function testId(test) {
  return `${test.path}:${test.line}:${test.name}`;
}

async function createSproutTestController(vscode, context, runner, python) {
  if (!runner || !vscode.tests?.createTestController) return undefined;
  const controller = vscode.tests.createTestController("sproutTests", "Sprout Tests");
  context.subscriptions.push(controller);
  const testsById = new Map();

  async function discover(targetUri) {
    const folder = workspaceFor(vscode, targetUri);
    const cwd = folder?.uri.fsPath || path.dirname(targetUri?.fsPath || runner);
    const defaultTests = path.join(cwd, "tests");
    const target = targetUri?.fsPath || (fs.existsSync(defaultTests) ? defaultTests : cwd);
    const result = await execFile(python, [runner, "test", target, "--list", "--json"], cwd);
    if (result.error && !result.stdout.trim()) return [];
    try {
      return JSON.parse(result.stdout).tests || [];
    } catch (_error) {
      return [];
    }
  }

  function addDiscovered(test) {
    const uri = vscode.Uri.file(test.path);
    const fileId = `file:${test.path}`;
    let fileItem = controller.items.get(fileId);
    if (!fileItem) {
      fileItem = controller.createTestItem(fileId, path.basename(test.path), uri);
      controller.items.add(fileItem);
    }
    const id = testId(test);
    let item = fileItem.children.get(id);
    if (!item) {
      item = controller.createTestItem(id, test.name, uri);
      fileItem.children.add(item);
    }
    item.range = new vscode.Range(
      Math.max(0, Number(test.line || 1) - 1),
      Math.max(0, Number(test.column || 1) - 1),
      Math.max(0, Number(test.line || 1) - 1),
      Math.max(1, Number(test.column || 1))
    );
    item.description = `${path.basename(test.path)}:${test.line}`;
    testsById.set(id, { item, test });
  }

  async function refresh(uri) {
    const tests = await discover(uri);
    const root = workspaceFor(vscode, uri);
    if (!uri || root?.uri.fsPath === uri.fsPath) {
      controller.items.replace([]);
      testsById.clear();
    } else {
      controller.items.delete(`file:${uri.fsPath}`);
      for (const [id, entry] of testsById) {
        if (entry.test.path === uri.fsPath) testsById.delete(id);
      }
    }
    for (const test of tests) addDiscovered(test);
  }

  controller.refreshHandler = () => refresh(undefined);

  const profile = controller.createRunProfile(
    "Run",
    vscode.TestRunProfileKind.Run,
    async (request, token) => {
      const run = controller.createTestRun(request);
      const selected = [];
      if (request.include?.length) {
        for (const item of request.include) {
          const entry = testsById.get(item.id);
          if (entry) selected.push(entry);
          else item.children.forEach((child) => {
            const childEntry = testsById.get(child.id);
            if (childEntry) selected.push(childEntry);
          });
        }
      } else {
        selected.push(...testsById.values());
      }

      for (const entry of selected) {
        if (token.isCancellationRequested || request.exclude?.some((item) => item.id === entry.item.id)) continue;
        run.started(entry.item);
        const folder = workspaceFor(vscode, entry.item.uri);
        const cwd = folder?.uri.fsPath || path.dirname(entry.test.path);
        const result = await execFile(
          python,
          [runner, "test", entry.test.path, "--filter", entry.test.name, "--json"],
          cwd
        );
        try {
          const payload = JSON.parse(result.stdout);
          const outcome = (payload.tests || [])[0];
          if (outcome?.status === "passed") {
            if (outcome.output) run.appendOutput(outcome.output.replace(/\n/g, "\r\n"), undefined, entry.item);
            run.passed(entry.item);
          } else {
            const message = new vscode.TestMessage(outcome?.message || result.stderr || "Sprout test failed");
            message.location = new vscode.Location(entry.item.uri, entry.item.range);
            run.failed(entry.item, message);
          }
        } catch (_error) {
          run.errored(entry.item, new vscode.TestMessage(result.stderr || result.stdout || "Invalid Sprout test output"));
        }
      }
      run.end();
    },
    true
  );
  context.subscriptions.push(profile);

  const watcher = vscode.workspace.createFileSystemWatcher("**/*.sprout");
  const update = (uri) => {
    if (uri.fsPath.includes(`${path.sep}tests${path.sep}`) || /_test\.sprout$/.test(uri.fsPath)) {
      refresh(uri);
    }
  };
  watcher.onDidCreate(update);
  watcher.onDidChange(update);
  watcher.onDidDelete((uri) => {
    controller.items.delete(`file:${uri.fsPath}`);
    for (const [id, entry] of testsById) {
      if (entry.test.path === uri.fsPath) testsById.delete(id);
    }
  });
  context.subscriptions.push(watcher);

  await refresh(undefined);
  return controller;
}

module.exports = { createSproutTestController };
