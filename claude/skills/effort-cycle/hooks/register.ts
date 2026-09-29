import type { EngineInterface, On } from 'claude-code'

/**
 * The cycle; `max` is left out on purpose, so `max` and anything unknown
 * step to `low`.
 */
export const LEVELS = ['low', 'medium', 'high', 'xhigh'] as const

export const COMMAND = 'effort-next'

export function nextLevelOf(current: unknown): string {
  const index = LEVELS.findIndex(level => level === current)

  return LEVELS[(index + 1) % LEVELS.length] ?? LEVELS[0]
}

export function register(on: On): void {
  // /effort does not report the level back, so the last one set through it or
  // seen on a model request is the current one; before either, and after
  // /effort's picker, settings decide.
  let current: unknown

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: 'Raise effort: low → medium → high → xhigh → low',
      immediate: true,
    })

    return next(e)
  })

  on('turn.step', async function* ($, e, next) {
    if (e.agentId === undefined) {
      current = e.effort
    }

    return yield* next(e)
  })

  on('command.run', { command: 'effort' }, async ($, e, next) => {
    const result = await next(e)
    current = e.args.trim() || undefined

    return result
  })

  on('command.run', { command: COMMAND }, async $ => {
    current ??= await settingsLevelOf($)
    const level = nextLevelOf(current)
    current = level
    // The engine refuses $.command.run inside a command.run hook, so the
    // built-in /effort runs once this hook has answered; its output is the
    // only line the press prints.
    $.clock.after(0, () => {
      $.command
        .run({ command: 'effort', args: level })
        .catch((error: unknown) => $.ui.toast(`/effort ${level}: ${error}`))
    })

    return {}
  })
}

type EffortSettings = {
  effortLevel?: unknown
  modelSettings?: Record<string, { effortLevel?: unknown } | undefined>
}

// /effort saves the level per model (`claude-opus-5-5`, no `[1m]`), over the
// top-level one.
async function settingsLevelOf($: EngineInterface): Promise<unknown> {
  const [settings, model]: [EffortSettings, string] = await Promise.all([
    $.settings.read(),
    $.session.model(),
  ])
  const perModel = settings.modelSettings?.[model.replace(/\[.*\]$/, '')]

  return perModel?.effortLevel ?? settings.effortLevel
}
