# Отчёт разработчика: P3-production-wiring

Статус: готово к ревью владельцем; продуктовая приёмка не заявляется.

## Актуальное продолжение: три замечания финальной сверки

База исправлений: 7ee566dad642201a721ed08259571e942c674deb. Владелец разрешил положительный учебный запуск, безопасные JSON-ошибки и subprocess-тесты уточнений. Изменены только production.py (обработка ошибок), добавлены проверки в test_production_wiring.py, учебный пример и документация задачи/handoff. Старые тесты и эталоны не изменены.

Положительный пример `positive-input.json` использует `positive-demo/profile/`. Все четыре файла и явное TEST ONLY подтверждение источника скопированы из существующей fixture payload в tests/test_production_wiring.py (e21fc82). Новый тест побайтно сравнивает профиль с исходной fixture и сравнивает JSON-данные. Новых цен, скидок, остатков или коммерческих attestations нет. `positive-demo/.gitattributes` сохраняет точные CSV-байты (-text) для стабильности хеша источника после checkout. Ни production runtime, ни launcher не импортируют tests.

Точная команда PowerShell из корня P3 worktree:

```powershell
& C:/Users/roman/.kalitka/kplitka/.venv/Scripts/python.exe plugins/fish-kp/skills/generate-fish-kp/scripts/run_production.py --runtime-root . --input docs/tasks/p3-production-wiring/positive-input.json --output-dir out/p3-positive-demo
```

Проверенный результат: exit **0**, ok=true, successful_calculation=true, calculation.total="275.00", gate_status=INTERNAL_DRAFT, client_offer=false. Созданы `out/p3-positive-demo/offer.docx` и `offer.json`. Это **внутренний диагностический DOCX, не клиентское КП**, несмотря на успешный расчёт P2. Полнота доставки и коммерческое доверие не подтверждены. Исходный fish_demo не изменялся и остаётся отрицательным примером с обязательной валидацией.

JSON-граница теперь обрабатывает KeyError, AttributeError и csv.Error наряду с прежними ошибками. Отсутствующий product_id в CSV возвращает ok=false, error_type=KeyError, сообщение об обязательном поле и exit **2**. Ошибки не превращаются в успех. Loader-функции P2 не изменялись.

Добавлено 7 проверок (с учётом параметризации):

- Положительный committed-пример: совпадение с fixture, настоящий расчёт через subprocess skill, закрытый gate, DOCX/JSON и сохранность входов.
- Четыре неверных профиля: отсутствие product_id в catalog/price CSV, неверный заголовок stock CSV, неверная структура rules JSON. Проверяются JSON-отказ, отсутствие traceback и сохранность прежнего вывода.
- Корректные ответы quantity/unit: сначала уточнения и отказ расчёта, затем total="275.00", пустой список оставшихся вопросов, INTERNAL_DRAFT, новый файл и сохранность прежних результатов.
- Неизвестный идентификатор вопроса (field_name/position): JSON ValueError, exit 2, отсутствие нового результата и сохранность предыдущих файлов.

Актуальные проверки: **15 passed** в test_production_wiring.py; полный harness **523 passed**, без skip; lint/package/tests exit **0**, harness exit **0**. Актуальный report.json: `out/checks/20261109T080545420863Z-4875ddb6/report.json`. Обязательная команда с uv по-прежнему не выполнена (uv отсутствует); использован явно разрешённый эквивалент существующим Python 3.12.10. PYTHONPATH и PYTEST_ADDOPTS — как в команде ниже, новый уникальный basetemp в out/. Проверки выполнялись с разрешением среды из-за прежних отказов доступа pytest к временным папкам.

Неизменны P2, profile/, profiles/, бизнес-правила, adapter, selection и commercial gate. Основная рабочая папка не редактировалась. Артефакты запуска и report.json остаются в игнорируемом out/. После успешного harness подготовлен отдельный локальный коммит исправлений; push/merge/PR запрещены и не выполняются.

Остаются препятствия клиентскому КП: нет авторизованного коммерческого issuer/attestation в этом интерфейсе, доверенных коммерческих входов и полной доставки; открыты Q1–Q9. Реальный LLM/eval и многопозиционный контракт — отдельные задачи. Это не блокеры технического wiring, но не позволяют объявить коммерческую готовность.

Ниже сохранён отчёт первоначальной реализации с историческим прогоном 516 passed; актуальный результат продолжения — 523 passed.

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
