"""Gera os conceitos de logo Bigodds em SVG (sem fontes: letras desenhadas em traço) e um PNG de revisão."""
import re
BG, LIME, GREEN, INK = "#0B1F17", "#C6F432", "#2F8F5B", "#F2F5EE"
SW = 9  # espessura do traço

# bigode: metade direita preenchida, a esquerda é o espelho
HALF = ("M100 90 C112 74 142 70 160 84 C170 92 177 95 184 89 C190 84 190 74 183 70 "
        "C196 69 204 86 196 100 C184 118 154 120 136 113 C120 107 108 110 100 117 Z")
def moustache(fill, tf=""):
    return (f'<g transform="{tf}"><path d="{HALF}" fill="{fill}"/>'
            f'<path d="{HALF}" fill="{fill}" transform="translate(200,0) scale(-1,1)"/></g>')

def word(x, y, s, c_big, c_odds):
    """'bigodds' monolinha; x,y = canto superior esquerdo, s = escala (altura total ~ 82*s)."""
    st = f'fill="none" stroke-width="{SW}" stroke-linecap="round" stroke-linejoin="round"'
    big = (f'<path d="M10 40 V100" stroke="{c_big}" {st}/><circle cx="30" cy="80" r="20" stroke="{c_big}" {st}/>'
           f'<path d="M64 64 V100" stroke="{c_big}" {st}/><circle cx="64" cy="47" r="5.5" fill="{c_big}"/>'
           f'<circle cx="98" cy="80" r="20" stroke="{c_big}" {st}/><path d="M118 62 V106 A20 20 0 0 1 80 114" stroke="{c_big}" {st}/>')
    odds = (f'<circle cx="152" cy="80" r="20" stroke="{c_odds}" {st}/>'
            f'<circle cx="206" cy="80" r="20" stroke="{c_odds}" {st}/><path d="M226 40 V100" stroke="{c_odds}" {st}/>'
            f'<circle cx="260" cy="80" r="20" stroke="{c_odds}" {st}/><path d="M280 40 V100" stroke="{c_odds}" {st}/>'
            f'<path d="M322 66 C316 58 298 58 298 70 C298 81 324 78 324 90 C324 103 300 104 294 94" stroke="{c_odds}" {st}/>')
    return f'<g transform="translate({x},{y}) scale({s})">{big}{odds}</g>'

def svg(w, h, body, bg=None):
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{rect}{body}</svg>'

# Conceito 1 "Bigode": bigode lima centrado em quadrado verde escuro
icon1 = f'<rect width="200" height="200" rx="44" fill="{BG}"/>' + moustache(LIME, "translate(14,22) scale(0.86)")
# Conceito 2 "Trevo": 4 folhas-coração (quadrado + 2 semicírculos) com o bico no centro, uma em lima = a vantagem
def heart(c, r):
    return (f'<g transform="rotate({r} 100 100)" fill="{c}"><rect x="60" y="60" width="36" height="36"/>'
            f'<circle cx="60" cy="78" r="18"/><circle cx="78" cy="60" r="18"/></g>')
def clover(c_main, c_edge):
    return (f'<path d="M100 110 C100 150 106 166 124 176" stroke="{c_main}" stroke-width="8" stroke-linecap="round" fill="none"/>'
            + "".join(heart(c_edge if r == 90 else c_main, r) for r in (0, 90, 180, 270)))
icon2 = f'<rect width="200" height="200" rx="44" fill="{BG}"/>' + f'<g transform="translate(6,-4)">{clover(GREEN, LIME)}</g>'
# Conceito 3 "Cavalheiro": monóculo (o "o" de odds) + bigode
def gent(c_m, c_o):
    return (f'<circle cx="124" cy="74" r="24" stroke="{c_o}" stroke-width="9" fill="none"/>'
            f'<path d="M146 86 C156 96 160 104 162 112" stroke="{c_o}" stroke-width="4" stroke-linecap="round" fill="none" stroke-dasharray="1 7"/>'
            + moustache(c_m, "translate(30,66) scale(0.7)"))
icon3 = f'<rect width="200" height="200" rx="44" fill="{BG}"/>' + gent(LIME, INK)

files = {
    "conceito1_icone.svg": svg(200, 200, icon1),
    "conceito2_icone.svg": svg(200, 200, icon2),
    "conceito3_icone.svg": svg(200, 200, icon3),
    "wordmark_escuro.svg": svg(380, 150, word(25, 10, 1, INK, LIME), BG),
    "wordmark_claro.svg": svg(380, 150, word(25, 10, 1, BG, GREEN), "#FFFFFF"),
}
for n, s in files.items():
    open(n, "w").write(s)

# folha de revisão
icons=[icon1, icon2, icon3]
sheet = (f'<rect width="1200" height="980" fill="#E9ECE6"/>'
         + "".join(f'<g transform="translate({60 + i * 380},30) scale(1.3)">{b}</g>' for i, b in enumerate(icons))
         + "".join(f'<g transform="translate({40 + i * 380},330)"><rect width="360" height="130" rx="20" fill="{BG}"/>'
                   f'<g transform="translate(14,15) scale(0.5)">{b}</g>{word(130, 30, 0.62, INK, LIME)}</g>' for i, b in enumerate(icons))
         + f'<g transform="translate(40,500)"><rect width="540" height="210" rx="24" fill="{BG}"/>{word(40, 20, 1.4, INK, LIME)}</g>'
         + f'<g transform="translate(620,500)"><rect width="540" height="210" rx="24" fill="#FFFFFF"/>{word(40, 20, 1.4, BG, GREEN)}</g>'
         + "".join(f'<g transform="translate({40 + i * 380},750)">' + "".join(f'<g transform="translate({x},0) scale({sc})">{b}</g>' for x, sc in ((0, 0.9), (200, 0.48), (310, 0.24)))+'</g>' for i, b in enumerate(icons)))
open("revisao.svg", "w").write(svg(1200, 980, sheet))
import cairosvg; cairosvg.svg2png(url="revisao.svg", write_to="revisao.png")
print("ok")

# --- kit final: os 3 escolhidos + ícones da app ---
import os
os.makedirs("final", exist_ok=True)
def lockup(icon_body):
    return svg(720, 260, f'<g transform="translate(28,30) scale(1)">{icon_body}</g>{word(262, 56, 1.25, INK, LIME)}', BG)
final = {
    "final/bigodds_wordmark.svg": svg(560, 210, word(40, 20, 1.4, INK, LIME), BG),
    "final/bigodds_trevo.svg": lockup(icon2),
    "final/bigodds_cavalheiro.svg": lockup(icon3),
    "final/icone_trevo.svg": svg(200, 200, icon2),
    "final/icone_cavalheiro.svg": svg(200, 200, icon3),
}
for n, s in final.items():
    open(n, "w").write(s)
    cairosvg.svg2png(bytestring=s.encode(), write_to=n[:-4] + ".png", output_width=1200 if "icone" not in n else 512)
# ícones PWA: 192 e 512, e versão "maskable" com margem de segurança (o Android corta em círculo)
for name, body in (("trevo", icon2), ("cavalheiro", icon3)):
    for size in (192, 512):
        cairosvg.svg2png(bytestring=svg(200, 200, body).encode(), write_to=f"final/{name}-{size}.png", output_width=size)
    inner = re.sub(r'<rect width="200" height="200" rx="44" fill="[^"]+"/>', "", body)
    mask = svg(200, 200, f'<rect width="200" height="200" fill="{BG}"/><g transform="translate(20,20) scale(0.8)">{inner}</g>')
    cairosvg.svg2png(bytestring=mask.encode(), write_to=f"final/{name}-maskable-512.png", output_width=512)
# pré-visualização: ecrã inicial de telemóvel com os dois ícones
phone = (f'<rect width="900" height="560" fill="#E9ECE6"/>'
         f'<g transform="translate(40,40)"><rect width="380" height="480" rx="40" fill="#1B1B1F"/>'
         f'<g transform="translate(60,70) scale(0.6)">{icon2}</g><g transform="translate(200,70) scale(0.6)">{icon3}</g>'
         f'<g transform="translate(40,230)"><rect width="300" height="88" rx="18" fill="#2A2A30"/>'
         f'<g transform="translate(12,12) scale(0.32)">{icon2}</g>'
         f'<rect x="96" y="22" width="150" height="12" rx="6" fill="{INK}"/><rect x="96" y="46" width="180" height="10" rx="5" fill="{LIME}"/></g></g>'
         f'<g transform="translate(460,150)"><rect width="400" height="150" rx="24" fill="{BG}"/>{word(44, 10, 0.95, INK, LIME)}</g>')
cairosvg.svg2png(bytestring=svg(900, 560, phone).encode(), write_to="final/previsao_telemovel.png")
print(sorted(os.listdir("final")))
