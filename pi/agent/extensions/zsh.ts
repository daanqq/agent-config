import { accessSync, constants } from "node:fs";
import { basename } from "node:path";
import {
  createLocalBashOperations,
  type ExtensionAPI,
} from "@mariozechner/pi-coding-agent";

function shellQuote(value: string) {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

function canExecute(path: string) {
  try {
    accessSync(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function getUsableZshPath() {
  if (process.platform === "win32") return undefined;

  const candidates = [
    process.env.PI_USER_BASH_SHELL,
    process.env.SHELL && basename(process.env.SHELL) === "zsh"
      ? process.env.SHELL
      : undefined,
    "/bin/zsh",
  ];

  return candidates.find((path): path is string => !!path && canExecute(path));
}

function getPiZshrcPath() {
  return process.env.PI_USER_ZSHRC ?? `${process.env.HOME}/.pi/agent/zshrc`;
}

export default function (pi: ExtensionAPI) {
  const zshPath = getUsableZshPath();
  if (!zshPath) return;

  const local = createLocalBashOperations();

  pi.on("user_bash", () => {
    return {
      operations: {
        exec(command, cwd, options) {
          // Run zsh as a non-interactive shell. Avoid `-i`: it sources ~/.zshrc,
          // which can start prompt/ZLE integrations without a real interactive
          // job-control terminal. Source a small pi-specific zshrc instead for
          // safe aliases/functions, then eval the user command so aliases expand.
          const initPath = getPiZshrcPath();
          const initCommand = `[[ -r ${shellQuote(initPath)} ]] && source ${shellQuote(initPath)}; eval ${shellQuote(command)}`;
          const zshCommand = `PI_USER_BASH=1 exec ${shellQuote(zshPath)} -fc ${shellQuote(initCommand)}`;
          return local.exec(zshCommand, cwd, options);
        },
      },
    };
  });
}