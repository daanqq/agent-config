import type { CommandRunInput, PromptSubmitInput, On, RenderPropsOf } from 'claude-code'
import { describe, expect, test, tier } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

tier('user')

const URL_A = 'https://spacehub.esoft.tech/entity/EUTP-170658'
const URL_B = 'https://spacehub.esoft.tech/entity/EUTP-1'

const BAND: RenderPropsOf['AbovePrompt'] = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 9 },
  view: {},
}

const TASKURL: CommandRunInput = {
  command: 'taskurl',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 100 },
}

function prompt(text: string): PromptSubmitInput {
  return { text, wait: false, origin: { kind: 'composer' } }
}

type Session = { toasts: string[]; store: Map<string, unknown> }

function sessionOf(on: On, stored: Record<string, unknown> = {}): Session {
  const toasts: string[] = []
  const store = new Map(Object.entries(stored))
  on('store.get', ($, e) => ({ value: store.get(e.key) }))
  on('store.set', ($, e) => {
    store.set(e.key, e.value)
    return { value: undefined }
  })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('prompt.submit', ($, e) => ({ text: e.text }))
  on('ui.toast', ($, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => $.ui.resolve(e).Box({}))

  return { toasts, store }
}

async function start($: Engine): Promise<void> {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/w' })
}

async function bandText($: Engine): Promise<string | undefined> {
  const ui = await $.ui.mount({
    plugin: 'task-link',
    surface: 'terminal',
    component: 'AbovePrompt',
    props: BAND,
  })
  const text = await ui.find({ type: 'Text' })
  await ui.unmount()

  return text?.text
}

describe('register', () => {
  test('the first task URL typed in the session is drawn and kept', async ($, on) => {
    const { store } = sessionOf(on)
    await start($)
    expect(await bandText($)).toBeUndefined()

    await $.prompt.submit(prompt(`see (${URL_A}).`))
    await $.prompt.submit(prompt(URL_B))

    expect(await bandText($)).toBe(`[${URL_A}]`)
    expect(store.get('s1')).toBe(URL_A)
  })

  test('/taskurl replaces the task and rejects anything else', async ($, on) => {
    const { toasts } = sessionOf(on)
    await start($)

    await $.command.run({ ...TASKURL, args: URL_A })
    await $.command.run({ ...TASKURL, args: 'https://example.com/entity/X' })

    expect(await bandText($)).toBe(`[${URL_A}]`)
    expect(toasts).toEqual([
      'Session task: EUTP-170658',
      'Usage: /taskurl https://spacehub.esoft.tech/entity/EUTP-170658',
    ])
  })

  test('a resumed session restores its task from the store', async ($, on) => {
    sessionOf(on, { s1: URL_B })
    await start($)

    expect(await bandText($)).toBe(`[${URL_B}]`)
  })
})
