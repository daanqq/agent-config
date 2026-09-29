# TypeScript patterns

## Discriminated state

Use one literal field so contradictory states cannot coexist.

```ts
type DiffState =
  | { kind: "loading" }
  | { kind: "ready"; diff: GitDiff }
  | { kind: "error"; error: string };
```

Prefer this over `{ loading: boolean; diff?: GitDiff; error?: string }` when the combinations have different invariants.

## Non-empty collections

Strengthen a collection only where empty would make the operation partial.

```ts
type NonEmpty<T> = [T, ...T[]];

function newestSession(sessions: NonEmpty<Session>): Session {
  return sessions[0];
}

function isNonEmpty<T>(items: T[]): items is NonEmpty<T> {
  return items.length > 0;
}
```

Keep `T[]` when empty has a valid meaning, such as a sum whose identity is zero.

## Branded primitives

Brand a primitive when two values have the same runtime representation but different semantics and are realistically mixed up.

```ts
declare const agentIdBrand: unique symbol;
type AgentId = string & { readonly [agentIdBrand]: true };

function parseAgentId(input: string): AgentId {
  if (!isUuid(input)) throw new Error("invalid agent id");
  return input as AgentId;
}
```

The cast is local to the validating constructor. Downstream code trusts `AgentId`. Do not brand every string or number by reflex.

## External data as `unknown`

```ts
function parseUser(input: unknown): User {
  if (typeof input !== "object" || input === null) {
    throw new Error("expected user object");
  }

  const value = input as Record<string, unknown>;
  if (typeof value.id !== "string" || typeof value.name !== "string") {
    throw new Error("invalid user fields");
  }

  return { id: value.id, name: value.name };
}
```

Prefer a repository schema validator when one is already installed. The small structural cast above only enables property inspection; the returned domain value is constructed from validated fields.

## Honest type guards

```ts
function isCircle(shape: Shape): shape is Circle {
  return shape.kind === "circle";
}
```

A guard must check every fact its return type claims. Prefer direct discriminant narrowing when the guard adds no reusable meaning.

## Exhaustive variants

```ts
function area(shape: Shape): number {
  switch (shape.kind) {
    case "circle":
      return Math.PI * shape.radius ** 2;
    case "rectangle":
      return shape.width * shape.height;
    default: {
      const exhaustive: never = shape;
      return exhaustive;
    }
  }
}
```

Use the repository's existing exhaustive helper if it has one.

## `satisfies` without widening

```ts
const config = {
  theme: "dark",
  columns: 3,
} satisfies AppConfig;
```

The compiler checks `AppConfig`, while `config.theme` remains the literal `"dark"`.

## Schema-derived shapes

```ts
import type { ChecksMessage } from "./generated/checks";

type CheckSummary = Pick<ChecksMessage, "totalCount" | "checks">;
```

Derivation keeps the local type tied to the authoritative generated contract. Declare a separate domain type when the domain intentionally differs from the transport shape.

## Object parameters

```ts
function openFile(options: {
  uri: string;
  selection?: Selection;
  preview?: boolean;
}): void {
  // ...
}
```

Object parameters are most useful when values share types, options are optional, or call sites otherwise need comments to explain argument order.

## Boundary adapter

```ts
type CreateUser = {
  id: UserId;
  displayName: string;
};

function parseCreateUserRequest(body: unknown): CreateUser {
  const request = createUserSchema.parse(body);
  return {
    id: parseUserId(request.id),
    displayName: request.displayName,
  };
}

function createUser(command: CreateUser): User {
  // Internal logic receives a trusted domain value.
}
```

Transport validation and domain construction happen once. Internal functions do not repeatedly inspect the original wire shape.
