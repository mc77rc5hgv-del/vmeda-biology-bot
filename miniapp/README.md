# VMEDA Mini App — Этап 2 (дизайн-прототип)

React + TypeScript + Vite. Работает **полностью на тестовых данных** (`src/lib/mockData.ts`) —
никакого backend/API/реальных пользовательских данных здесь нет. См. ТЗ, раздел 21 «Этап 2».

## Запуск

```bash
npm install
npm run dev       # локальная разработка, http://localhost:5173
npm run build     # production-сборка в dist/
npm run preview   # предпросмотр production-сборки
npm run lint      # oxlint
```

Внутри Telegram — откройте `dev`/`preview` URL через `@BotFather` → `/setmenubutton` на тестовом
боте (или ngrok-туннель для локальной разработки); вне Telegram (обычный браузер) приложение
тоже работает — `src/lib/telegram.ts` безопасно деградирует, когда `window.Telegram` не найден.

## Структура

```
src/
├── styles/       — design tokens (tokens.css) и глобальные стили
├── lib/
│   ├── telegram.ts   — обёртка над window.Telegram.WebApp (тема, back-button, haptics)
│   ├── types.ts       — контентный контракт (§14 ТЗ) + модели прогресса/доступа (§13, §16)
│   ├── mockData.ts    — тестовые данные Этапа 2 (список предметов — РЕАЛЬНЫЙ, из аудита бота)
│   ├── api.ts          — единственная точка, которую нужно переписать на fetch('/api/v1/...')
│   └── store.ts         — Zustand, только локальное UI-состояние (таб курса и т.п.)
├── components/    — переиспользуемые UI-примитивы (CSS Modules)
└── pages/         — 6 экранов Этапа 2: Home, Subject, Material, Test, Ai, Profile (+ Progress, NotFound)
```

## Что дальше (не входит в Этап 2)

- Подключение к реальному API (`web_api/`, Этап 3 ТЗ) — начинается с переписывания `src/lib/api.ts`.
- Проверка Telegram `initData` на backend — фронт уже готов отдавать сырую строку
  (`getRawInitData()` в `src/lib/telegram.ts`), но сегодня её никто не использует.
- Экраны «Избранное», «Поиск», «Подписка» (полный магазин тарифов) — сейчас только
  заглушки-ссылки на экране профиля.
