"""Shared accessible web styling guided by Apple's Human Interface Guidelines."""
import re
from app.webpage.templates import load_asset
PALETTES = {
    'light': {'bg':'#f5f5f7','panel':'#ffffff','surface':'#f2f2f7','control':'#ffffff',
              'line':'#d2d2d7','control-line':'#85858a','text':'#1d1d1f','muted':'#606067','accent':'#005bb5',
              'primary':'#0066cc','primary-hover':'#0055aa','primary-pressed':'#004b96','on-primary':'#ffffff',
              'green':'#237537','red':'#b42324','warning':'#855000','hover':'#e8e8ed',
              'pressed':'#e5e5ea','glass':'rgba(245,245,247,.88)','scrim':'rgba(0,0,0,.32)'},
    'dark': {'bg':'#000000','panel':'#1c1c1e','surface':'#2c2c2e','control':'#1c1c1e',
             'line':'#48484a','control-line':'#8e8e93','text':'#f5f5f7','muted':'#b5b5bc','accent':'#82b6ff',
             'primary':'#0066cc','primary-hover':'#0055aa','primary-pressed':'#004b96','on-primary':'#ffffff',
             'green':'#76d98d','red':'#ff9999','warning':'#f0c675','hover':'#3a3a3c',
             'pressed':'#343436','glass':'rgba(28,28,30,.88)','scrim':'rgba(0,0,0,.64)'},
}


def _tokens(palette):
    return ';'.join('--'+key+':'+value for key,value in palette.items())


DESIGN_CSS = ':root{'+_tokens(PALETTES['light'])+'}\n' + '@media(prefers-color-scheme:dark){:root:not([data-appearance="light"]){'+_tokens(PALETTES['dark'])+'}}\n' + ':root[data-appearance="light"]{'+_tokens(PALETTES['light'])+';color-scheme:light}\n:root[data-appearance="dark"]{'+_tokens(PALETTES['dark'])+';color-scheme:dark}\n' + load_asset("design-system.css")



def apply_appearance(page, appearance='system'):
    """Choose the saved appearance before first paint, including public sign-in."""
    if appearance not in ('system', 'light', 'dark'):
        appearance = 'system'
    page = page.replace('<html lang="en">', '<html lang="en" data-appearance="'+appearance+'">', 1)
    if appearance != 'system':
        colors = iter([PALETTES[appearance]['bg']])
        def theme_color(match):
            color = next(colors, None)
            return '<meta name="theme-color" content="'+color+'">' if color else ''
        page = re.sub(r'<meta name="theme-color"[^>]*>', theme_color, page)
    return page
