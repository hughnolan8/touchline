# web/ — conventions

- One route per page in `app.py`; its data comes from one function in `queries.py`.
- Templates extend `base.html`; shared fragments are `_name.html` includes.
- `hx-boost` on `<body>` makes navigation AJAX; pages always render in full (use
  `hx-select` for partial refreshes, as on the Engine page). No JS build step.
- Charts are inline SVG from `charts.py`. Colours are CSS variables in `static/app.css`
  with a dark-mode override; keep layouts working at 375px width.
- Mutating actions are `POST /admin/<action>` behind `TOUCHLINE_ADMIN_TOKEN` basic auth;
  read-only pages are public. Display times in Europe/London; store UTC.
