# P3: file manifest

## Актуальный комплект для публикации

Дата: 28 октября 2026. Ветка: feature/p3-llm-docx. Все пути ниже уникальны и проверены на существование.
Три повреждённых документа восстановлены из читаемых оригиналов out/p3_handoff; manifest актуализирован по фактическим файлам.
Включён tests/test_review_draft.py: внутренний расчётный макет с обязательной маркировкой INTERNAL_DRAFT / TEST ONLY.
Правила коммерческого допуска не ослаблены. P1/P2 и исходные данные P4 не входят в изменения production-кода.

Исключены reference_p4/, out/, demo/p3_6_demo.docx, временные DOCX/PDF, кэши, локальные настройки и секреты.
Публикуются только явно перечисленные файлы; широкое добавление каталогов запрещено.
Тесты используют минимальные синтетические CSV из tests/fixtures/p4_synthetic, а не локальный reference_p4/.
Опубликованное ядро P2 включено только как неизменённая тестовая fixture, не как production-подключение.
Историческая изолированная проверка 45 файлов дала 499 passed; после добавления review_draft она не повторялась.
Актуальный полный рабочий прогон фиксируется в P3_TEST_REPORT.md. Коммерческая достоверность данных им не подтверждается.

46 files: 12 production modules, 22 test modules, 7 fixtures/source records, 5 review documents.

## Production

```text
src/kp_plugin/llm/needs.py
src/kp_plugin/llm/clarify.py
src/kp_plugin/llm/selection.py
src/kp_plugin/docgen/builder.py
src/kp_plugin/llm/unreachable.py
src/kp_plugin/llm/p4_catalog.py
src/kp_plugin/llm/cases.py
src/kp_plugin/llm/selection_bridge.py
src/kp_plugin/llm/p2_adapter.py
src/kp_plugin/docgen/gate.py
src/kp_plugin/docgen/corporate.py
src/kp_plugin/orchestrator.py
```

## Tests

```text
tests/test_docgen.py
tests/test_needs.py
tests/test_needs_eval.py
tests/test_clarify.py
tests/test_needs_clarify_integration.py
tests/test_unreachable.py
tests/test_unreachable_handler.py
tests/test_selection.py
tests/test_p4_catalog.py
tests/test_cases.py
tests/test_case_permissions.py
tests/test_selection_bridge.py
tests/test_calculation_binding.py
tests/test_p2_adapter.py
tests/test_p2_published.py
tests/test_docgen_gate.py
tests/test_corporate_docgen.py
tests/test_final_visual_docgen.py
tests/test_polished_docgen.py
tests/test_orchestrator.py
tests/test_p3_blockers.py
tests/test_review_draft.py
```

## Fixtures

```text
tests/fixtures/p3_needs_eval.json
tests/fixtures/demo_company_test_only.json
tests/fixtures/p2_47cb831/calculation.py
tests/fixtures/p2_47cb831/SOURCE.json
tests/fixtures/p4_synthetic/catalog/catalog.csv
tests/fixtures/p4_synthetic/prices_stock/warehouse_stock.csv
tests/fixtures/p4_synthetic/README.md
```

## Review documentation

```text
docs/handoff/p3/P3_IMPLEMENTATION_SUMMARY.md
docs/handoff/p3/P3_TEST_REPORT.md
docs/handoff/p3/P3_INTEGRATION_REQUIREMENTS.md
docs/handoff/p3/P3_HANDOFF_CHECKLIST.md
docs/handoff/p3/P3_FILE_MANIFEST.md
```
