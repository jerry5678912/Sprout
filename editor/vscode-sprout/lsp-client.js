const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");

class SproutLanguageClient {
  constructor(vscode, pythonPath, runnerPath, extensionPath, diagnostics, outputChannel) {
    this.vscode = vscode;
    this.pythonPath = pythonPath;
    this.runnerPath = runnerPath;
    this.extensionPath = extensionPath;
    this.diagnostics = diagnostics;
    this.outputChannel = outputChannel;
    this.process = undefined;
    this.buffer = Buffer.alloc(0);
    this.nextId = 1;
    this.pending = new Map();
    this.requestTimeoutMs = 6000;
    this.ready = false;
    this.starting = false;
    this.stopping = false;
    this.openDocuments = new Map();
    this.pendingSyncs = new Map();
  }

  log(message) {
    const stamped = `[${new Date().toISOString()}] ${message}`;
    if (this.outputChannel) this.outputChannel.appendLine(stamped);
    else console.log(`[Sprout LSP] ${message}`);
  }

  findServer() {
    const candidates = [
      path.join(this.extensionPath, "tools", "sprout_lsp.py"),
      path.join(path.dirname(this.runnerPath), "tools", "sprout_lsp.py")
    ];
    return candidates.find((candidate) => fs.existsSync(candidate));
  }

  settings() {
    const config = this.vscode.workspace.getConfiguration("sprout");
    return {
      sprout: {
        diagnostics: {
          enabled: config.get("diagnostics.enabled", true),
          visibleSquiggles: config.get("diagnostics.visibleSquiggles", true),
          styleWarnings: config.get("diagnostics.styleWarnings", true),
          typoChecking: config.get("diagnostics.typoChecking", true)
        },
        analysis: {
          typeCheckingMode: config.get("analysis.typeCheckingMode", "basic"),
          diagnosticMode: config.get("analysis.diagnosticMode", "workspace"),
          indexing: config.get("analysis.indexing", true),
          userFileIndexingLimit: config.get("analysis.userFileIndexingLimit", 2000),
          useLibraryCodeForTypes: config.get("analysis.useLibraryCodeForTypes", true),
          exclude: config.get("analysis.exclude", []),
          languageServerMode: config.get("analysis.languageServerMode", "default"),
          diagnosticSeverityOverrides: config.get("analysis.diagnosticSeverityOverrides", {})
        }
      }
    };
  }

  async start() {
    this.starting = true;
    const server = this.findServer();
    if (!server) {
      this.log("No language server found. Falling back to command-based providers.");
      this.starting = false;
      return false;
    }
    const cwd = this.vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || path.dirname(this.runnerPath);
    this.log(`Starting language server`);
    this.log(`Python: ${this.pythonPath}`);
    this.log(`Server: ${server}`);
    this.log(`Runner: ${this.runnerPath}`);
    this.log(`CWD: ${cwd}`);
    this.process = childProcess.spawn(this.pythonPath, [server], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"]
    });
    this.process.stdout.on("data", (chunk) => this.onData(chunk));
    this.process.stderr.on("data", (chunk) => {
      const text = String(chunk).trim();
      if (text) this.log(text);
    });
    this.process.on("error", (error) => {
      this.log(`Language server process error: ${error.message}`);
    });
    this.process.on("exit", (code, signal) => {
      this.log(`Language server exited code=${code ?? "none"} signal=${signal ?? "none"}`);
      this.ready = false;
      this.starting = false;
      this.openDocuments.clear();
      for (const pending of this.pendingSyncs.values()) {
        clearTimeout(pending.timer);
      }
      this.pendingSyncs.clear();
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
      initializationOptions: this.settings(),
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
    this.starting = false;
    this.log("Language server initialized");
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
      const startedAt = Date.now();
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) {
          this.log(`Request timed out: ${method} id=${id}`);
          reject(new Error(`Sprout language server request timeout: ${method}`));
        }
      }, this.requestTimeoutMs);
      this.pending.set(id, { resolve, reject, timer, method, startedAt });
      this.send({ jsonrpc: "2.0", id, method, params });
      if (token) {
        token.onCancellationRequested(() => {
          const pending = this.pending.get(id);
          if (!pending) return;
          this.pending.delete(id);
          clearTimeout(pending.timer);
          this.notify("$/cancelRequest", { id });
          pending.reject(new Error(`Sprout language server request cancelled: ${method}`));
        });
      }
    });
    return promise;
  }

  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (true) {
      let boundary = this.buffer.indexOf("\r\n\r\n");
      let headerEnd = 4;
      if (boundary === -1) {
        const lfBoundary = this.buffer.indexOf("\n\n");
        if (lfBoundary !== -1) {
          boundary = lfBoundary;
          headerEnd = 2;
        }
      }
      if (boundary === -1) return;
      const headers = this.buffer.slice(0, boundary).toString("utf8");
      const match = headers.match(/Content-Length:\s*(\d+)/i);
      if (!match) {
        this.log(`Malformed LSP headers: ${headers.slice(0, 200)}...`);
        let nextOffset = boundary + headerEnd;
        while (nextOffset < this.buffer.length && this.buffer[nextOffset] !== 10) {
          nextOffset += 1;
        }
        const newlineLength = this.buffer[nextOffset] === 10 ? (this.buffer[nextOffset - 1] === 13 ? 2 : 1) : 0;
        this.buffer = newlineLength > 0
          ? this.buffer.slice(nextOffset + newlineLength)
          : Buffer.alloc(0);
        continue;
      }
      const length = Number(match[1]);
      if (!Number.isFinite(length) || length < 0 || length > 16 * 1024 * 1024) {
        this.log(`Invalid Content-Length: ${match[1]}`);
        this.buffer = this.buffer.slice(boundary + headerEnd);
        continue;
      }
      const bodyStart = boundary + headerEnd;
      if (this.buffer.length < bodyStart + length) return;
      const bodyBytes = this.buffer.slice(bodyStart, bodyStart + length);
      let body;
      try {
        body = bodyBytes.toString("utf8");
      } catch (error) {
        this.log(`Invalid LSP body encoding: ${error}`);
        this.buffer = this.buffer.slice(bodyStart + length);
        continue;
      }
      this.buffer = this.buffer.slice(bodyStart + length);
      try {
        this.onMessage(JSON.parse(body));
      } catch (error) {
        this.log(`Invalid response: ${error}`);
      }
    }
  }

  dedupePublishDiagnostics(diagnostics) {
    if (!Array.isArray(diagnostics)) return diagnostics;
    const seen = new Map();
    for (const item of diagnostics) {
      if (!item || !item.range) continue;
      const key = [
        item.range.start?.line,
        item.range.start?.character,
        item.range.end?.line,
        item.range.end?.character,
        item.severity,
        item.code,
        item.message
      ].join("|");
      if (!seen.has(key)) seen.set(key, item);
    }
    return Array.from(seen.values());
  }

  onMessage(message) {
    if (Object.prototype.hasOwnProperty.call(message, "id")) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      const elapsed = Math.max(0, Date.now() - (pending.startedAt || Date.now()));
      if (elapsed >= 150) {
        this.log(`Slow request ${pending.method} ${elapsed}ms`);
      }
      if (message.error) pending.reject(new Error(message.error.message || "Sprout LSP request failed"));
      else pending.resolve(message.result);
      return;
    }
    if (message.method === "textDocument/publishDiagnostics") {
      this.publishDiagnostics(message.params || {});
    }
  }

  publishDiagnostics(params) {
    if (!params?.uri) return;
    let uri;
    try {
      uri = this.vscode.Uri.parse(params.uri);
    } catch (_error) {
      this.log(`Invalid diagnostic uri: ${params.uri}`);
      return;
    }
    const document = this.vscode.workspace.textDocuments.find((candidate) => candidate.uri.toString() === uri.toString());
    if (!document) {
      this.diagnostics.delete(uri);
      return;
    }
    if (!params.diagnostics || params.diagnostics.length === 0) {
      this.diagnostics.delete(uri);
      return;
    }
    const documentLines = document ? document.getText().split(/\r?\n/) : [];

    const clamp = (value, minValue, maxValue) => Math.max(minValue, Math.min(maxValue, Number.isFinite(value) ? value : minValue));
    const clampPosition = (line, character) => {
      const safeLine = document
        ? clamp(line, 0, Math.max(0, documentLines.length - 1))
        : Math.max(0, Number.isFinite(line) ? line : 0);
      const lineText = documentLines[safeLine] || "";
      const safeCharacter = clamp(character, 0, lineText.length);
      return [safeLine, safeCharacter];
    };
    const normalizeDiagnosticRange = (raw) => {
      if (!raw?.start || !raw?.end) return null;
      let [startLine, startCharacter] = clampPosition(Number(raw.start.line || 0), Number(raw.start.character || 0));
      let [endLine, endCharacter] = clampPosition(
        Number(raw.end.line || startLine),
        Number(raw.end.character || startCharacter)
      );
      if (endLine < startLine) {
        endLine = startLine;
        endCharacter = startCharacter;
      }
      const startLineText = documentLines[startLine] || "";
      if (endLine === startLine) {
        const normalizedEnd = Math.max(endCharacter, startCharacter);
        endCharacter = Math.min(startLineText.length, normalizedEnd);
        if (endCharacter <= startCharacter) {
          if (startLineText.length === 0) {
            endCharacter = 0;
          } else {
            startCharacter = Math.min(startCharacter, startLineText.length - 1);
            endCharacter = Math.min(startLineText.length, startCharacter + 1);
          }
        }
      } else {
        endCharacter = Math.max(0, Math.min(documentLines[endLine]?.length || 0, endCharacter));
      }
      if (startLineText.length === 0 && startCharacter === 0 && endLine === startLine) {
        endCharacter = 0;
      }
      if (endLine === startLine && endCharacter < startCharacter) return null;
      return new this.vscode.Range(
        startLine,
        startCharacter,
        endLine,
        endCharacter
      );
    };
    if (document && document.languageId === "sprout") {
      if (!document.getText().trim()) {
        this.log(`Diagnostics cleared for blank document ${uri.toString()}`);
        this.diagnostics.delete(uri);
        return;
      }
      if (typeof params.version === "number" && document.version > params.version) {
        this.log(`Ignored stale diagnostics for ${uri.toString()} server=${params.version} editor=${document.version}`);
        return;
      }
    }
    const diagnostics = this.dedupePublishDiagnostics(params.diagnostics || []).map((item) => {
      const range = normalizeDiagnosticRange(item.range);
      const severity = ({
        1: this.vscode.DiagnosticSeverity.Error,
        2: this.vscode.DiagnosticSeverity.Warning,
        3: this.vscode.DiagnosticSeverity.Information,
        4: this.vscode.DiagnosticSeverity.Hint
      })[item.severity] || this.vscode.DiagnosticSeverity.Warning;
      if (!range) {
        return null;
      }
      const diagnostic = new this.vscode.Diagnostic(range, item.message, severity);
      diagnostic.code = item.code;
      diagnostic.source = item.source || "sprout";
      diagnostic.data = item.data || {};
      diagnostic.tags = (item.tags || []).map((tag) => {
        if (tag === 1 || tag === "unnecessary") return this.vscode.DiagnosticTag.Unnecessary;
        if (tag === 2 || tag === "deprecated") return this.vscode.DiagnosticTag.Deprecated;
        return undefined;
      }).filter(Boolean);
      return diagnostic;
    }).filter(Boolean);
    if (diagnostics.length) this.diagnostics.set(uri, diagnostics);
    else this.diagnostics.delete(uri);
    this.log(`Diagnostics received for ${uri.toString()}: ${diagnostics.length}`);
  }

  open(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    const uri = document.uri.toString();
    const openedVersion = this.openDocuments.get(uri);
    if (openedVersion !== undefined) {
      if (openedVersion !== document.version) {
        this.openDocuments.set(uri, document.version);
        this.notify("textDocument/didChange", {
          textDocument: { uri, version: document.version },
          contentChanges: [{ text: document.getText() }]
        });
        this.log(`Document synced ${uri} v${document.version}`);
      }
      return;
    }
    this.openDocuments.set(uri, document.version);
    this.notify("textDocument/didOpen", {
      textDocument: {
        uri,
        languageId: "sprout",
        version: document.version,
        text: document.getText()
      }
    });
    this.log(`Document opened ${uri} v${document.version}`);
  }

  change(event) {
    if (!this.ready || event.document.languageId !== "sprout") return;
    const uri = event.document.uri.toString();
    if (!this.openDocuments.has(uri)) {
      this.open(event.document);
      return;
    }
    this.openDocuments.set(uri, event.document.version);
    this.queueSync(event.document);
  }

  queueSync(document) {
    const uri = document.uri.toString();
    const existing = this.pendingSyncs.get(uri);
    if (existing) clearTimeout(existing.timer);
    const timer = setTimeout(() => this.flushSync(document), 180);
    this.pendingSyncs.set(uri, {
      version: document.version,
      text: document.getText(),
      timer
    });
  }

  hasPendingSync(document) {
    return this.pendingSyncs.has(document.uri.toString());
  }

  flushSync(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    const uri = document.uri.toString();
    const pending = this.pendingSyncs.get(uri);
    if (!pending) return;
    this.pendingSyncs.delete(uri);
    this.notify("textDocument/didChange", {
      textDocument: { uri, version: pending.version },
      contentChanges: [{ text: pending.text }]
    });
  }

  save(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    this.flushSync(document);
    this.log(`Document saved ${document.uri.toString()}`);
    this.notify("textDocument/didSave", { textDocument: { uri: document.uri.toString() } });
  }

  close(document) {
    if (!this.ready || document.languageId !== "sprout") return;
    const uri = document.uri.toString();
    const pending = this.pendingSyncs.get(uri);
    if (pending) {
      clearTimeout(pending.timer);
      this.pendingSyncs.delete(uri);
    }
    this.openDocuments.delete(uri);
    this.log(`Document closed ${uri}`);
    this.notify("textDocument/didClose", { textDocument: { uri } });
    this.diagnostics.delete(document.uri);
  }

  configure() {
    if (!this.ready) return;
    this.log("Configuration changed");
    this.notify("workspace/didChangeConfiguration", { settings: this.settings() });
  }

  async analysisStatus(document) {
    if (!this.ready) return undefined;
    const params = document ? { uri: document.uri.toString() } : {};
    return this.request("sprout/analysisStatus", params);
  }

  async rebuildWorkspaceIndex(document) {
    if (!this.ready) return undefined;
    const params = document ? { uri: document.uri.toString() } : {};
    return this.request("sprout/rebuildWorkspaceIndex", params);
  }

  textRequest(method, document, position, extra = {}, token) {
    if (!this.ready) return Promise.resolve(undefined);
    this.open(document);
    if (this.hasPendingSync(document)) {
      this.flushSync(document);
    }
    return this.request(method, {
      textDocument: { uri: document.uri.toString() },
      position: { line: position.line, character: position.character },
      ...extra
    }, token);
  }

  async stop() {
    if (!this.process || this.stopping) return;
    this.stopping = true;
    this.starting = false;
    for (const pending of this.pendingSyncs.values()) {
      clearTimeout(pending.timer);
    }
    this.pendingSyncs.clear();
    this.log("Stopping language server");
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
