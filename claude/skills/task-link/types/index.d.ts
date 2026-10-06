export type TaskLink = { id: string; url: string }

declare module 'claude-code' {
  interface PluginState {
    'task-link': { task: TaskLink | null }
  }
}
