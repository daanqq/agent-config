import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const agentDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const packageDirectories = [
  resolve(agentDir, "extensions"),
  resolve(agentDir, "extensions", "firecrawl-search"),
  resolve(agentDir, "extensions", "subagents"),
];

function runNpm(cwd) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(npm, ["ci"], {
      cwd,
      stdio: "inherit",
      // npm.cmd is a shell script on Windows rather than a native executable.
      shell: process.platform === "win32",
    });
    child.once("error", reject);
    child.once("close", (code, signal) => {
      if (code === 0) resolveRun();
      else reject(new Error(`npm ci failed${signal ? ` (${signal})` : ` with exit code ${code}`}`));
    });
  });
}

for (const cwd of packageDirectories) {
  console.log(`Installing dependencies in ${cwd}`);
  await runNpm(cwd);
}

console.log("All extension dependencies are installed.");
