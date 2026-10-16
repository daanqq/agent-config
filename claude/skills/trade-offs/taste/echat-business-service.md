# echat.business.service taste

`~/deploy/env/development/services/echat.business.service`. Снято: 2026-10-16, `56592ab`.
Документировано: только `.eslintrc.json` -> `@ecosystem/eslint-config/service` (ESLint 7). README пуст.
Сила: [П] явное правило, [У] устойчивый паттерн, [С] слабая тенденция.

## Устойчиво, не задокументировано
- [У] Слои: `index.js` (подписки на события) -> `controllers/*` (только деструктуризация и проброс) ->
  `service/<domain>/<method>.js` (один файл на метод + `index.js`) -> `api/restEchat.js` (класс над axios).
- [У] Валидация в OpenAPI (`spec/methods/**/*.yml`, типы `shared://`, описания по-русски);
  в коде только точечные `throw new RuntimeError('Invalid input...')`.
- [У] Любое изменение API повышает `version` в `spec/root.yml`.
- [У] Ошибки: `try/catch (err)` и `throw new RuntimeError(\`... ${toStr(err.response?.data?.message || err)}\`)`;
  успех - `logger.info`. Частичные данные - обёртка `resolveRequest` с `logger.error`.
- [У] Долгие операции не ждут: результат уходит фронту через
  `ext.events.sendToFrontend(..., EventModes.QUEUE)`.
- [У] CommonJS, async-стрелки, условные поля через `...cond && {...}`, параллельно - `Promise.all`.
- [С] `catch(err)` без пробела (ESLint 7), в отличие от frontend.
