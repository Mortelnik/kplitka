# Проверка: установка → skill → Python → DOCX

Владелец Р1, участники Р2/Р3/Р5. Срок: первая неделя.
Цель: выбрать проверенный способ интеграции, а не закончить бизнес-логику.
Статус на 21.10.2026: агент в диалоге прочитал установленный skill и выполнил
его скрипт из кэша; выдача и открытие файла в интерфейсе НЕ подтверждены.
Kalitka AI как отдельный целевой клиент не проверен.

## Что подтверждает документация, а что нет

Skill может содержать scripts, references и assets; он может работать без MCP,
если достаточно упакованных инструкций и ресурсов
([Build skills](https://developers.openai.com/plugins/build/skills)).
Portable-плагин имеет корневой `plugin.json` и каталог `skills/`;
repo marketplace использует `.agents/plugins/marketplace.json`, а `source.path`
разрешается относительно корня marketplace, не папки `.agents/plugins/`
([Package your plugin](https://developers.openai.com/plugins/build/plugins)).
Это не доказательство исполнения Python или возврата DOCX в Kalitka AI.

## Локальная предварительная проверка

Из корня репозитория:

```bash
uv sync --extra dev
uv run pytest -v
uv run python plugins/fish-kp/skills/generate-fish-kp/scripts/smoke_docx.py \
  --input plugins/fish-kp/skills/generate-fish-kp/assets/smoke-input.json \
  --output-dir out/smoke
```

Файл берётся из поля `document_path` JSON-ответа. Проверьте, что DOCX открывается
и итог равен `2200000.00` RUB. Это синтетическая арифметика, без выбора НДС,
скидок, контейнеров и тарифа. Повторный запуск создаёт другой файл.

## Проверка целевого клиента

1. Зафиксировать версию/сборку Kalitka AI, ОС, дату и способ установки.
2. Проверить, какой формат поддерживается: portable `plugin.json` или
   compatibility layout. Не создавать второй манифест без нужды.
3. Установить плагин по поддерживаемому в Kalitka AI пути. Каталог OpenAI
   является подготовленным примером, не гарантией наличия такой функции клиента.
4. В новом диалоге написать: «Проверь установку fish-kp на учебном примере.
   Выполни bundled Python-скрипт и верни технический DOCX».
5. Проверить, что активировался нужный skill. Установить доступность Python,
   зависимости python-docx, входного файла и разрешённой папки вывода.
6. Выполнить скрипт из УСТАНОВЛЕННОЙ копии плагина. Проверить JSON и DOCX.
   Файл из терминала разработчика не заменяет этот шаг.
7. Получить DOCX в интерфейсе, скачать и открыть его. Если клиент показал только
   локальный путь, выдача файла НЕ подтверждена.
8. Записать результат каждого шага и блокеры. После изменений переустановить
   плагин/обновить его копию способом клиента и повторить проверку.

## Протокол

| Проверка | Результат | Доказательство / ошибка |
|---|---|---|
| Версия клиента и способ установки | Подтверждено для Codex CLI, не проверено для Kalitka AI | Windows, 21.10.2026, `codex-cli 0.159.2`; локальный marketplace зарегистрирован командой `codex plugin marketplace add D:\Projects\kalitka-kp-plugin --json`, затем `codex plugin add fish-kp@kalitka-kp-dev --json`. |
| Пакет распознан | Подтверждено для Codex CLI | `codex plugin list`: `fish-kp@kalitka-kp-dev installed, enabled 0.2.0`; путь установленной копии `C:\Users\morte\.codex\plugins\cache\kalitka-kp-dev\fish-kp\0.2.0`. Использован существующий portable `plugin.json`, второй формат не создавался. |
| Skill активирован | Инструкции применены агентом в этом диалоге; автоматическая активация не проверена | Агент прочитал `SKILL.md` и `references/runtime-check.md` из установленного кэша и следовал разделу «Проверка установки». Прежняя отдельная `codex exec`-сессия была прервана. В ней при обращении к удалённому каталогу плагинов и Apps MCP возникал HTTP 401: `Could not parse your authentication token. Please try signing in again.` Причина не установлена; в текущем запуске 401 не возникал. |
| Python доступен | Подтверждено для агента в этом диалоге | `D:\Projects\kalitka-kp-plugin\.venv\Scripts\python.exe` выполнил bundled-скрипт из каталога установленного skill. |
| python-docx установлен | Подтверждено в проектном venv | Скрипт создал DOCX; `docx.Document` затем открыл его из того же venv. Глобальные зависимости не устанавливались. |
| Файл доступен из установленной копии | Подтверждено для агента | Агент работал в `C:\Users\morte\.codex\plugins\cache\kalitka-kp-dev\fish-kp\0.2.0\skills\generate-fish-kp` и запустил `scripts\smoke_docx.py` с `assets\smoke-input.json`. |
| Итог 2200000.00 | Подтверждено в запуске агентом | stdout: `ok=true`, `calculation.total="2200000.00"`; полный JSON показан ниже. |
| DOCX сформирован | Подтверждено на диске | `out/agent-smoke/technical-smoke-7d098e9d417a4cc592cf6b1ca0978ab4.docx`, 37204 байта; SHA-256 `6b7c91f5d363d04f234eb14c85e93b07b3729d88a734bddf2732988a6816d6f5`. ZIP исправен; `python-docx` прочитал 3 абзаца. |
| Запуск агентом в диалоге | Подтверждено | Первая попытка записи только в `out/agent-smoke` вернула JSON `{"ok": false, "error": "[WinError 5] Отказано в доступе: 'D:\\\\Projects\\\\kalitka-kp-plugin\\\\out\\\\agent-smoke'"}`. После запроса разрешения та же команда завершилась с кодом 0; неограниченный режим не применялся. |
| Получение документа через интерфейс | Не подтверждено | `open_in_codex` с новым DOCX вернул `status=queued`, не подтверждение открытия или скачиваемого вложения. Предложена ссылка на созданный файл в ответе; её доступность зависит от интерфейса и пока не проверена пользователем. |
| Подтверждение открытия пользователем | Не проверено | Ожидается явный ответ пользователя после попытки открыть документ. Не объединять с фактом создания DOCX. |

JSON запуска агентом:

```json
{"ok": true, "mode": "technical-smoke-only", "calculation": {"quantity_tons": "20", "unit_price": "100000.00", "tax_rate": "0.10", "currency": "RUB", "subtotal": "2000000.00", "tax": "200000.00", "total": "2200000.00"}, "document_path": "D:\\Projects\\kalitka-kp-plugin\\out\\agent-smoke\\technical-smoke-7d098e9d417a4cc592cf6b1ca0978ab4.docx", "sha256": "6b7c91f5d363d04f234eb14c85e93b07b3729d88a734bddf2732988a6816d6f5", "client_delivery_verified": false}
```

Команды проверки: `codex --version`; `codex plugin marketplace list`;
`codex plugin marketplace add D:\Projects\kalitka-kp-plugin --json`;
`codex plugin list`; `codex plugin add fish-kp@kalitka-kp-dev --json`;
`codex exec -C D:\Projects\kalitka-kp-plugin --skip-git-repo-check -s read-only --json
"Используй установленный skill generate-fish-kp..."` (прервано);
`D:\Projects\kalitka-kp-plugin\.venv\Scripts\python.exe
C:\Users\morte\.codex\plugins\cache\kalitka-kp-dev\fish-kp\0.2.0\skills\generate-fish-kp\scripts\smoke_docx.py
--input C:\Users\morte\.codex\plugins\cache\kalitka-kp-dev\fish-kp\0.2.0\skills\generate-fish-kp\assets\smoke-input.json
--output-dir D:\Projects\kalitka-kp-plugin\out\installed-smoke`;
`python -c` с `docx.Document`/`zipfile.ZipFile.testzip`, `Get-FileHash`.
20 тестов pytest и `scripts/validate_package.py` сообщены пользователем;
в рамках этого протокола повторно не запускались.

В доказательства не включать ключи API и реальные клиентские документы.

## Решение по архитектуре

- Все шаги прошли: локальный путь допускается для MVP; дальше реализуются
  реальное ядро, его поставка с плагином и зависимости.
- Нет исполнения Python: изучить поддерживаемый механизм инструментов.
  MCP является кандидатом, но его подключение в Kalitka AI тоже проверяется.
- Нет выдачи файла: отдельно проверить поддерживаемые ресурсы/вложения/хранилище.
  Добавление MCP само по себе не доказывает доступность скачивания.
- Установка не поддерживается: получить пример рабочего пакета у заказчика,
  не начинать переписывание бизнес-ядра.

MCP подходит для контролируемых инструментов, живых данных и кода на своей
инфраструктуре ([Build an MCP server](https://developers.openai.com/plugins/build/mcp-server)).
Отдельный клиент Responses API нужен только при прямых вызовах модели;
форматы `output` и `text.format` отличаются от Chat Completions
([Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)).
