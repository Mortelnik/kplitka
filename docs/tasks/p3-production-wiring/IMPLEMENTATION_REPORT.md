# Отчёт разработчика: P3-production-wiring

Статус: готово к ревью владельцем; продуктовая приёмка не заявляется.

## Контекст

- Контракт: TASK.md; согласованное ТЗ Матвея и уточнения владельца в чате 9 ноября 2026.
- Агент: Codex.
- Рабочая папка: C:/Users/roman/.kalitka/kplitka/.worktrees/p3-repair.
- Ветка: feature/p3-llm-docx.
- Базовый commit: 349cd2a9799a028e87cf1bccff1d0d8361701c1f.
- Локальный коммит реализации: e21fc82 (feat(p3): wire real P2 into JSON runtime and skill). Отчёт и handoff — отдельный последующий коммит документации.
- CONTRIBUTING.md отсутствует в checkout и дереве origin/main; не создавался, согласно уточнению владельца это не блокер.

## Изменения

| Файл | Изменение и назначение |
|---|---|
| src/kp_plugin/production.py | Production-импорт calculate_offer; загрузка и обязательная валидация профиля существующими функциями; сбор входов и вызов run_flow; DOCX и JSON-сводка, статусы и диагностика. |
| plugins/fish-kp/skills/generate-fish-kp/scripts/run_production.py | Тонкий JSON launcher установленного runtime либо явного --runtime-root; без бизнес-логики. |
| SKILL.md и references/workflow.md того же skill | Порядок запуска после уточнений, формат JSON и разграничение выполнения конвейера и коммерческого допуска. |
| tests/test_production_wiring.py | 8 тестов: настоящий P2, gate, неподтверждённые источники/количество, ошибки профиля, subprocess skill, JSON, fish_demo, сохранность артефактов. |
| docs/tasks/p3-production-wiring/* | Контракт, этот отчёт, пример исходного fish_demo и тексты двух Issues. |
| docs/handoff/p3/P3_INTEGRATION_REQUIREMENTS.md | Актуальный статус wiring и сохранённые ограничения; прежние исторические записи оставлены. |

Изменений вне контракта нет. Новые зависимости не добавлялись. Существующие тесты и эталоны не менялись. P2, profile/, profiles/, adapter, selection и commercial gate не менялись.

## Проверки

- Обязательная команда `uv run python scripts/check.py` не выполнена: uv недоступен в PATH. Использован прямо разрешённый владельцем эквивалент:

```powershell
$env:PYTHONPATH = "$PWD/src"
$env:PYTHONUTF8 = '1'
$runId = [guid]::NewGuid().ToString('N')
$env:PYTEST_ADDOPTS = "--basetemp=out/pytest-$runId -p no:cacheprovider --ignore=out --ignore=pytest-cache-files-031j2vj2 --ignore=pytest-cache-files-6jkwuxgn"
& C:/Users/roman/.kalitka/kplitka/.venv/Scripts/python.exe scripts/check.py
```

- Среда: существующий Python 3.12.10 основной папки; пакеты не устанавливались. PYTHONPATH явно выбирает src текущего P3 worktree, а не код основной ветки.
- Exit code harness: **0**. Lint **0**, package **0**, tests **0**; **516 passed**, без skip.
- report.json: `out/checks/20261109T075053257545Z-b070fb09/report.json` (от корня P3).
- Новые тесты отдельно: **8 passed**, exit **0**.
- Первые попытки pytest в ограниченной среде остановились на PermissionError временных каталогов до выполнения тестов; повтор с разрешением среды прошёл. Настройки выше меняют размещение временных файлов и исключают только вывод/служебные кэши; тесты не отключены и проверки не ослаблены.
- `git diff --check`: exit **0**. Запрещённые пути не входят в diff.
- Реальный запуск skill: exit **0**, создан `out/p3-production-wiring-demo/offer.docx` и `offer.json`. JSON: ok=true, gate_status=INTERNAL_DRAFT, client_offer=false, successful_calculation=false, calculation=null. Обязательная validate_profile сообщает отсутствие percent у D-01. Подтверждения источников и ConstraintReview отсутствуют, их runtime не придумывает.
- Отдельные реальные положительные вызовы P2 в новых API/subprocess тестах дали Decimal total 275.00 на явно учебном входе. Они используют production calculate_offer, без импорта P2 fixture и без подмены формул. Коммерческий допуск остаётся закрыт.
- Контрольные SHA-256 девяти исходно изменённых/неотслеживаемых файлов основной рабочей папки совпали с предварительным снимком; её ветка и набор изменений сохранены. Файлы основной папки не редактировались. Служебная Git-запись локальных коммитов worktree хранится в общем .git.
- Отметка M у tests/fixtures/p2_47cb831/calculation.py существовала до задачи: хеш файла/индекса/HEAD b36145c8b79f6377bde9f3067c7feb02471719f3, diff пустой. Файл не добавлялся в коммиты и индекс для устранения отметки не обновлялся.

## Самостоятельный запуск полного конвейера

Одна команда PowerShell из корня P3 worktree:

```powershell
& C:/Users/roman/.kalitka/kplitka/.venv/Scripts/python.exe plugins/fish-kp/skills/generate-fish-kp/scripts/run_production.py --runtime-root . --input docs/tasks/p3-production-wiring/fish-demo-input.json --output-dir out/p3-production-wiring-demo
```

Пути к DOCX и JSON возвращаются в stdout JSON. При существующем DOCX run_flow выбирает новый суффикс; старый файл сохраняется. Вывод — **внутренний диагностический отчёт, не клиентское КП**. В исходном fish_demo P2 передан в run_flow, но не исполняется из-за обязательных блокировок. Получать сумму обходом валидации запрещено. Примерный вход не изменяет сам профиль.

## Критерии задачи

| Критерий | Результат |
|---|---|
| Подключение настоящего P2 к run_flow | Реализовано, подтверждено API и subprocess тестами реального расчёта. |
| Skill и JSON | Скрипт делегирует production runtime; UTF-8 stdout и отдельный JSON, Decimal строками, абсолютные выходные пути. |
| Сохранение блокировок | Gate не менялся; отсутствующие attestations не создаются, fish_demo не исправлялся ради суммы. |
| Неподтверждённые входы | Отказ до вызова P2, диагностический DOCX и статусы. Неверный JSON возвращает ok=false и exit 2. |
| Issues | gh недоступен; тексты «P3: многопозиционный заказ» и «P3: реальный LLM и версионированные промпты» подготовлены в issues.md. Issues не опубликованы. |
| Проверки | Эквивалент harness exit 0; 516 passed. |
| Локальная история | Реализация e21fc82 и последующий коммит документации; push/merge/PR не выполнялись. |

## Ограничения и вопросы

- Закрыт технический wiring, а не коммерческая готовность и не приёмка проекта.
- Нет реального LLM/провайдера: ручной structured input проходит существующий NeedsExtractor с его ограниченной проверкой evidence. FakeLLM тестов не доказывает качество извлечения; eval вынесен в отдельную Issue.
- Runtime не выдаёт коммерческое свидетельство и не принимает его через публичный JSON. Для клиентского КП нужна отдельная авторизованная интеграция issuer; gate не обходится.
- Q1–Q9 открыты. Многопозиционный заказ, полная доставка, коммерческая достоверность прайсов/остатков и полномочия подтверждающей стороны не реализованы этой задачей.
- Копия skill требует доступного kp_plugin runtime и зависимостей либо явного --runtime-root. Установка и проверка в Kalitka AI не выполнялись.
- Word-рендеринг и визуальная приёмка DOCX не выполнялись; проверена читаемость DOCX через python-docx и существующие регрессии.
- Блокеров технической сдачи wiring не осталось. Решение о принятии и merge — за владельцем.
