/**
 * SubagentManager — owns the registry of running/finished subagents.
 *
 * Each subagent is a scoped `SubagentSession` from a `SubagentBackend` plus a
 * pump fiber that folds its normalized event stream into a mutable
 * `SubagentSnapshot`. Closing a subagent's scope kills the underlying
 * session/process and stops the pump.
 *
 * The manager also exposes a synchronous `SubagentReadModel` so the
 * imperative TUI components (which render synchronously) can read snapshots
 * and issue fire-and-forget commands without touching the Effect runtime.
 */

import {
  Context,
  Effect,
  Exit,
  Fiber,
  Layer,
  Result,
  Scope,
  Semaphore,
  Stream,
} from "effect";
import type { SessionCheckpoint, SubagentBackend, SubagentSession } from "./backend.ts";
import { BackendRegistry } from "./backend.ts";
import type {
  BackendName,
  LiveToolState,
  RunOutcome,
  SpawnTask,
  SubagentEvent,
  SubagentOrigin,
  SubagentMeta,
  SubagentSnapshot,
  SubagentStatus,
  TranscriptItem,
} from "./domain.ts";
import {
  BackendUnavailableError,
  ConcurrencyLimitError,
  SendError,
  SpawnError,
} from "./domain.ts";

export const MAX_RUNNING = 4;
export const MAX_TRACKED = 64;
export const MAX_IDLE_BACKENDS = 2;
const STOP_TIMEOUT_MS = 5_000;
const ERROR_TEXT_MAX_LENGTH = 4_096;
const TRANSCRIPT_TEXT_MAX_LENGTH = 64 * 1_024;
const LIVE_ASSISTANT_MAX_LENGTH = 128 * 1_024;
const FINAL_TEXT_MAX_LENGTH = 1_024 * 1_024;
const MAX_TRANSCRIPT_ITEMS = 512;

function bounded(text: string) {
  return text.slice(0, ERROR_TEXT_MAX_LENGTH);
}

function boundedTranscriptText(text: string) {
  return text.slice(0, TRANSCRIPT_TEXT_MAX_LENGTH);
}

function appendTranscript(snapshot: MutableSnapshot, item: TranscriptItem) {
  snapshot.transcript.push(item);
  if (snapshot.transcript.length > MAX_TRANSCRIPT_ITEMS) {
    snapshot.transcript.splice(
      0,
      snapshot.transcript.length - MAX_TRANSCRIPT_ITEMS,
    );
  }
}

// --- Internal state -----------------------------------------------------------

/** Mutable snapshot; exposed to readers via the readonly SubagentSnapshot type. */
interface MutableSnapshot {
  id: string;
  origin: SubagentOrigin;
  backend: BackendName;
  title: string;
  prompt: string;
  cwd: string;
  status: SubagentStatus;
  createdAt: number;
  settledAt?: number;
  errorText?: string;
  meta: SubagentMeta;
  usage: { tokens?: number; contextWindow?: number };
  transcript: TranscriptItem[];
  liveAssistant?: { text: string; thinking: string };
  liveTools: LiveToolState[];
  queued: SubagentSnapshot["queued"];
  finalText: string;
  turns: number;
}

interface LiveBackend {
  readonly kind: "live";
  readonly session: SubagentSession;
  readonly scope: Scope.Closeable;
}

interface DormantBackend {
  readonly kind: "dormant";
  readonly checkpoint?: SessionCheckpoint;
  /** Resume must await actual teardown, not just eviction from the registry. */
  readonly closing: Fiber.Fiber<void>;
}

interface Entry {
  snapshot: MutableSnapshot;
  readonly task: SpawnTask;
  backend: LiveBackend | DormantBackend;
  readonly commands: Semaphore.Semaphore;
  lastUsed: number;
  sending?: Fiber.Fiber<void, SendError>;
  /** Cancel invalidates sends already waiting for the command permit. */
  commandEpoch: number;
  liveToolMap: Map<string, LiveToolState>;
}

// --- Read model ----------------------------------------------------------------

/** Synchronous bridge for the TUI. Snapshots are live objects; do not mutate. */
export interface SubagentReadModel {
  list(): ReadonlyArray<SubagentSnapshot>;
  get(id: string): SubagentSnapshot | undefined;
  size(): number;
  /** Registry/status changes only (footer, dashboard); never streaming deltas. */
  subscribe(listener: () => void): () => void;
  /** All per-subagent changes, including streaming (takeover view). */
  subscribeTo(id: string, listener: () => void): () => void;
  /** Fire-and-forget: steer/continue a subagent (takeover input). */
  requestSend(id: string, text: string): void;
  /** Fire-and-forget: abort a running subagent (dashboard `x`, takeover). */
  requestAbort(id: string): void;
  /**
   * Register the settle hook. `consumed` is true when an active
   * subagent_wait/cancel is collecting the result (so it must not also be
   * delivered as a follow-up message).
   */
  setOnSettled(
    hook: ((snap: SubagentSnapshot, consumed: boolean) => void) | undefined,
  ): void;
}

// --- Service --------------------------------------------------------------------

export interface CancelResult {
  readonly id: string;
  readonly title: string;
  readonly status: SubagentStatus;
  readonly cancelled: boolean;
}

export interface SubagentManagerShape {
  spawn(
    backend: BackendName,
    task: SpawnTask,
  ): Effect.Effect<
    SubagentSnapshot,
    SpawnError | ConcurrencyLimitError | BackendUnavailableError
  >;
  /**
   * Wait until all listed subagents are settled. Unknown ids are treated as
   * settled (the tool layer validates ids first). While waiting, settles for
   * these ids are marked "consumed". Interruption (tool abort) releases the
   * interest and leaves the subagents running.
   */
  waitFor(
    ids: ReadonlyArray<string>,
    onPending?: (pending: string[]) => void,
  ): Effect.Effect<void>;
  /** Cancel running subagents; resolves when they have settled. */
  cancel(
    ids: ReadonlyArray<string>,
  ): Effect.Effect<ReadonlyArray<CancelResult>>;
  send(id: string, text: string): Effect.Effect<void, SendError>;
  get(id: string): Effect.Effect<SubagentSnapshot | undefined>;
  readonly list: Effect.Effect<ReadonlyArray<SubagentSnapshot>>;
  readonly disposeAll: Effect.Effect<void>;
  readonly view: SubagentReadModel;
}

export class SubagentManager extends Context.Service<
  SubagentManager,
  SubagentManagerShape
>()("subagents/SubagentManager") {}

// --- Implementation --------------------------------------------------------------

const makeManager = Effect.gen(function* () {
  const registry = yield* BackendRegistry;
  // Detached forker for sync contexts (read-model commands, pruning) that
  // preserves the manager's services instead of using the global runtime.
  const runDetached = Effect.runForkWith(yield* Effect.context());

  const entries = new Map<string, Entry>();
  const waitInterest = new Map<string, number>();
  const listeners = new Set<() => void>();
  /** One-shot nextChange waiters, swapped out before invocation so waiters
   * re-registering during notification are not visited in the same sweep. */
  let changeWaiters: Array<() => void> = [];
  const idListeners = new Map<string, Set<() => void>>();
  const cleanups = new Set<Fiber.Fiber<unknown>>();
  let modelCounter = 0;
  let btwCounter = 0;
  let reserved = 0;
  let useCounter = 0;
  let disposed = false;
  let onSettled:
    ((snap: SubagentSnapshot, consumed: boolean) => void) | undefined;

  const notify = (id?: string, lifecycle = true) => {
    if (lifecycle) {
      const waiters = changeWaiters;
      changeWaiters = [];
      for (const waiter of waiters) waiter();
      for (const listener of [...listeners]) {
        try {
          listener();
        } catch {
          // A failed status/render listener must not corrupt lifecycle state.
        }
      }
    }
    if (id) {
      for (const listener of idListeners.get(id) ?? []) {
        try {
          listener();
        } catch {
          // Same.
        }
      }
    }
  };

  /** Resolves on the next state change. Interruption unregisters the waiter. */
  const nextChange = Effect.callback<void>((resume) => {
    const waiter = () => resume(Effect.void);
    changeWaiters.push(waiter);
    return Effect.sync(() => {
      const index = changeWaiters.indexOf(waiter);
      if (index >= 0) changeWaiters.splice(index, 1);
    });
  });

  const runningCount = () =>
    [...entries.values()].filter(
      (e) => e.snapshot.status === "running",
    ).length;

  const addInterest = (ids: ReadonlyArray<string>) => {
    for (const id of ids) waitInterest.set(id, (waitInterest.get(id) ?? 0) + 1);
  };
  const releaseInterest = (ids: ReadonlyArray<string>) => {
    for (const id of ids) {
      const count = (waitInterest.get(id) ?? 1) - 1;
      if (count <= 0) waitInterest.delete(id);
      else waitInterest.set(id, count);
    }
  };

  const closeEntryScope = (entry: Entry) =>
    entry.backend.kind === "live"
      ? Scope.close(entry.backend.scope, Exit.void).pipe(Effect.ignore)
      : Fiber.join(entry.backend.closing);

  const trackCleanup = (effect: Effect.Effect<void>) => {
    const fiber = runDetached(effect);
    cleanups.add(fiber);
    fiber.addObserver(() => cleanups.delete(fiber));
    return fiber;
  };

  const retireBackend = (entry: Entry, live: LiveBackend, checkpoint?: SessionCheckpoint) => {
    // Detach the pump before teardown can emit terminal events. The close must
    // also run outside that pump's own finalizer (closing it there deadlocks).
    const closing = trackCleanup(Effect.yieldNow.pipe(
      Effect.andThen(Scope.close(live.scope, Exit.void)),
      Effect.ignore,
    ));
    entry.backend = { kind: "dormant", checkpoint, closing };
  };

  const checkpointOf = (live: LiveBackend) => {
    try {
      return live.session.checkpoint?.();
    } catch {
      // A persistence failure must not discard the only in-memory history.
      return undefined;
    }
  };

  const trimIdleBackends = () => {
    if (disposed) return;
    const idle = [...entries.values()]
      .filter((entry) => entry.backend.kind === "live" &&
        entry.snapshot.status !== "running" && !entry.sending)
      .sort((a, b) => a.lastUsed - b.lastUsed);
    let excess = idle.length - MAX_IDLE_BACKENDS;
    for (const entry of idle) {
      if (excess <= 0) break;
      const live = entry.backend;
      if (live.kind !== "live" || !registry.get(entry.snapshot.backend)?.resume) continue;
      const checkpoint = checkpointOf(live);
      // A failed/pre-init session may not have native persistence yet. Keeping
      // it hot is safer than discarding its only history to satisfy the cache cap.
      if (!checkpoint) continue;
      retireBackend(entry, live, checkpoint);
      excess--;
    }
  };

  // Let the native producer finish its settlement/queued-turn transition first.
  let trimScheduled = false;
  const scheduleTrim = () => {
    if (trimScheduled || disposed) return;
    trimScheduled = true;
    queueMicrotask(() => {
      trimScheduled = false;
      trimIdleBackends();
    });
  };

  const pruneSettled = () => {
    if (entries.size <= MAX_TRACKED) return;
    const candidates = [...entries.values()]
      .filter(
        (e) =>
          e.snapshot.status !== "running" && !e.sending &&
          !waitInterest.has(e.snapshot.id),
      )
      .sort(
        (a, b) =>
          (a.snapshot.settledAt ?? a.snapshot.createdAt) -
          (b.snapshot.settledAt ?? b.snapshot.createdAt),
      );
    for (const entry of candidates) {
      if (entries.size <= MAX_TRACKED) break;
      entries.delete(entry.snapshot.id);
      trackCleanup(closeEntryScope(entry));
    }
  };

  const settle = (entry: Entry, outcome: RunOutcome) => {
    const s = entry.snapshot;
    if (s.status !== "running") return;
    s.settledAt = Date.now();
    entry.lastUsed = ++useCounter;
    switch (outcome._tag) {
      case "Completed":
        s.status = "done";
        s.errorText = undefined;
        s.finalText = outcome.finalText.slice(0, FINAL_TEXT_MAX_LENGTH);
        break;
      case "Failed":
        s.status = "error";
        s.errorText = bounded(outcome.errorText);
        // Never let a failed run report the previous run's successful output.
        s.finalText = (outcome.partialText ?? "").slice(
          0,
          FINAL_TEXT_MAX_LENGTH,
        );
        break;
      case "Interrupted":
        s.status = "error";
        s.errorText = "Run was aborted";
        s.finalText = (outcome.partialText ?? "").slice(
          0,
          FINAL_TEXT_MAX_LENGTH,
        );
        break;
    }
    s.liveAssistant = undefined;
    entry.liveToolMap.clear();
    s.liveTools = [];
    s.queued = [];
    const consumed = (waitInterest.get(s.id) ?? 0) > 0;
    notify(s.id);
    try {
      // During teardown, don't queue results into a shutting-down session.
      if (!disposed) onSettled?.(s, consumed);
    } catch {
      // The parent session may be unavailable; settlement stays final.
    }
    pruneSettled();
    scheduleTrim();
  };

  const foldEvent = (entry: Entry, event: SubagentEvent) => {
    const s = entry.snapshot;
    const previousStatus = s.status;
    switch (event._tag) {
      case "RunStarted":
        s.status = "running";
        s.settledAt = undefined;
        s.errorText = undefined;
        break;
      case "RunSettled":
        settle(entry, event.outcome);
        return; // settle() already notified
      case "UserMessage":
        appendTranscript(s, {
          kind: "user",
          text: boundedTranscriptText(event.text),
        });
        break;
      case "AssistantDelta": {
        const live = s.liveAssistant ?? { text: "", thinking: "" };
        s.liveAssistant =
          event.kind === "text"
            ? {
                ...live,
                text: (live.text + event.delta).slice(
                  -LIVE_ASSISTANT_MAX_LENGTH,
                ),
              }
            : {
                ...live,
                thinking: (live.thinking + event.delta).slice(
                  -LIVE_ASSISTANT_MAX_LENGTH,
                ),
              };
        break;
      }
      case "AssistantMessage":
        appendTranscript(s, {
          kind: "assistant",
          parts: event.parts.map((part) =>
            part.type === "toolCall"
              ? {
                  ...part,
                  argsPreview: part.argsPreview
                    ? boundedTranscriptText(part.argsPreview)
                    : undefined,
                }
              : { ...part, text: boundedTranscriptText(part.text) },
          ),
        });
        s.liveAssistant = undefined;
        s.turns++;
        break;
      case "ToolStart":
        entry.liveToolMap.set(event.toolId, {
          toolId: event.toolId,
          name: event.name,
          argsPreview: event.argsPreview
            ? boundedTranscriptText(event.argsPreview)
            : undefined,
        });
        s.liveTools = [...entry.liveToolMap.values()];
        break;
      case "ToolUpdate": {
        const current = entry.liveToolMap.get(event.toolId);
        if (current) {
          entry.liveToolMap.set(event.toolId, {
            ...current,
            outputPreview: event.outputPreview
              ? boundedTranscriptText(event.outputPreview)
              : current.outputPreview,
          });
          s.liveTools = [...entry.liveToolMap.values()];
        }
        break;
      }
      case "ToolEnd":
        entry.liveToolMap.delete(event.toolId);
        s.liveTools = [...entry.liveToolMap.values()];
        appendTranscript(s, {
          kind: "toolResult",
          toolId: event.toolId,
          name: event.name,
          isError: event.isError,
          outputPreview: event.outputPreview
            ? boundedTranscriptText(event.outputPreview)
            : undefined,
        });
        break;
      case "QueueChanged":
        s.queued = event.queued;
        break;
      case "UsageChanged":
        s.usage = {
          tokens: event.tokens ?? s.usage.tokens,
          contextWindow: event.contextWindow ?? s.usage.contextWindow,
        };
        break;
      case "MetaChanged":
        s.meta = { ...s.meta, ...event.meta };
        break;
      case "BackendError":
        s.errorText = bounded(event.message);
        break;
    }
    notify(s.id, s.status !== previousStatus);
  };

  const attachPump = (entry: Entry, live: LiveBackend) => {
    const pump = Stream.runForEach(live.session.events, (event) =>
      Effect.sync(() => {
        if (entry.backend === live) foldEvent(entry, event);
      }),
    ).pipe(
      Effect.ensuring(Effect.sync(() => {
        if (entry.backend !== live) return;
        if (entry.snapshot.status === "running") {
          settle(entry, {
            _tag: "Failed",
            errorText: "Backend event stream ended unexpectedly",
          });
        }
        // Dead transports are never reusable, even below the idle cache cap.
        if (!disposed) retireBackend(entry, live, checkpointOf(live));
      })),
    );
    return Scope.provide(Effect.forkScoped(pump), live.scope);
  };

  const spawn = (backendName: BackendName, task: SpawnTask) =>
    Effect.gen(function* () {
      // Reserve synchronously (before the first yield inside doSpawn) so
      // parallel tool calls cannot race past the global cap.
      yield* Effect.suspend(
        (): Effect.Effect<void, SpawnError | ConcurrencyLimitError> => {
          if (disposed) {
            return new SpawnError({
              message: "Subagent manager is shutting down.",
            });
          }
          if (runningCount() + reserved >= MAX_RUNNING) {
            return new ConcurrencyLimitError({
              message: `Max ${MAX_RUNNING} subagents can run concurrently. Wait for one to finish before spawning another.`,
            });
          }
          reserved++;
          return Effect.void;
        },
      );

      const doSpawn = Effect.gen(function* () {
        const backend: SubagentBackend | undefined = registry.get(backendName);
        if (!backend) {
          return yield* new BackendUnavailableError({
            message: `Unknown backend "${backendName}".`,
          });
        }
        const available = yield* backend.available;
        if (!available) {
          return yield* new BackendUnavailableError({
            message: `Backend "${backendName}" is not available on this machine (binary/SDK/credentials missing).`,
          });
        }

        const scope = yield* Scope.make();
        const session = yield* Scope.provide(backend.spawn(task), scope).pipe(
          Effect.onError(() => Scope.close(scope, Exit.void)),
        );
        if (disposed) {
          yield* Scope.close(scope, Exit.void);
          return yield* new SpawnError({
            message: "Subagent manager shut down while spawning.",
          });
        }

        const origin = task.origin ?? "model";
        const id =
          origin === "btw" ? `btw-${++btwCounter}` : `sa-${++modelCounter}`;
        const meta = yield* session.meta;
        const entry: Entry = {
          snapshot: {
            id,
            origin,
            backend: backendName,
            title: task.title,
            prompt: task.prompt,
            cwd: task.cwd,
            status: "running",
            createdAt: Date.now(),
            meta,
            usage: { contextWindow: meta.contextWindow },
            transcript: [],
            liveTools: [],
            queued: [],
            finalText: "",
            turns: 0,
          },
          task,
          backend: { kind: "live", session, scope },
          commands: Semaphore.makeUnsafe(1),
          lastUsed: ++useCounter,
          commandEpoch: 0,
          liveToolMap: new Map(),
        };
        entries.set(id, entry);

        if (entry.backend.kind === "live") yield* attachPump(entry, entry.backend);

        notify(id);
        return entry.snapshot as SubagentSnapshot;
      });

      return yield* doSpawn.pipe(
        Effect.ensuring(
          Effect.sync(() => {
            reserved--;
          }),
        ),
      );
    });

  const waitFor = (
    ids: ReadonlyArray<string>,
    onPending?: (pending: string[]) => void,
  ) =>
    Effect.suspend(() => {
      const unique = [...new Set(ids)];
      addInterest(unique);
      const loop = Effect.gen(function* () {
        let previousPending: string[] | undefined;
        while (true) {
          const pending = unique.filter(
            (id) => entries.get(id)?.snapshot.status === "running",
          );
          if (pending.length === 0) return;
          if (!previousPending || pending.length !== previousPending.length ||
              pending.some((id, index) => id !== previousPending?.[index])) {
            onPending?.(pending);
            previousPending = pending;
          }
          yield* nextChange;
        }
      });
      return loop.pipe(
        Effect.ensuring(
          Effect.sync(() => {
            releaseInterest(unique);
            pruneSettled();
          }),
        ),
      );
    });

  /** Interrupt one running entry, force-closing its scope after 5s. */
  const abortEntry = (entry: Entry) =>
    Effect.gen(function* () {
      entry.commandEpoch++;
      if (entry.sending) yield* Fiber.interrupt(entry.sending);
      yield* abortLocked(entry);
    });

  const abortLocked = (entry: Entry) =>
    Effect.gen(function* () {
      if (entry.snapshot.status !== "running") return;
      if (entry.backend.kind !== "live") {
        settle(entry, { _tag: "Interrupted" });
        return;
      }
      const graceful = yield* entry.backend.session.interrupt.pipe(
        Effect.timeout(STOP_TIMEOUT_MS),
        Effect.result,
      );
      if (Result.isFailure(graceful)) {
        // Settle before closing the scope so the pump's stream-ended
        // fallback ("Backend event stream ended unexpectedly") cannot win
        // the race and report the wrong terminal reason.
        yield* Effect.sync(() => {
          settle(entry, { _tag: "Interrupted" });
          entry.snapshot.errorText =
            "Abort deadline exceeded; session was force-disposed";
          notify(entry.snapshot.id);
        });
        // Bound the close like disposeAll does: a stuck backend finalizer
        // must not hang cancel after the run is already settled.
        yield* closeEntryScope(entry).pipe(
          Effect.timeout(STOP_TIMEOUT_MS),
          Effect.ignore,
        );
      }
    }).pipe(entry.commands.withPermit);

  const cancel = (ids: ReadonlyArray<string>) =>
    Effect.suspend(() => {
      const unique = [...new Set(ids)];
      const running = unique
        .map((id) => entries.get(id))
        .filter(
          (entry): entry is Entry => entry?.snapshot.status === "running",
        );
      const runningIds = running.map((entry) => entry.snapshot.id);
      // Mark consumed before interrupting so cancellation does not also
      // enqueue duplicate automatic result messages into the parent.
      addInterest(runningIds);
      const work = Effect.gen(function* () {
        yield* Effect.forEach(running, abortEntry, {
          concurrency: "unbounded",
        });
        while (running.some((entry) => entry.snapshot.status === "running")) {
          yield* nextChange;
        }
      });
      return work.pipe(
        Effect.ensuring(
          Effect.sync(() => {
            releaseInterest(runningIds);
            pruneSettled();
          }),
        ),
        Effect.map((): ReadonlyArray<CancelResult> =>
          unique.map((id) => {
            const snapshot = entries.get(id)?.snapshot;
            return {
              id,
              title: snapshot?.title ?? "?",
              status: snapshot?.status ?? "error",
              cancelled: runningIds.includes(id),
            };
          }),
        ),
      );
    });

  const reopen = (entry: Entry, dormant: DormantBackend) =>
    Effect.gen(function* () {
      // Never reopen a native session while its previous owner can still write.
      yield* Fiber.join(dormant.closing).pipe(
        Effect.timeout(STOP_TIMEOUT_MS),
        Effect.mapError(() => new SendError({ message: "Previous backend is still closing; retry later." })),
      );
      const backend = registry.get(entry.snapshot.backend);
      if (!backend?.resume || !dormant.checkpoint) {
        return yield* new SendError({ message: "Backend has no durable session to resume." });
      }
      const resume = backend.resume;
      const checkpoint = dormant.checkpoint;
      // Acquisition is interruptible; ownership transfer to Entry is not.
      // No successfully opened scope may fall between these two owners.
      yield* Effect.uninterruptibleMask((restore) => Effect.gen(function* () {
        const scope = yield* Scope.make();
        yield* Effect.gen(function* () {
          const session = yield* restore(Scope.provide(resume(entry.task, checkpoint), scope));
          if (disposed || entries.get(entry.snapshot.id) !== entry) {
            return yield* new SpawnError({ message: "Subagent manager is shutting down." });
          }
          const live: LiveBackend = { kind: "live", session, scope };
          entry.backend = live;
          yield* attachPump(entry, live);
        }).pipe(
          Effect.onError(() => Scope.close(scope, Exit.void)),
          Effect.mapError((error) => new SendError({ message: error.message })),
        );
      }));
    });

  const send = (id: string, text: string) =>
    Effect.suspend((): Effect.Effect<void, SendError> => {
      const entry = entries.get(id);
      if (!entry || disposed) {
        return new SendError({ message: `Subagent "${id}" is no longer tracked.` });
      }
      const epoch = entry.commandEpoch;
      return Effect.gen(function* () {
        // Recheck under the permit: another command may have settled, failed,
        // been cancelled, or been pruned while this send was waiting.
        if (disposed || entries.get(id) !== entry) {
          return yield* new SendError({ message: `Subagent "${id}" is no longer tracked.` });
        }
        if (epoch !== entry.commandEpoch) {
          return yield* new SendError({ message: "Send was cancelled." });
        }
        const restarting = entry.snapshot.status !== "running";
        if (restarting) {
          if (runningCount() + reserved >= MAX_RUNNING) {
            return yield* new SendError({
              message: `Max ${MAX_RUNNING} subagents can run concurrently; restarting "${id}" would exceed that.`,
            });
          }
          // Reserve before opening: wait/cancel and concurrent spawns see busy.
          entry.snapshot.status = "running";
          entry.snapshot.settledAt = undefined;
          entry.snapshot.errorText = undefined;
          notify(id);
        }
        entry.lastUsed = ++useCounter;
        const dispatch = Effect.gen(function* () {
          if (entry.backend.kind === "dormant") yield* reopen(entry, entry.backend);
          const live = entry.backend;
          if (live.kind !== "live") {
            return yield* new SendError({ message: "Backend ended while resuming." });
          }
          yield* live.session.send(text);
        }).pipe(
          Effect.catch((error) => {
            if (restarting) settle(entry, {
              _tag: "Failed",
              errorText: `Could not continue subagent: ${error.message}`,
            });
            return Effect.fail(error);
          }),
          Effect.onInterrupt(() => Effect.sync(() => {
            if (restarting) settle(entry, { _tag: "Interrupted" });
          })),
        );
        const sending = yield* Effect.forkChild(dispatch);
        entry.sending = sending;
        yield* Fiber.join(sending).pipe(Effect.ensuring(Effect.sync(() => {
          entry.sending = undefined;
          pruneSettled();
          scheduleTrim();
        })));
      }).pipe(entry.commands.withPermit);
    });

  const disposeAll = Effect.gen(function* () {
    disposed = true;
    const all = [...entries.values()];
    entries.clear();
    yield* Effect.forEach(all, (entry) => entry.sending
      ? Fiber.interrupt(entry.sending) : Effect.void, { concurrency: "unbounded" });
    yield* Effect.forEach(
      all,
      (entry) =>
        closeEntryScope(entry).pipe(
          Effect.timeout(STOP_TIMEOUT_MS),
          Effect.ignore,
        ),
      { concurrency: "unbounded" },
    );
    // Pruning cleanups are detached; bound them like everything else so a
    // stuck backend finalizer cannot block runtime shutdown indefinitely.
    yield* Effect.forEach(
      [...cleanups],
      (fiber) =>
        Fiber.await(fiber).pipe(Effect.timeout(STOP_TIMEOUT_MS), Effect.ignore),
      { concurrency: "unbounded" },
    ).pipe(Effect.ignore);
    yield* Effect.sync(() => notify());
  });

  const view: SubagentReadModel = {
    list: () => [...entries.values()].map((entry) => entry.snapshot),
    get: (id) => entries.get(id)?.snapshot,
    size: () => entries.size,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    subscribeTo: (id, listener) => {
      const entry = entries.get(id);
      if (entry) entry.lastUsed = ++useCounter;
      let set = idListeners.get(id);
      if (!set) {
        set = new Set();
        idListeners.set(id, set);
      }
      set.add(listener);
      return () => {
        set.delete(listener);
        if (set.size === 0) idListeners.delete(id);
      };
    },
    requestSend: (id, text) => {
      runDetached(send(id, text).pipe(Effect.catch((error) => Effect.sync(() => {
        const entry = entries.get(id);
        if (entry) {
          entry.snapshot.errorText = bounded(error.message);
          notify(id, false);
        }
      }))));
    },
    requestAbort: (id) => {
      const entry = entries.get(id);
      if (!entry) return;
      // UI-initiated aborts are not "consumed": the failed result still
      // flows back to the parent as a follow-up message, matching v1.
      runDetached(abortEntry(entry).pipe(Effect.ignore));
    },
    setOnSettled: (hook) => {
      onSettled = hook;
    },
  };

  // Safety net: disposing the ManagedRuntime tears everything down even if
  // the extension forgot to call disposeAll explicitly.
  yield* Effect.addFinalizer(() => disposeAll);

  return SubagentManager.of({
    spawn,
    waitFor,
    cancel,
    send,
    get: (id) => Effect.sync(() => entries.get(id)?.snapshot),
    list: Effect.sync(() => [...entries.values()].map((e) => e.snapshot)),
    disposeAll,
    view,
  });
});

export const SubagentManagerLive: Layer.Layer<
  SubagentManager,
  never,
  BackendRegistry
> = Layer.effect(SubagentManager, makeManager);
