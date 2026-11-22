import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const agentDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const args = new Set(process.argv.slice(2));
const devMode = args.has("--dev");

const runtimeDirectories = [resolve(agentDir, "extensions")];
const devDirectories = [
  resolve(agentDir, "extensions"),
  resolve(agentDir, "extensions", "background-terminals"),
  resolve(agentDir, "extensions", "firecrawl-search"),
  resolve(agentDir, "extensions", "subagents"),
];

const packageDirectories = devMode ? devDirectories : runtimeDirectories;
const npmArgs = devMode ? ["ci"] : ["ci", "--omit=dev", "--ignore-scripts"];

function runNpm(cwd) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(npm, npmArgs, {
      cwd,
      stdio: "inherit",
      // npm.cmd is a shell script on Windows rather than a native executable.
      shell: process.platform === "win32",
    });
    child.once("error", reject);
    child.once("close", (code, signal) => {
      if (code === 0) resolveRun();
      else reject(new Error(`npm ${npmArgs.join(" ")} failed${signal ? ` (${signal})` : ` with exit code ${code}`}`));
    });
  });
}

for (const cwd of packageDirectories) {
  console.log(`Installing ${devMode ? "dev + runtime" : "runtime"} dependencies in ${cwd}`);
  await runNpm(cwd);
}

console.log(`All ${devMode ? "dev + runtime" : "runtime"} extension dependencies are installed.`);
