# Исправление UTF-8 для Windows

## Причина

В каркасе 0.2 некоторые вызовы Path.read_text() не указывали кодировку.
На Windows пользователя Python 3.13 использовал cp1251, а SKILL.md записан
в UTF-8. Ошибка относится к переносимости каркаса, не к данным пользователя.

## Применение

Архив содержит относительные пути от корня проекта, без дополнительной
папки kalitka-kp-plugin. Закройте процессы агента, редактирующие эти файлы.
Если вы сами изменяли перечисленные файлы, сначала сохраните свою версию
и объедините изменения вручную. Иначе распакуйте архив в
`D:\Projects\kalitka-kp-plugin` с заменой файлов.

Изменяются:
- scripts/validate_package.py
- scripts/import_issues.py
- tests/test_plugin_package.py
- tests/test_issue_importer.py
- plugins/fish-kp/skills/generate-fish-kp/scripts/smoke_docx.py
- .github/workflows/ci.yml

Добавляется tests/test_utf8_portability.py.
README_UTF8_FIX.md можно оставить как пояснение к исправлению.
Каталоги, профили, ТЗ, зависимости и Git-история не изменяются.

## Проверка из Windows CMD или PowerShell

```text
uv run pytest -v
uv run python scripts/validate_package.py
```

Ожидание: 20 passed, затем сообщение Package paths and frontmatter OK.
Создавать новое окружение и повторять uv init не нужно.

## Если пока не применяете исправление

Временный режим UTF-8 для двух команд:

```text
uv run python -X utf8 -m pytest -v
uv run python -X utf8 scripts/validate_package.py
```

Это обход проблемы для текущего запуска, а не замена исправления исходников.
Не перекодируйте SKILL.md в cp1251 и не используйте errors="ignore".

## Проверено в среде сборки

20 тестов проходят на Linux Python 3.12. Ошибка старого валидатора
воспроизведена через cp1251-default, исправленный проходит тот же сценарий.
Проверены UTF-8 stdout при PYTHONIOENCODING=cp1251 и кириллический путь DOCX.
Добавлена матрица GitHub Actions Ubuntu/Windows и Python 3.11/3.13.
Реальная Windows в среде сборки недоступна, CI Windows ещё не запускался.
