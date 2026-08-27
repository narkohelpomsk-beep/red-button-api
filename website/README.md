# Сайт «Красная кнопка» (redbuttonhelp.ru)

Исходники главной страницы и английский перевод.

## Структура

| Файл | Назначение |
|------|------------|
| `index.html` | Главная (RU) с переключателем RU/EN |
| `en/index.html` | Главная (EN) |
| `chat-lite.js` / `site-chat-gpt.js` | Чат на RU |
| `chat-lite.en.js` / `site-chat-gpt.en.js` | Чат-UI и упрощённый режим на EN |
| `chat-config.js`, `metrika-config.js` | Конфиг API и Метрики |
| `assets/` | Логотипы центров |

## Как выложить на хостинг

Скопируйте содержимое `website/` в корень сайта (nginx), сохранив структуру:

```text
/index.html
/en/index.html
/chat-*.js
/site-chat-gpt*.js
/assets/...
```

Английская страница: `https://redbuttonhelp.ru/en/`

## Важно

- Полный GPT-чат через API по-прежнему отвечает на **русском** (`config.json` locale `ru`).
- На EN-странице переведены интерфейс лендинга и упрощённый чат (`chat-lite.en.js`).
- Статьи в футере (pomoshch-omsk, zavisimost и др.) пока только на русском.
