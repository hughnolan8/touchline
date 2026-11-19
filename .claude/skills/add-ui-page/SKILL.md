---
name: add-ui-page
description: Add a page, panel, table or chart to the Touchline dashboard. Use for any change under touchline/web/.
---

1. **Conventions.** Read `touchline/web/AGENTS.md`.
2. **Data.** Add one function to `touchline/web/queries.py` that returns plain dicts. Its SQL
   lives there, not in the template.
3. **Route.** Add it in `touchline/web/app.py` with `page(request, "<name>", **data)`. For a
   new nav item, add it to the tuple list in `templates/base.html`.
4. **Template.** Create `templates/<name>.html` extending `base.html`. Use `.card`, `.tiles`
   and `table` inside `.scroll`, plus the existing `money`, `pct` and `when` filters. Charts
   are SVG helpers in `charts.py`, not JS.
5. **Test.** Add the path to `test_every_page_renders_on_an_empty_database` in
   `tests/test_web.py` and run `uv run pytest tests/test_web.py`.
6. **Visual check.** Use the `run-app` skill, at desktop and 375px widths. Update
   `docs/features/ui.md`.
