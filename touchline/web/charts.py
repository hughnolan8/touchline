"""Server-rendered inline SVG charts (no JS)."""

from markupsafe import Markup


def equity_svg(curve: list[dict], width: int = 640, height: int = 160) -> Markup:
    values = [point["equity"] for point in curve]
    if len(values) < 2:
        return Markup('<p class="muted">The equity curve appears after the first settled bet.</p>')
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - (v - low) / span * (height - 8) - 4:.1f}"
        for i, v in enumerate(values)
    )
    start_y = height - (values[0] - low) / span * (height - 8) - 4
    return Markup(
        f'<svg class="chart" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" '
        f'aria-label="Equity from £{values[0]:,.0f} to £{values[-1]:,.0f}">'
        f'<line x1="0" x2="{width}" y1="{start_y:.1f}" y2="{start_y:.1f}" class="baseline"/>'
        f'<polyline points="{points}" class="line"/></svg>'
    )
