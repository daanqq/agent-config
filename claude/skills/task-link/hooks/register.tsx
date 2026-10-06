import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { TaskLink } from '../types'

// Mirrors pi/agent/extensions/00-ui-editor.ts.
export const TASK_URL_PREFIX = 'https://spacehub.esoft.tech/entity/'
export const COMMAND = 'taskurl'

const task = atom({ plugin: 'task-link', key: 'task' } as const, null)

export function parseTaskUrl(value: unknown): TaskLink | undefined {
  if (typeof value !== 'string' || !value.startsWith(TASK_URL_PREFIX)
    || /[\s\x00-\x1f\x7f-\x9f]/.test(value)) return undefined
  try {
    const url = new URL(value)
    const id = url.pathname.match(/^\/entity\/([A-Za-z0-9][A-Za-z0-9_-]*)\/?$/)?.[1]
    if (id) return { id, url: url.href }
  } catch {
    return undefined
  }
  return undefined
}

export function firstTaskLink(text: string): TaskLink | undefined {
  const links = text.matchAll(/https:\/\/spacehub\.esoft\.tech\/entity\/[^\s<>"'`\)\]\}]+/g)
  for (const [link] of links) {
    const found = parseTaskUrl(link.replace(/[.,;:!?]+$/, ''))
    if (found) return found
  }
  return undefined
}

// The store outlives the session, so the task is kept per session id and
// comes back on --resume.
async function setTask($: EngineInterface, next: TaskLink): Promise<void> {
  await $.store.set(await $.session.id(), next.url)
  await update($, task, () => next)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: "Set or replace the session's SpaceHub task URL",
      argumentHint: `${TASK_URL_PREFIX}EUTP-170658`,
    })
    const restored = parseTaskUrl(await $.store.get(await $.session.id()))
    await update($, task, () => restored ?? null)

    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    if (e.origin.kind === 'composer' && (await read($, task)) === null) {
      const first = firstTaskLink(e.text)
      if (first) await setTask($, first)
    }

    return next(e)
  })

  on('command.run', { command: COMMAND }, async ($, e) => {
    const next = parseTaskUrl(e.args.trim())
    if (!next) {
      $.ui.toast(`Usage: /${COMMAND} ${TASK_URL_PREFIX}EUTP-170658`)
      return {}
    }
    await setTask($, next)
    $.ui.toast(`Session task: ${next.id}`)

    return {}
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const current = await read($, task)
    if (current === null || e.props.hasSurvey) return next(e)

    const { Box, Text } = $.ui.resolve(e)

    // Plain text, not Link: without FORCE_HYPERLINK Claude Code does not emit
    // OSC 8 under herdr, and herdr opens a clicked URL found in the text,
    // trimming the unbalanced closing bracket.
    return (
      <Box width={e.props.bodyColumns} justifyContent="flex-end">
        <Text>[{current.url}]</Text>
      </Box>
    )
  })
}
