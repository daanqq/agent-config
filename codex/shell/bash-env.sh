# Codex reads this through BASH_ENV ([shell_environment_policy.set] in ~/.codex/config.toml).
# T3 starts codex through the mise shim, and mise puts the global tools (node 22) ahead of
# the shims in the PATH it hands down. Moving the shims first lets node follow the .nvmrc of
# the current repository, as in Claude Code shells (~/.zshrc).
shims="$HOME/.local/share/mise/shims"
if [ -d "$shims" ]; then
  p=":$PATH:"
  p="${p//:$shims:/:}"
  p="${p#:}"
  PATH="$shims:${p%:}"
  export PATH
fi
unset shims p
