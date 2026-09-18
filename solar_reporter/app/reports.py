"""
Genereert PDF-rapporten (dagelijks/maandelijks) op basis van een door de
gebruiker samengesteld layout-template (zie settings.py:
branding.pdf_template). Elk element in dat template (tekst, afbeelding,
grafiek) staat in procenten van de pagina en wordt hier op de juiste plek
getekend. Gebruikt matplotlib om zowel de grafiek als de PDF-pagina zelf te
tekenen (geen extra PDF-bibliotheek nodig).
"""
import io
import re
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.patches import Rectangle
from matplotlib.backends.backend_pdf import PdfPages

import images as images_module

PAGE_WIDTH_IN = 8.27  # A4 staand
PAGE_HEIGHT_IN = 11.69

# Tags die in tekstelementen gebruikt kunnen worden; {tag} wordt vervangen
# door de waarde uit de context die per rapport wordt opgebouwd (zie
# app.py: _report_context). Deze lijst wordt ook aan de front-end
# geserveerd (tag-kiezer in de PDF-editor).
AVAILABLE_TAGS = [
    {"tag": "report_title", "label": "Titel van het rapport"},
    {"tag": "period_label", "label": "Periode (datum of maand)"},
    {"tag": "opbrengst_kwh", "label": "Opbrengst (kWh)"},
    {"tag": "opbrengst_euro", "label": "Opbrengst (€)"},
    {"tag": "besparing_totaal_kwh", "label": "Totale besparing (kWh)"},
    {"tag": "besparing_totaal_euro", "label": "Totale besparing (€)"},
    {"tag": "gegenereerd_op", "label": "Datum/tijd van verzenden"},
]

_TAG_PATTERN = re.compile(r"\{([a-z0-9_]+)\}")

_FONT_FAMILIES = {"sans-serif", "serif", "monospace"}
_FONT_STYLES = {"normal", "italic", "oblique"}


def substitute_tags(text, context):
    """Vervangt {tag}-placeholders door hun waarde. Onbekende tags blijven
    ongewijzigd staan, zodat een typefout niet leidt tot een fout rapport."""
    def repl(match):
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return _TAG_PATTERN.sub(repl, text or "")


def _wrap_text(text, width_pct, font_size):
    """Ruwe schatting van het aantal tekens dat past in de breedte van het
    element, zodat lange teksten niet buiten hun vak lopen. Geen exacte
    tekstmeting (dat vereist een gerenderd canvas) maar in de praktijk
    ruim voldoende voor rapportteksten."""
    avail_in = max((width_pct or 10) / 100.0 * PAGE_WIDTH_IN, 0.3)
    avg_char_width_in = max((font_size or 12) * 0.5, 4) / 72.0
    max_chars = max(8, int(avail_in / avg_char_width_in))

    lines = []
    for line in (text or "").split("\n"):
        lines.extend(textwrap.wrap(line, max_chars) or [""])
    return "\n".join(lines)


def _draw_text_element(fig, ax, el, context, box_height_pct):
    """Tekent een tekstelement regel voor regel (in plaats van één
    ax.text-aanroep met '\\n') zodat we voor onderstreping de werkelijk
    gerenderde breedte van elke regel kunnen opmeten en er een echte lijn
    onder kunnen tekenen — matplotlib-tekst heeft geen ingebouwde
    underline-optie."""
    raw = substitute_tags(el.get("text", ""), context)
    font_size = el.get("font_size", 12)
    wrapped = _wrap_text(raw, el.get("width", 10), font_size)
    align = el.get("align", "left")
    tx, ha = {
        "left": (0.0, "left"),
        "center": (0.5, "center"),
        "right": (1.0, "right"),
    }.get(align, (0.0, "left"))
    family = el.get("font_family")
    if family not in _FONT_FAMILIES:
        family = "sans-serif"
    style = el.get("font_style", "normal")
    if style not in _FONT_STYLES:
        style = "normal"
    weight = el.get("font_weight", "normal")
    color = el.get("color", "#111111")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    box_height_in = max((box_height_pct or 10) / 100.0 * PAGE_HEIGHT_IN, 0.05)
    line_height_frac = min(0.9, (font_size * 1.22 / 72.0) / box_height_in)

    text_objs = []
    ypos = 1.0
    for line in wrapped.split("\n"):
        text_objs.append(ax.text(
            tx, ypos, line,
            fontsize=font_size, fontweight=weight, fontstyle=style,
            fontfamily=family, color=color, ha=ha, va="top",
        ))
        ypos -= line_height_frac

    if el.get("underline"):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        inv = ax.transData.inverted()
        for t in text_objs:
            if not t.get_text():
                continue
            bbox = t.get_window_extent(renderer=renderer)
            (x0, y0), (x1, _) = inv.transform([[bbox.x0, bbox.y0], [bbox.x1, bbox.y0]])
            if x1 > x0:
                ax.plot(
                    [x0, x1], [y0, y0], color=color,
                    linewidth=max(font_size * 0.05, 0.8), solid_capstyle="butt",
                )


def _style_chart_axes(ax, show_grid):
    """Geeft de as-stijl een iets luxere, rustigere uitstraling: zachte
    rasterlijnen, dunnere/lichtere randen en grijstinten voor labels."""
    ax.set_axisbelow(True)
    if show_grid:
        ax.grid(axis="y", linestyle="--", linewidth=0.7, alpha=0.35, color="#9aa5b1")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c7ccd1")
    ax.spines["bottom"].set_color("#c7ccd1")
    ax.tick_params(colors="#5b6470")
    ax.yaxis.label.set_color("#5b6470")


def _draw_chart(ax, el, chart_labels, chart_values, chart_ylabel):
    """Tekent de grafiek volgens de instellingen van het chart-element:
    type (staaf/lijn/vlak), kleur, rasterlijnen, waardelabels en
    lijndikte/markers."""
    chart_type = el.get("chart_type", "bar")
    color = el.get("chart_color", "#03a9f4")
    show_grid = el.get("show_grid", True)
    show_values = el.get("show_values", False)
    show_markers = el.get("show_markers", True)
    line_width = el.get("line_width", 2.5)
    value_decimals = max(0, min(4, int(el.get("value_decimals", 2))))

    n = len(chart_labels)
    x_positions = list(range(n))
    max_val = max(chart_values) if chart_values else 0

    _style_chart_axes(ax, show_grid)

    if chart_type == "bar":
        ax.bar(x_positions, chart_values, color=color, width=0.62)
    elif chart_type == "line":
        ax.plot(
            x_positions, chart_values, color=color, linewidth=line_width,
            marker="o" if show_markers else None, markersize=4.5,
            markerfacecolor="white", markeredgecolor=color, markeredgewidth=1.4,
            solid_capstyle="round",
        )
        ax.set_ylim(0, max_val * 1.15 if max_val > 0 else 1)
    elif chart_type == "area":
        ax.fill_between(x_positions, chart_values, color=color, alpha=0.22)
        ax.plot(
            x_positions, chart_values, color=color, linewidth=line_width,
            marker="o" if show_markers else None, markersize=4.5,
            markerfacecolor="white", markeredgecolor=color, markeredgewidth=1.4,
            solid_capstyle="round",
        )
        ax.set_ylim(0, max_val * 1.15 if max_val > 0 else 1)

    if show_values:
        for xi, val in zip(x_positions, chart_values):
            if not val:
                continue
            ax.annotate(
                f"{val:.{value_decimals}f}", (xi, val), textcoords="offset points", xytext=(0, 4),
                ha="center", fontsize=7, color="#3a3f45",
            )

    ax.set_ylabel(chart_ylabel)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(chart_labels)
    if n > 15:
        ax.tick_params(axis="x", labelrotation=90, labelsize=7)
    else:
        ax.tick_params(axis="x", labelrotation=45, labelsize=8)


def render_report_pdf(elements, context, chart_labels, chart_values, chart_ylabel):
    """Tekent één PDF-pagina volgens `elements` (lijst van dicts zoals in
    branding.pdf_template.elements) en retourneert de PDF als bytes."""
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(PAGE_WIDTH_IN, PAGE_HEIGHT_IN))

        for el in elements or []:
            x = max(0.0, min(100.0, float(el.get("x", 0)))) / 100.0
            y = max(0.0, min(100.0, float(el.get("y", 0)))) / 100.0
            w = max(1.0, min(100.0, float(el.get("width", 10)))) / 100.0
            h = max(1.0, min(100.0, float(el.get("height", 10)))) / 100.0
            # CSS-achtige coördinaten (oorsprong linksboven) omzetten naar
            # matplotlib figure-coördinaten (oorsprong linksonder).
            bottom = max(0.0, 1.0 - y - h)

            etype = el.get("type")
            if etype == "text":
                ax = fig.add_axes([x, bottom, w, h])
                ax.axis("off")
                _draw_text_element(fig, ax, el, context, el.get("height", 10))
            elif etype == "image":
                img_path = images_module.image_path(el.get("image_id"))
                if img_path:
                    try:
                        img = mpimg.imread(img_path)
                    except (FileNotFoundError, OSError, ValueError):
                        img = None
                    if img is not None:
                        ax = fig.add_axes([x, bottom, w, h])
                        ax.imshow(img)
                        ax.axis("off")
            elif etype == "chart":
                ax = fig.add_axes([x, bottom, w, h])
                _draw_chart(ax, el, chart_labels, chart_values, chart_ylabel)
            elif etype == "line":
                ax = fig.add_axes([x, bottom, w, h])
                ax.axis("off")
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                orientation = el.get("orientation", "horizontal")
                line_color = el.get("line_color", "#c7ccd1")
                line_thickness = el.get("line_thickness", 1.5)
                if orientation == "vertical":
                    ax.plot([0.5, 0.5], [0, 1], color=line_color, linewidth=line_thickness, solid_capstyle="butt")
                else:
                    ax.plot([0, 1], [0.5, 0.5], color=line_color, linewidth=line_thickness, solid_capstyle="butt")
            elif etype == "rect":
                ax = fig.add_axes([x, bottom, w, h])
                ax.axis("off")
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                facecolor = el.get("fill_color", "#03a9f4") if el.get("has_fill") else "none"
                if el.get("has_border", True):
                    edgecolor = el.get("border_color", "#111111")
                    linewidth = el.get("border_width", 1.5)
                else:
                    edgecolor = "none"
                    linewidth = 0
                ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=facecolor, edgecolor=edgecolor, linewidth=linewidth))

        pdf.savefig(fig)
        plt.close(fig)
    buf.seek(0)
    return buf.read()
