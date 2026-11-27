# tidy-client taste

Снято: 2026-10-16, `53da36000` (master). Дополняет `docs/agent/CODING_STANDARDS.md` и
`docs/agent/coding-standards/tidy-client.md`, не повторяет их.
Сила: [П] явное правило, [У] устойчивый паттерн, [С] слабая тенденция.

## Устойчиво, не задокументировано
- [У] Состояние запроса в store: флаги `is*` + `error: string | null`
  (`ClientNameStore.ts`, `RequestChatOnboardingStore.ts`). Union или enum - для статусов очередей
  и локального UI (`MessageSendJobStatus` с дискриминатором `kind`, `'idle' | 'loading' | 'done'`).
- [С] Computed-геттеры редки (около 10 против 267 `set*`): только для производных прав
  и видимости (`canUseFeature`, `isNameChangeRequired`).
- [У] MobX: чаще `makeObservable` с явной картой; новые stores бывают на
  `makeAutoObservable(this, {}, { autoBind: true })`. Async-мутации через `runInAction`, `flow` нет.
- [У] Служебные поля store - `private`, не `#`. Публичная поверхность = `I*Store` в `stores/ifaces/`.
- [У] Устаревшие ответы отсекают счётчиком поколений (`loadRequestId`, `listFetchGeneration`),
  последовательность - очередью на promise (`countersRefreshQueue`), не AbortController.
- [У] Null-object вместо `undefined`: `findById` возвращает `initChatValue`, проверка по `!chat.id`.
- [У] Enum с префиксом `E` в `src/client/utils/enums/` или рядом с контрактом в `ifaces/`;
  `type` для данных, `interface` для контрактов stores.
- [У] Ответ протокола сужают проверкой `type`/`typeof` и `throw`; ESLint при этом разрешает `any`.
- [У] Магические значения - `UPPER_CASE`-константы, экспортируемые для тестов (`SYNC_INDICATOR_DELAY_MS`).
- [У] Store бросает `Error` или возвращает `boolean`; компонент показывает `pushSnack(..., { variant: 'error' })`.
  Тексты ошибок для пользователя формирует store, по-русски.
- [У] Стили через `sx` и токены темы (`echatGray.*`, `echatPrimary.*`); `makeStyles` нет.
- [У] Тесты: unit store через фабрику `createStore` и фейковый rootStore; гонки - `deferred<T>()`
  и fake timers. Фикс приходит с тестом на гонку, повтор или unmount.

## Legacy и новый код
- `MessagesNew.ts` - текущий store сообщений, `Messages.ts` - legacy.
- `ChatList.ts` и `MessagesNew.ts` монолитные; новую логику выносят в координаторы
  с колбэками в options (`StreamRecoveryCoordinator`).
- `any` в legacy (`audioPlayer.ts`); новый код сужает типы явно и через type guards.
