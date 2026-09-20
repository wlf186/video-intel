import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { get } from "node:http";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { createServer } from "vite";

function message(socket, predicate) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error("WebSocket response timed out")); }, 10000);
    function cleanup() { clearTimeout(timer); socket.removeEventListener("message", receive); }
    function receive(event) {
      const value = JSON.parse(event.data);
      if (predicate(value)) { cleanup(); resolve(value); }
    }
    socket.addEventListener("message", receive);
  });
}

test("Vite blocks external files while serving modules and HMR", { timeout: 30000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "video-intel-vite-"));
  const root = join(directory, "app");
  await mkdir(root);
  const marker = "PRIVATE_VIDEO_INTEL_SECURITY_MARKER";
  await writeFile(join(directory, "secret.html"), marker);
  await writeFile(join(directory, "secret.js.map"), JSON.stringify({version: 3, file: "x.js", sources: ["secret"], sourcesContent: [marker], names: [], mappings: ""}));
  await writeFile(join(root, "index.html"), '<script type="module" src="/main.js"></script>');
  await writeFile(join(root, "main.js"), 'export const value = "legitimate"; if(import.meta.hot) import.meta.hot.accept();');
  const server = await createServer({
    configFile: false, root, logLevel: "silent",
    server: { host: "127.0.0.1", port: 0, fs: { strict: true, allow: [root] } },
  });
  let socket;
  try {
    await server.listen();
    const port = server.httpServer.address().port;
    const base = `http://127.0.0.1:${port}`;
    assert.match(await (await fetch(`${base}/main.js`)).text(), /legitimate/);
    for (const path of [
      `/@fs${join(directory, "secret.html")}`,
      `/@fs${join(directory, "secret.html")}?raw`,
      `/@fs${join(directory, "secret.js.map")}`,
    ]) {
      const response = await fetch(base + path);
      assert.ok([403, 404].includes(response.status), `${path}: ${response.status}`);
      assert.ok(!(await response.text()).includes(marker));
    }
    assert.ok(server.environments.client.depsOptimizer, "Exercise optimized-dependency middleware");
    // http.get preserves ../ instead of normalizing the attack before it reaches Vite.
    const traversedMap = await new Promise((resolve, reject) => {
      get({hostname: "127.0.0.1", port, path: "/node_modules/.vite/deps/../../../../secret.js.map"}, (response) => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => { body += chunk; });
        response.on("end", () => resolve({status: response.statusCode, body}));
      }).on("error", reject);
    });
    assert.ok(!traversedMap.body.includes(marker), "Optimized sourcemap traversal disclosed private content");
    if (traversedMap.status === 200) {
      // Vite may serve the app's index fallback after rejecting this map route.
      assert.match(traversedMap.body, /src="\/main\.js"/);
    } else {
      assert.ok([403, 404].includes(traversedMap.status), `Traversal status: ${traversedMap.status}`);
    }
    socket = new WebSocket(`ws://127.0.0.1:${port}/?token=${server.config.webSocketToken}`, "vite-hmr");
    await message(socket, (value) => value.type === "connected");
    for (const suffix of ["?raw", "?inline"]) {
      const response = message(socket, (value) => value.event === "vite:invoke");
      socket.send(JSON.stringify({type: "custom", event: "vite:invoke", data: {
        name: "fetchModule", id: "send:security", data: [pathToFileURL(join(directory, "secret.html")).href + suffix],
      }}));
      const value = await response;
      assert.ok(value.data.data.error, JSON.stringify(value));
      assert.ok(!JSON.stringify(value).includes(marker));
    }
    const update = message(socket, (value) => value.type === "update");
    await writeFile(join(root, "main.js"), 'export const value = "updated"; if(import.meta.hot) import.meta.hot.accept();');
    assert.ok((await update).updates.some((value) => value.path === "/main.js"));
    assert.match(await (await fetch(`${base}/main.js`)).text(), /updated/);
  } finally {
    socket?.close();
    await server.close();
    await rm(directory, { recursive: true, force: true });
  }
});
