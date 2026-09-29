import type { CommandRunInput, On } from 'claude-code'
import { describe, expect, mock, test, tier } from 'claude-code/testing'
import type { Engine, MockClock } from 'claude-code/testing'

tier('user')

const NEXT: CommandRunInput = {
  command: 'effort-next',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: false, columns: 100 },
}

type Session = { set: string[]; clock: MockClock }

function sessionOf(on: On, settings: Record<string, unknown> = {}): Session {
  const set: string[] = []
  const clock = mock.clock(on)
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  on('settings.read', () => ({ value: settings }))
  on('session.model', () => ({ value: 'claude-opus-5-5[1m]' }))
  on('command.run', { command: 'effort' }, ($, e) => {
    set.push(e.args)

    return { text: `Set effort level to ${e.args}` }
  })
  on('turn.step', async function* ($, e) {
    return {
      turnId: e.turnId,
      index: e.index,
      answer: '',
      toolUses: [],
      stopReason: 'end_turn',
      usage: null,
    }
  })

  return { set, clock }
}

async function pressNext(
  $: Engine,
  clock: MockClock,
): Promise<void> {
  expect(await $.command.run(NEXT)).toEqual({})
  await clock.advance(0)
  await clock.settle()
}

describe('register', () => {
  test("from the model's saved level it steps up and wraps past xhigh to low", async ($, on) => {
    const { set, clock } = sessionOf(on, {
      effortLevel: 'high',
      modelSettings: { 'claude-opus-5-5': { effortLevel: 'medium' } },
    })

    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/w' })
    for (let i = 0; i < 4; i++) {
      await pressNext($, clock)
    }

    expect(set).toEqual(['high', 'xhigh', 'low', 'medium'])
  })

  test('max and an unset level step to low', async ($, on) => {
    const { set, clock } = sessionOf(on)

    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/w' })
    await pressNext($, clock)

    expect(set).toEqual(['low'])

    const step = $.turn.step({
      turnId: 't',
      index: 0,
      model: 'm',
      effort: 'max',
      messageCount: 1,
    })
    for await (const chunk of step) {
      expect(chunk).toBeUndefined()
    }
    await pressNext($, clock)

    expect(set).toEqual(['low', 'low'])
  })

  test('a level typed with /effort is where the cycle goes on from', async ($, on) => {
    const { set, clock } = sessionOf(on, { effortLevel: 'medium' })

    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/w' })
    await pressNext($, clock)
    await $.command.run({ ...NEXT, command: 'effort', args: 'max' })
    await pressNext($, clock)

    expect(set).toEqual(['high', 'max', 'low'])
  })
})
