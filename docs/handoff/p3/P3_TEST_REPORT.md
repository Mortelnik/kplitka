# P3: фактические проверки и дефекты

## Предпубликационная проверка — 28 октября 2026

Восстановлено в UTF-8 из неповреждённого out/p3_handoff/P3_TEST_REPORT.md.
Старые статусы ниже относятся к моменту соответствующего исторического аудита.

Актуальная команда: `.venv\Scripts\python.exe scripts/check.py`.
Отчёт: `out/checks/20261028T140221127596Z-5a4e2cd5/report.json`.
Ruff, package validation и полный pytest: PASS, exit 0.
Итог pytest: **501 passed / 0 failed / 0 skipped**.
Два новых теста tests/test_review_draft.py проверяют внутренний макет, исходные суммы P2 и обязательную маркировку INTERNAL_DRAFT / TEST ONLY.
Неизвестные условия не заменяются коммерческими обещаниями; отсутствие свидетельств блокирует коммерческий допуск.

Тесты используют минимальные синтетические CSV и временные документы вместо reference_p4/ и заранее созданного final_visual_offer.docx.
Историческая изолированная проверка 45 кандидатов дала 499 passed; актуальные 46 файлов в изолированной копии в этой задаче не проверялись.
Production P1/P2 относительно исходного HEAD не изменён. Тесты проверяют SHA256 и Git blob опубликованной fixture P2.
Точный комплект: 46 файлов в P3_FILE_MANIFEST.md; generated DOCX/PDF и локальные данные P4 исключены.

## Исторический отчёт из восстановленного оригинала

## Контрольное закрытие B1/B2 — актуальная проверка 28 октября 2026

Это проверка без изменения production-кода, тестов, P1/P2, CSV P4 и дизайна. Обновлены только три разрешённых handoff-документа. Ветка feature/p3-llm-docx и HEAD 1314ecdd89b50b42faafa5fae4cd41af60435a43 сохранены.

Целевая команда: `.venv\Scripts\python.exe -m pytest tests/test_p3_blockers.py tests/test_docgen.py tests/test_docgen_gate.py tests/test_orchestrator.py -q -p no:cacheprovider --tb=short` → **61 passed, 0 failed, 0 skipped**, exit 0.

Общий `.venv\Scripts\python.exe scripts/check.py` → **499 passed, 0 failed, 0 skipped**, lint/package/tests PASS, exit 0. Новый report.json: `out/checks/20261028T124022365256Z-b8954ff1/report.json`. git diff --check: exit 0. Прогон с разрешённым выходом из песочницы для временных файлов pytest; зависимости не устанавливались.

### Конкретные доказательства коммерческого шлюза

Все перечисленные случаи находятся в tests/test_p3_blockers.py и повторно PASSED в текущем прогоне:

| Утверждение | Тест / параметр | Результат |
|---|---|---|
| Неизвестные верхнеуровневые constraints не одобряются | test_unknown_top_level_constraints_block_commercial_approval | PASSED, INTERNAL_DRAFT |
| Пустой список/None не означает подтверждённое отсутствие, если поле неизвестно | test_empty_unknown_constraints_never_become_confirmed_absence[request], [item] | Оба PASSED, constraints_unknown |
| Неподтверждённые evidence и противоречивый review блокируют | test_unknown_conflicting_or_incompatible_review_blocks[unverified], [contradictory] | Оба PASSED, constraints_unconfirmed / constraints_contradictory |
| scope_complete=True без отдельного review недостаточно | test_unknown_conflicting_or_incompatible_review_blocks[missing], [unknown] | Оба PASSED; setup_gate сохраняет scope_complete=True, constraints review заменяется на None/UNKNOWN |
| Положительный допуск только с явным подтверждением и совместимостью | test_explicit_verified_compatible_constraints_pass_without_mutation[request], [item] | Оба PASSED, CONFIRMED + источники + актуальный fingerprint + три compatible=True |
| Отсутствие условий требует отдельного подтверждения | test_absence_requires_explicit_confirmed_review | PASSED, constraints_absence_unconfirmed |
| Нельзя прикрыть конфликт наличия условий подтверждением их отсутствия | test_unknown_conflicting_or_incompatible_review_blocks[absence] | PASSED, constraints_presence_conflict |
| Проверяются товар, расчёт и условия предложения | test_unknown_conflicting_or_incompatible_review_blocks[product], [calculation], [terms] | Все PASSED, конкретный constraints_incompatible |
| При блокировке сохраняется диагностический INTERNAL_DRAFT; коммерческий файл не создаётся | test_unknown_conflicting_or_incompatible_review_blocks (все 10 параметров) | PASSED: черновик повторно читается, содержит код причины; commercial generation raises ValueError, файл отсутствует |
| Изменение ограничений делает прежнее review недействительным даже с новым общим attestation | test_changed_constraint_invalidates_old_review_even_with_new_price_attestation | PASSED, constraints_review_stale |
| Источники и прочие проверки не обходятся | test_unknown_conflicting_or_incompatible_review_blocks[sources], test_constraint_review_does_not_override_unknown_stock | Оба PASSED |

По фактическому gate.py: ConstraintReview по умолчанию UNKNOWN; CommercialAttestation.constraints по умолчанию None; _constraint_issues всегда исполняется до допуска, неизвестные поля и отрицательное evidence не стираются. Свидетельство сравнивается с fingerprint полного current invocation и output. Только проверка request.constraints может быть разрешена внешним review, остальные проблемы не исключаются из блокировки. Не добавлено интерпретации текста. Истинность внешней проверки и полномочия reviewer остаются доверенной границей, а не доказанным коммерческим фактом.

### Конкретное доказательство B2

- tests/test_docgen.py::test_real_p2_reference_if_available — **PASSED**, не skipped. При локальной production-заглушке вызывается опубликованная fixture через проверяющий SHA256/Git SHA-1 loader. Дополнительного pytest.skip в функции нет.
- tests/test_p3_blockers.py::test_legacy_reference_with_actual_published_p2 — **PASSED**: monkeypatch только в памяти предоставляет настоящую опубликованную функцию как локальную calculate_offer; исполняется тот же legacy-тест.
- Вход содержит необходимые tax_rate/source_ref в прайсе и container_capacity_tons/source_ref в каталоге. tax_rate=0.2 следует из прежнего учебного эталона 2100000/10500000; не назначен реальным клиентам. Проверяются исходные Decimal base/discount/tax/total и источники. Формулы P2 не менялись.
- Fixture commit 47cb8314048da277ec4f85f969a01600a7b2965e, SHA256 `56eaa710080d061dba7ce395297db45031736618ad76016854de5a48be56643e` сохранён. Ошибка была в неполной fixture старого теста, не скрыта skip и не исправлялась внутри ядра Юлии.

**Контрольный вердикт:** B1 FIXED, B2 FIXED. По двум проверенным дефектам внутренних BLOCKER не осталось; техническое ревью возможно. Это не полная повторная независимая приёмка всей роли и не закрытие production/runtime/LLM/доставки/авторизации.

Дата: 28 октября 2026. Актуализировано после отдельно разрешённых исправлений B1/B2. Ниже сохранены результаты первоначального аудита и воспроизведения, явно отделённые от текущего статуса.

## Актуальный итог исправлений

Оба дефекта сначала повторно воспроизведены двумя новыми тестами: 2 failed (COMMERCIALLY_APPROVED вместо draft и KeyError tax_rate). После исправления новые регрессии и позитивные сценарии прошли.

- `.venv\Scripts\python.exe -m pytest tests/test_p3_blockers.py tests/test_docgen.py tests/test_docgen_gate.py tests/test_orchestrator.py tests/test_final_visual_docgen.py tests/test_polished_docgen.py -q -p no:cacheprovider --tb=short`: **69 passed, exit 0**.
- `.venv\Scripts\python.exe scripts/check.py`: **499 passed, 0 skipped**, lint/package/tests PASS, exit 0.
- Актуальный report.json: `out/checks/20261028T122308931550Z-d36060cb/report.json`.
- Новая группа tests/test_p3_blockers.py: 19 passed. test_docgen.py: теперь 12 passed, skip отсутствует. Остальные значения покрытия в исторической таблице ниже не изменились.
- git diff --check: exit 0; зависимости не менялись. Итоговые проверки с разрешённым выходом из песочницы из-за временных каталогов pytest.

**B1 закрыт.** Отсутствующий/unknown/contradictory review, неизвестные constraints на верхнем уровне или в позиции, явно unverified evidence, нет источников, отсутствует подтверждение отсутствия условий, несогласованные статусы и несовместимость по товару/расчёту/условиям дают INTERNAL_DRAFT с конкретным кодом constraints_*. Существующие условия допускаются только при отдельном ConstraintReview, совпадающем с отпечатком invocation+output. Изменение условий делает review устаревшим; неизвестные остатки не перекрываются review. Требования и вся диагностика сохраняются без изменения. Два положительных случая request/item проверены с настоящей P2. Нет эвристик свободного текста.

**B2 закрыт.** Причина — неполный вход старого теста: tax_rate, source_ref прайса, container_capacity_tons и source_ref товара отсутствовали; это не дефект расчётного кода Юлии. Fixture заполнена по фактическому API P2. Учебная ставка 0.2 выведена из уже зафиксированных в этом же тесте tax=2100000/base=10500000, а не взята из P4 или назначена бизнесу. Capacity=26 — существующий учебный вход. В production P2 ничего не подменяется. Если локального импорта нет, тест исполняет неизменённую опубликованную fixture с checksum-проверкой. Отдельная регрессия инъецирует ту же настоящую функцию как локальный импорт и выполняет legacy-тест. Проверяются Decimal base/discount/tax/total и источники.

Положительные старые TEST ONLY свидетели дополнены явным review подтверждённого отсутствия ограничений с отдельного разрешения владельца. Проверки одобрения и сумм не удалялись/не ослаблялись. Новое обязательное для допуска поле по умолчанию unknown; старые вызовы API не ломаются, но без review коммерческая генерация теперь закономерно блокируется.

Оставшаяся граница доверия: кто-то вне P3 должен проверить и удостоверить совместимость условий; review не является автоматическим доказательством коммерческой истинности. Срок и полномочия задаёт внешнее CommercialAttestation. Исходные bridge-проблемы request.constraints сохраняются для диагностики, но именно эта проверка может быть закрыта review в gate; остальные проблемы блокируют как прежде.

## Исторический аудит до исправлений

В первоначальном аудите код не менялся; приведённые далее старые цифры и команды воспроизведения описывают состояние ДО исправления, не актуальный результат.

## Новые прогоны

1. `.venv\Scripts\python.exe -m pytest tests/test_needs.py tests/test_needs_eval.py tests/test_clarify.py tests/test_needs_clarify_integration.py tests/test_unreachable.py tests/test_unreachable_handler.py tests/test_selection.py tests/test_p4_catalog.py tests/test_cases.py tests/test_case_permissions.py tests/test_selection_bridge.py tests/test_calculation_binding.py tests/test_p2_adapter.py tests/test_p2_published.py tests/test_docgen.py tests/test_docgen_gate.py tests/test_corporate_docgen.py tests/test_final_visual_docgen.py tests/test_polished_docgen.py tests/test_orchestrator.py -q -p no:cacheprovider`

**444 passed, 1 skipped**, exit 0.

2. `.venv\Scripts\python.exe scripts/check.py`

**479 passed, 1 skipped; lint/package/tests PASS**, exit 0.

Report: `out/checks/20261028T120857224765Z-4bdf794f/report.json`. git_state_changed=false, все три returncode=0. Выполнено с разрешённым выходом из песочницы: ранее штатный сбор временных каталогов давал PermissionError. Ничего не устанавливалось.

3. `git diff --check` — exit 0. `git diff --cached --name-only` пуст. `git ls-files --stage reference_p4/` пуст. `git check-ignore -v reference_p4/` → `.git/info/exclude:8:/reference_p4/`. `out/p3_handoff/` исключён общим правилом out/, файлы отчётов не подготовлены к коммиту.

## Покрытие по фактическому tests.log

| Тестовый модуль | Passed | Что проверяет |
|---|---:|---|
| test_needs.py | 32 | Нормализация, типы, неизвестные/неподтверждённые поля и текстовое evidence |
| test_needs_eval.py | 3 | Только структура 21 сценария JSON и запрет выдуманных фактов в ожидаемых данных; не исполнение LLM-eval |
| test_clarify.py | 28 | Вопросы, ответы, конфликты, невалидные количества, сохранность |
| test_needs_clarify_integration.py | 21 | FakeLLM → частичный запрос → последовательные ответы → readiness, история |
| test_unreachable.py | 47 | Структура/инварианты причин, стоимости и альтернатив |
| test_unreachable_handler.py | 40 | Детерминированные пять причин, границы бюджета, внешние варианты |
| test_selection.py | 41 | ID/имя/синонимы, draft, неоднозначность, единицы/остатки, несколько позиций |
| test_p4_catalog.py | 33 | Реальные два CSV, партии, источники, ошибки/негативные копии, synthetic |
| test_cases.py | 23 | Ссылки/контент/задача/несколько товаров и сохранность |
| test_case_permissions.py | 18 | allowed/prohibited/unknown, конфликт прав и usage_limits |
| test_selection_bridge.py | 20 | Проблемы и bindings, кейсы отдельно, P4 и источники |
| test_calculation_binding.py | 24 | Подмена ID/позиций/количества/единицы/версий/валюты, каноничность |
| test_p2_adapter.py | 47 | Протокол на stub, отказ плохих входов/ответов, доверие и полнота |
| test_p2_published.py | 13 | 9 случаев действительно вызывают код Юлии, 4 блокируют до вызова |
| test_docgen.py | 11 (+1 skipped) | Прежние документы/суммы/входы/технический текст; legacy P2-reference skipped |
| test_docgen_gate.py | 25 | Текущий контекст, источники/стоимость, сроки свидетельств, кейсы, черновик |
| test_corporate_docgen.py | 5 | Структура и стили OOXML, P4-черновик, optional, NaN/Infinity |
| test_final_visual_docgen.py | 6 | Видимый TEST ONLY, дата, условные блоки, длинные значения, изоляция demo |
| test_polished_docgen.py | 2 | Утверждённые шрифты/интервалы, суммы и сохранность старого примера |
| test_orchestrator.py | 5 | P4 → draft; настоящая P2 → TEST ONLY, запрещённый/unknown кейс, invalid/stale |

Ещё 35 прошедших проверок относятся к harness/package/plugin/importer/UTF-8; тесты с именами test_calculation.py и test_validation.py локально содержат только docstring, тестовых функций в них нет. Новые тесты не добавлялись в рамках аудита.

## B1 — историческое воспроизведение, сейчас ИСПРАВЛЕНО

Фактически воспроизведено: CustomerNeeds.unknown_fields=['constraints'], неподтверждённое условие сохранено в model_payload, остальные данные и TEST ONLY свидетельства полные. С настоящей функцией P2 select_products возвращает confirmed, gate — COMMERCIALLY_APPROVED, blockers=(). Аналогичный unknown_fields у item даёт needs_review/INTERNAL_DRAFT.

Причина: selection.py:171 пересекает только верхнеуровневые unknown_fields с product_name/quantity/unit; needs.py:286 strict validate не отклоняет неизвестные дополнительные поля запроса; gate.py:77–112 не имеет самостоятельного запрета оставшихся значимых неизвестных полей. Извлечение может удалить неподтверждённое верхнеуровневое условие из constraints, сохранив его в model_payload и unknown_fields. Отпечаток фиксирует такое состояние, но не запрещает его.

Воспроизведение в памяти, без файлов:

```python
import sys
sys.path.insert(0, 'tests')
from datetime import date
from test_docgen_gate import setup_gate
from test_orchestrator import _test_attestor
from test_p2_published import core, COMMIT
from kp_plugin.llm.selection import select_products
from kp_plugin.llm.p2_adapter import run_p2, prepare_p2_invocation
from kp_plugin.llm.selection_bridge import assess_selection
from kp_plugin.docgen.gate import evaluate_gate
data, *_ = setup_gate()
data['needs'].unknown_fields = ['constraints']
data['needs'].model_payload['constraints'] = ['TEST ONLY unresolved client restriction']
data['settings'] = data['settings'].model_copy(update={'p2_implementation': COMMIT})
data['selection'] = select_products(data['needs'], data['profile'].products)
result = run_p2(**data, calculate_offer=core.__wrapped__())
current = prepare_p2_invocation(**data)
assessment = assess_selection(data['needs'], data['selection'], data['profile'],
    calculation=result.evidence, calculation_context=current.bridge_context,
    confirmed_sources=data['settings'].input_sources)
decision = evaluate_gate(result, current, assessment,
    attestation=_test_attestor(result), as_of=date(2026, 10, 28))
print(decision.status, decision.blockers)
# Факт: COMMERCIALLY_APPROVED (). Требование: INTERNAL_DRAFT до разрешения ограничения.
```

На момент аудита требовалось разрешение. Оно получено последующим заданием, исправление и отрицательные тесты выполнены; актуальный статус в начале документа. Сам selection остаётся консервативным, внешнюю совместимость удостоверяет gate review.

## B2 — историческое воспроизведение, сейчас ИСПРАВЛЕНО

`tests/test_docgen.py:262` сейчас пропускается из-за отсутствия локальной calculate_offer. Он передаёт каталог без container_capacity_tons/source_ref и прайс без tax_rate/source_ref. При подключении настоящего P2 тест падает `KeyError: 'tax_rate'`.

Проверено без замены локального файла:

```python
import sys
sys.path.insert(0, 'tests')
import kp_plugin.engine.calculation as local
from test_p2_published import core
from test_docgen import test_real_p2_reference_if_available
local.calculate_offer = core.__wrapped__()  # только память отдельного процесса
test_real_p2_reference_if_available()
# KeyError: 'tax_rate'
```

Это был дефект старого тестового входа, не ошибка Юлии. Вход обновлён с разрешения владельца, ожидаемые суммы сохранены. Актуальный запуск не имеет skip, но production wiring по-прежнему отдельно не реализован.

## IMPORTANT — воспроизводимость и доверенная граница

- Полный harness зависит от исключённого local reference_p4; в чистом клоне без отдельно полученного P4 эта группа не воспроизводится. Подменять вымышленными CSV нельзя.
- test_polished_docgen.py:22–23 читает ранее существующий игнорируемый out/p3_e2e/final_visual_offer.docx. В полном прогоне его может создать предшествующий тест; самостоятельный запуск в чистом checkout зависит от артефакта/порядка.
- TEST ONLY свидетельства подтверждают работу контрактов, не существование товара/истинность прайса. issuer/confirmed/externally_validated не аутентифицируются; scope_complete — внешнее утверждение. Источники правил должны быть непусты, но нет схемы соответствия каждого правила конкретной записи-источнику; для цены сопоставляется source_id, не вся тройка версии/locator. Сам хеш доверия не создаёт.
- run_p2 валидирует типы/конечность/источники ответа, но не проверяет арифметическое тождество сумм; произвольный injected callable и p2_implementation — ответственность доверенного вызывающего компонента. Production-идентификация исполняемого артефакта не реализована.

## Пробелы и сохранность

Нет реального LLM/API, семантического evidence-eval, UI/runtime skill activation, production P2 wiring, multi-item коммерческого расчёта, доставки сверх total, отдельной сводки/чат-черновика/постоянной сессии. Нет полного свежего прогона после объединения с P2. Автоматический Word-рендеринг здесь не выполнялся; визуальное утверждение polished-дизайна предоставил владелец.

Неизменность до/после проверок (SHA256):

- final_polished_offer.docx: `3f71e2cbcba23abc62566f5f9ff74595264f1285165eda450624388cd0efe10d`;
- P4 catalog.csv: `7ba885b7bf39f0bc368fde0f4f7d8755a9df1a7c24750cb8f3ccdd9ea48110cf`;
- P4 warehouse_stock.csv: `7dfdef2b2b277aa8cf41693beb980866648b12ecadc484fec85f636ffcc8bbdc`;
- опубликованная P2 fixture: `56eaa710080d061dba7ce395297db45031736618ad76016854de5a48be56643e`.

Тесты создали новые суффиксные документы и out/checks, не перезаписывая прежние демонстрационные файлы. Зелёный harness не включает воспроизведённый B1 и не исполняет B2 при production P2.
