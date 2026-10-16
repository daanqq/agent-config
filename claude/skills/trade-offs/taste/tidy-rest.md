# tidy-rest taste

Снято: 2026-10-16, `ad1b4d96` (master). Дополняет `docs/agent/CODING_STANDARDS.md`,
`docs/agent/coding-standards/tidy-rest.md` и `tidy-rest/CLAUDE.md`, не повторяет их.
Сила: [П] явное правило, [У] устойчивый паттерн, [С] слабая тенденция.

## Устойчиво, не задокументировано
- [У] Набор признаков - битовые флаги в числовом enum (`ChatFlag = 1 << n`,
  `src/chats/Enums.ts`) и хелперы `hasFlag/addFlag/removeFlag` (`src/utils/utils.ts`),
  а не отдельные boolean-поля. Новый признак - следующий бит.
- [У] Числовые enum (около 134); строковые literal union редки.
- [С] Смысл кодируют диапазоном чисел (`GLOBAL_APP_SETTING_ID_START` = 128),
  настройки - позиционным кортежем `[id, type, value]`.
- [У] Совместимость - дефолтом на чтении (`row('flags').default(0)`, `updatedAt.default(createdAt)`),
  а не миграцией.
- [У] «Нет данных» - `[]`/`null`; нарушение прав - `ErrorResponse(errors.<domain>.<name>, 403)`.
  Коды в словаре `src/utils/Error.ts`.
- [У] Сервисы создаются фабриками (`chatServiceFactory()`), без DI-контейнера.
- [У] Почти везде `type`, не `interface` (в свежих диффах 58 против 1).
- [У] Нестрогий TS: `strictNullChecks` выключен, `any` разрешён, но в новом коде почти не пишется;
  `as X` встречается часто.
- [У] Опциональные поля внешних DTO расширяют честно (`status?`, `| null`), не подменяют дефолтами.
- [У] Guard-цепочка ранних return, затем `const` и тернарник; `let` с последующим `if` заметно реже
  (39 против 693 добавленных строк). Внутри блока, где соседи на `let` + `if`, держи их форму.
- [У] Конкурентность: условный update (`filter(...).update`, `replaced > 0`) и детерминированный id
  с `insert(..., { conflict: 'update' })`, а не распределённые блокировки.
- [У] Комментарии и JSDoc по-русски, объясняют причину. Коммиты по-английски с номером задачи.
- [С] Упрощение API предпочитают наращиванию (пагинация с continuation заменена лимитом 300).

## Legacy и новый код
- Новый домен уходит в `src/<domain>/` service; legacy `src/controllers/*` всё ещё расширяют
  на месте прямыми запросами RethinkDB.
- Сообщения: новый слой `*Repository` / `*Dual` / `*PG` / `*RDB` с `ReadRouter` и `dualWrite`;
  при правке проверяй обе реализации. Legacy - Model/Collection только для RethinkDB.
- `TjsMapper`: строковые `case 'e_message_new'` и `TJSPack<any>` - legacy, новый код на enum.
