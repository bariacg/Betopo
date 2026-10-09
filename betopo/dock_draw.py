# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Pixel layout and GPU drawing for the workspace's bottom command panel."""
import math

import blf
import gpu
from gpu_extras.batch import batch_for_shader

_shader = None


def layout(width, height, left_inset, right_inset, scale, items):
    available = width - left_inset - right_inset
    padding, gap, bottom = 10 * scale, 5 * scale, 12 * scale
    usable = available - 2 * padding
    empty = {'rect': (0, 0, 0, 0), 'buttons': []}
    if not items or usable < 40 or height < 60:
        return empty
    button_width = min(140 * scale, usable)
    columns = min(len(items), max(1, int((usable + gap) // (button_width + gap))))
    rows = math.ceil(len(items) / columns)
    # Keep every command when a viewport is resized; shrink height rather than
    # silently dropping the last row of tools.
    button_height = min(54 * scale, (height - bottom - 2 * padding - (rows - 1) * gap) / rows)
    if button_height < 22:
        return empty
    panel_width = columns * button_width + (columns - 1) * gap + 2 * padding
    panel_height = rows * button_height + (rows - 1) * gap + 2 * padding
    x = left_inset + (available - panel_width) / 2
    buttons = []
    for index, item in enumerate(items):
        row, column = divmod(index, columns)
        buttons.append({
            'id': item['id'], 'label': item['label'],
            'rect': (x + padding + column * (button_width + gap),
                     bottom + padding + (rows - 1 - row) * (button_height + gap),
                     button_width, button_height),
        })
    return {'rect': (x, bottom, panel_width, panel_height), 'buttons': buttons,
            'scale': scale}


def draw_rect(x, y, width, height, color):
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(_shader, 'TRIS',
                             {'pos': ((x, y), (x + width, y), (x, y + height), (x + width, y + height))},
                             indices=((0, 1, 2), (2, 1, 3)))
    _shader.bind()
    _shader.uniform_float('color', color)
    batch.draw(_shader)


def fitted_size(text, width, height, size):
    blf.size(0, size)
    tw, th = blf.dimensions(0, text)
    size = max(7, min(size, size * width / max(1, tw), size * height / max(1, th)))
    blf.size(0, size)
    return blf.dimensions(0, text)


def draw(layout, active_id=None, hover_id=None, disabled_ids=(), scale=1.0):
    if not layout or not layout['buttons']:
        return
    previous_blend = gpu.state.blend_get()
    gpu.state.blend_set('ALPHA')
    try:
        px, py, pw, ph = layout['rect']
        draw_rect(px, py, pw, ph, (.07, .08, .09, .96))
        for button in layout['buttons']:
            x, y, width, height = button['rect']
            identifier = button['id']
            if identifier in disabled_ids:
                background, foreground = (.12, .13, .14, 1), (.47, .49, .51, 1)
            elif identifier == active_id:
                background, foreground = (.05, .36, .55, 1), (1, 1, 1, 1)
            elif identifier == hover_id:
                background, foreground = (.29, .32, .35, 1), (1, 1, 1, 1)
            else:
                background, foreground = (.18, .20, .22, 1), (.92, .94, .96, 1)
            draw_rect(x, y, width, height, background)
            label = button['label']
            tw, th = fitted_size(label, width - 16 * scale, height - 10, 17 * scale)
            blf.color(0, *foreground)
            blf.position(0, x + (width - tw) / 2, y + (height - th) / 2, 0)
            blf.draw(0, label)

    finally:
        gpu.state.blend_set(previous_blend)
