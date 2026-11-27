# tidy-server taste

Снято: 2026-10-16, `1674e35` (master). Дополняет `docs/agent/CODING_STANDARDS.md`,
`docs/agent/coding-standards/tidy-server.md`, `tidy-proto.md` и `tidy-server/AGENTS.md`.
Сила: [П] явное правило, [У] устойчивый паттерн, [С] слабая тенденция.

## Устойчиво, не задокументировано
- [У] Pattern matching в заголовках функций и `case`; `if` почти нет (523 `case`).
  Хелперы: `map_x(#{...}) -> ...; map_x(_) -> Default.`
- [У] Records для протокола и state gen_server; maps только для JSON из REST,
  чтение через `maps:get(Key, Map, Default)`.
- [У] Boolean на проводе - integer 0/1, отсутствие - `void` (`tidy_data_util:bool_to_int/int_to_bool`).
- [У] Совместимость с REST - дефолтом на чтении с комментарием о причине
  (`maps:get(<<"isReceiptChanged">>, Item, true)` «Старый REST не передаёт флаг»).
- [У] Мусорный вход нормализует узкий хелпер с catch-all клаузой (`normalize_user_flags/1`)
  и тестом на absent/null/int; хелпер, падающий с `function_clause` на не-boolean, заменяют `case`.
- [У] Ответ manager-а: `{ok, Rec} | {error, get_error_msg(HxErr)}`; `try` редок.
- [У] Новая команда меняет в одном коммите: `hrl`, `check_code`, `to_print_code`,
  `decode`/`list_to_rec`, `process` + `_process`, manager и тест.
- [У] EUnit: roundtrip `encode -> tuple -> decode` с `?assertMatch` на конкретный кортеж;
  удаление хвостового поля сопровождают тестом декодирования legacy-кортежа.
- [С] Устаревший код: `@deprecated` и `TODO: [EUTP-...]` с перечнем того, что удалить.

## Legacy и новый код
- Поля records в snake_case; camelCase (`dontNotify`) - отклонение, не норма.
