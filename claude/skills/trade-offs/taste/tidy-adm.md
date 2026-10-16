# tidy-adm taste

Снято: 2026-10-16, `73fffe7` (master). Дополняет `docs/agent/CODING_STANDARDS.md` и
`docs/agent/coding-standards/tidy-adm.md`, не повторяет их. Своих AGENTS.md/CLAUDE.md и тестов нет.
Сила: [П] явное правило, [У] устойчивый паттерн, [С] слабая тенденция.

## Устойчиво, не задокументировано
- [П] Форма - явная state machine, а не набор флагов (правило); в свежем коде
  `EDrawerState { Idle, Loading, Saving, Error, Success }` (`AutoChatCreationDrawerStore.ts`).
- [У] Интерфейс store объявлен в том же файле, что и store (в отличие от `ifaces/` в tidy-client).
- [У] Доступ к stores: `useContext(RootStoreCtx)`.
- [У] Справочники держит CatalogStore; `find`/`findIndex` проверяют до мутации (правило).
- [У] Цвет из `theme.palette.primaryColors?.*`; новые правки стилизуют через `sx`.
- [У] `makeStyles(() => createStyles({...}))` - форма всех существующих вызовов `makeStyles`.
- [У] Новые проверки данных Space - через type guards (`isSpaceObjectClass`).

## Legacy и новый код
- MobX смешан даже в одном файле: декораторы `@observable`/`@action.bound`, `makeAutoObservable`,
  `makeObservable` на каждое поле. Единого стандарта нет, и правило запрещает вводить его попутно:
  следуй стилю конкретного файла.
- Стили: legacy `makeStyles` из `@material-ui/styles` соседствует с `sx`; старое не мигрируют.
- `any` встречается часто (около 137 `: any`); в новом коде его убирают, когда тип выводится.
