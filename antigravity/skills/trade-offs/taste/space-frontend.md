# Space frontend taste

`~/deploy/env/development/services/frontend`. Снято: 2026-10-16, `a94ea900e5f`.
Документировано: `src/stores/README.md` (пример устарел), `src/utils/README.md`,
`eslint.config.mjs` -> `@ecosystem/eslint-config/react`. AGENTS.md/CLAUDE.md нет. JS без TS и тестов.
Сила: [П] явное правило, [У] устойчивый паттерн, [С] слабая тенденция.

## Правила ESLint, влияющие на дизайн
- [П] Нет вложенных тернарников; `curly: all`; `no-else-return`; пустая строка перед `return`.
- [П] `id-denylist`: нельзя `e`, `data`, `value`, `date`, `items`; `catch (_)` для неиспользуемой ошибки.
- [П] `max-len 100`, `max-lines 1100`, `max-nested-callbacks 3`.
- [П] Базовые компоненты из `@ecosystem/uikit-base`, хуки из `@ecosystem/uikit-hooks`.
- [П] Линт веток проверяет только изменённые строки: legacy правят постепенно.

## Устойчиво, не задокументировано
- [У] `makeObservable(this, {...})` с явной картой (201 из 240 новых классов); декораторы - legacy.
- [У] Async-стрелки и отдельный сеттер-action на каждое изменение; `flow` нет, `runInAction` редок.
- [У] Загрузка - `DataLoadingState` или enum `loadingStatus`, не флаг `isLoading`.
- [У] Набор значений - объект-константа + config-map (`HOTNESS_LEVEL`/`HOTNESS_CONFIG`),
  доменные enum из `@ecosystem/enums`, множества через `new Set`.
- [У] Stores создаются на странице; дочерние - `new` внутри родителя; синглтоны только у
  `RouterStore` и `PluginsStore`. Зависимости через конструктор.
- [У] Флаги фич синхронизируют через `reaction(..., { fireImmediately: true })` или `await when(...)`
  в именованном методе.
- [У] Guard-clauses; сложные условия - именованные `isX`/`hasX`. Хелперы в `utils.js`/`consts.js`
  рядом со store, `fp.*` и `hasValue` из `@ecosystem/esoft-tools-shared`.
- [У] «Приватные» члены с префиксом `_`, исключены из observable.
- [У] Запрос в `try/catch (_)` с `notify({ variant: 'error', message: 'l10n(...)' })`; побочные загрузки
  без `await`, ошибки ловятся внутри; для необязательных данных - тихий fallback.
- [У] Компонент: `magic(View, { store: mapStore, styles: s })`; порядок View, `mapStore`, `propTypes`, export.
- [У] Пользовательские строки - `'l10n(...)'`. Комментарии по-русски, редкие, о причине.

## Legacy и новый код
- `EChat/index.js` (около 1560 строк, около 20 булевых флагов, `makeAutoObservable`) - legacy,
  не образец.
- `@sharedHooks`/`@sharedComponents` при правке заменяют на `@ecosystem/uikit-*`.
