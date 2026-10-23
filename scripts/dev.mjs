import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join } from "node:path";

const port = 4173;
const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

createServer(async (request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, `http://localhost:${port}`).pathname);
  const relativePath = pathname === "/" ? "index.html" : pathname.slice(1);
  const isPublicFile =
    relativePath === "index.html" || relativePath.startsWith("dist/") || relativePath.startsWith("go/");

  if (!isPublicFile || relativePath.includes("..")) {
    response.writeHead(404).end("Not found");
    return;
  }

  try {
    const body = await readFile(join(process.cwd(), relativePath));
    response.writeHead(200, { "Content-Type": contentTypes[extname(relativePath)] ?? "application/octet-stream" });
    response.end(body);
  } catch {
    response.writeHead(404).end("Not found");
  }
}).listen(port, () => {
  console.log(`errrt is running at http://localhost:${port}`);
});
