const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

class SproutLanguageClient {
  constructor(vscode, pythonPath, runnerPath, extensionPath, diagnostics) {
    this.vscode = vscode;
    this.pythonPath = pythonPath;
    this.runnerPath = runnerPath;
    this.extensionPath = extensionPath;
    this.diagnostics = diagnostics;
    this.process = undefined;
    this.buffer = Buffer.alloc(0);
    this.nextId = 1;
    this.pending = new Map();
    this.ready = false;
    this.stopping = false;
  }

  findServer() {
    const candidates = [
      path.join(this.extensionPath, "tools", "sprout_lsp.py"),
      path.join(path.dirname(this.runnerPath), "tools", "sprout_lsp.py")
    ];
    return candidates.find((candidate) => fs.existsSync(candidate));
  }

  async start() {
    const server = this.findServer();
    if (!server) return false;
    this.process = childProcess.spawn(this.pythonPath, [server], {
      cwd: this.vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || path.dirname(this.runnerPath),
      stdio: ["pipe", "pipe", "pipe"]
    });
    this.process.stdout.on("data", (chunk) => this.onData(chunk));
    this.process.stderr.on("data", (chunk) => {
      const text = String(chunk).trim();
      if (text) console.warn(`[Sprout LSP] ${text}`);
    });
    this.process.on("exit", () => {
      this.ready = false;
      for (const { reject } of this.pending.values()) reject(new Error("Sprout language server stopped"));
      this.pending.clear();
    });

    const folders = (this.vscode.workspace.workspaceFolders || []).map((folder) => ({
      uri: folder.uri.toString(),
      name: folder.name
    }));
    const rootUri = folders[0]?.uri || null;
    await this.request("initialize", {
      processId: process.pid,
      rootUri,
      workspaceFolders: folders,
      capabilities: {
        general: { positionEncodings: ["utf-16"] },
        workspace: { workspaceFolders: true },
        textDocument: {
          completion: { completionItem: { snippetSupport: true, documentationFormat: ["markdown", "plaintext"] } },
          hover: { contentFormat: ["markdown", "plaintext"] },
          definition: {},
          references: {},
          rename: { prepareSupport: true },
          signatureHelp: {},
          documentSymbol: {},
          codeAction: { codeActionLiteralSupport: { codeActionKind: { valueSet: ["quickfix"] } } }
        }
      }
    });
    this.notify("initialized", {});
    this.ready = true;
    return true;
  }

  send(payload) {
    if (!this.process?.stdin.writable) throw new Error("Sprout language server is unavailable");
    const body = Buffer.from(JSON.stringify(payload), "utf8");
    this.process.stdin.write(`Content-Length: ${body.length}\r\n\r\n`);
    this.process.stdin.write(body);
  }

  notify(method, params) {
    this.send({ jsonrpc: "2.0", method, params });
  }

  request(method, params, token) {
    const id = this.nextId++;
    const promise = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.send({ jsonrpc: "2.0", id, method, params });
    });
    if (token) {
      token.onCancellationRequested(() => this.notify("$/cancelRequest", { id }));
    }
    return promise;
  }

  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (true) {
      const boundary = this.buffer.indexOf("\r\n\r\n");
      if (boundary === -1) return;
      const headers = this.buffer.slice(0, boundary).toString("ascii");
      const match = headers.match(/Content-Length:\s*(\d+)/i);
      if (!match) {
        this.buffer = Buffer.alloc(0);
        return;
      }
      const length = Number(match[1]);
      const bodyStart = boundary + 4;
      if (this.buffer.length < bodyStart + length) return;
      const body = this.buffer.slice(bodyStart, bodyStart + length).toString("utf8");
      this.buffer = this.buffer.slice(bodyStart + length);
      try {
        this.onMessage(JSON.parse(body));
      } catch (error) {
        console.warn(`[Sprout LSP] Invalid response: ${error}`);
      }
    }
  }

  onMessage(message) {
    if (Object.prototype.hasOwnProperty.call(message, "id")) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message || "Sprout LSP request failed"));
      else pending.resolve(message.result);
      return;
    }
    if (message.method === "textDocument/publishDiagnostics") {
      this.publishDiagnostics(message.params || {});
    }
  }

  publishDiagnostics(params) {
    const uri = this.vscode.Uri.parse(params.uri);
    const diagnostics = (params.diagnostics || []).map((item) => {
      const range = new this.vscode.Range(
        item.range.start.line,
        item.range.start.character,
        item.range.end.line,
        item.range.end.character
      );
      const severity = item.severity === 2
        ? this.vscode.DiagnosticSeverity.Warning
        : this.vscode.DiagnosticSeverity.Error;
      const diagnostic = new this.vscode.Diagnostic(range, item.message, severity);
      diagnostic.code = item.code;
      diagnostic.source = item.source || "sprout";
      return diagnostic;
    });
    if (diagnostics.length) this.diagnostics.set(uri, diagnostics);
    else this.diagnostics.delete(uri);
  }

  open(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    this.notify("textDocument/didOpen", {
      textDocument: {
        uri: document.uri.toString(),
        languageId: "sprout",
        version: document.version,
        text: document.getText()
      }
    });
  }

  change(event) {
    if (!this.ready || event.document.languageId !== "sprout") return;
    this.notify("textDocument/didChange", {
      textDocument: { uri: event.document.uri.toString(), version: event.document.version },
      contentChanges: event.contentChanges.map((change) => ({
        range: {
          start: { line: change.range.start.line, character: change.range.start.character },
          end: { line: change.range.end.line, character: change.range.end.character }
        },
        rangeLength: change.rangeLength,
        text: change.text
      }))
    });
  }

  save(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    this.notify("textDocument/didSave", { textDocument: { uri: document.uri.toString() } });
  }

  close(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    this.notify("textDocument/didClose", { textDocument: { uri: document.uri.toString() } });
    this.diagnostics.delete(document.uri);
  }

  textRequest(method, document, position, extra = {}, token) {
    if (!this.ready) return Promise.resolve(undefined);
    return this.request(method, {
      textDocument: { uri: document.uri.toString() },
      position: { line: position.line, character: position.character },
      ...extra
    }, token);
  }

  async stop() {
    if (!this.process || this.stopping) return;
    this.stopping = true;
    try {
      await this.request("shutdown", {});
      this.notify("exit", {});
    } catch (_error) {
      this.process.kill();
    }
    this.ready = false;
  }
}

module.exports = { SproutLanguageClient };
