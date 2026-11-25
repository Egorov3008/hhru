# Golden-фикстуры hh.ru

Каждому `*.html` соответствует `*.json` — эталонный ответ парсера.
Сломался markup hh.ru → golden-тест красный, а не тихая деградация.

## Как снять новую фикстуру

1. Открой страницу выдачи в браузере с живой сессией hh.ru:
   `https://krasnoznamensk.hh.ru/search/vacancy?text=<запрос>&searchArea=1&itemsOnPage=50`
2. Сохрани **полный HTML** страницы (Ctrl+S, «Веб-страница, полностью»)
   в `tests/fixtures/<query>_area<area>_p<page>.html`.
3. Обнови golden JSON:

   ```bash
   .venv/bin/python tools/update_fixtures.py
   ```

   Скрипт вызывает парсер на сохранённом HTML и пишет результат рядом
   с `.html` в виде `.json`.

4. Прогони тесты — должны остаться зелёными:

   ```bash
   .venv/bin/python -m pytest tests/test_hh_adapter.py -q
   ```

## Структура

```
tests/fixtures/
├── __init__.py      # FIXTURE_DIR, check_golden(), norm()
├── README.md        # этот файл
├── python_area1_p0.html   → python_area1_p0.json
├── python_area1_p1.html   → python_area1_p1.json
└── analitika_area1_p0.html → analitika_area1_p0.json
```

`check_golden(path)` → True, если JSON валиден как `list[CardDTO]`.
`norm(value)` сворачивает узкие/неразрывные пробелы hh.ru к обычным.
