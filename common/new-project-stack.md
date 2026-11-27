# New Project Stack Defaults

Дефолтные предпочтения при выборе стека, проектировании или создании **новых** проектов, утилит, скриптов и CLI с нуля (не применять к существующим репозиториям, где стек уже задан).

- **Языки**: TypeScript 7 (`strict`, ESM) - основной; Python 3 (stdlib) для скриптов и автоматизации; Go (stdlib) для простых нативных CLI/хуков.
- **Веб**: Astro (+ React только для островов) для статики; Vite + React 19 для SPA и веб-инструментов (без Next.js, если не нужен SSR).
- **UI и стейт**: Tailwind CSS, shadcn/ui + Radix UI, Lucide, локальные шрифты (`@fontsource`), Zustand, TanStack Query, Zod/TypeBox.
- **Бэкенд и рантайм**: Node.js 24+ (нативный запуск TS), Hono + `ws` для лёгких API/демонов.
- **Тулинг**: pnpm или Bun (+ Turborepo для монореп), Oxlint + Oxfmt (вместо ESLint/Prettier), Vitest, Conventional Commits.
- **Фокус**: минимум лишних зависимостей, производительность, аккуратная типографика.
