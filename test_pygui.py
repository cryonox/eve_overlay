import dearpygui.dearpygui as dpg
from overlay import OverlayWindow, WindowManager
from config import C
import random
import time
import math

WIN_TITLE = "overlay"
win_mgr = WindowManager(WIN_TITLE, C)

def on_overlay_toggle(enabled):
    if enabled:
        dpg.configure_item("status", default_value="OVERLAY MODE (Alt+Shift+T)", color=(0, 255, 0))
    else:
        dpg.configure_item("status", default_value="NORMAL MODE (Alt+Shift+T)", color=(255, 0, 0))

overlay = OverlayWindow(WIN_TITLE, on_toggle=on_overlay_toggle)


dpg.create_context()

with dpg.font_registry():
    default_font = dpg.add_font("C:/Windows/Fonts/arial.ttf", int(16 * win_mgr.dpi_scale))
dpg.bind_font(default_font)

win_x, win_y, win_w, win_h = win_mgr.load()
print(f"Loading window state: {win_x}, {win_y}, {win_w}, {win_h}")
dpg.create_viewport(title=WIN_TITLE, width=win_w, height=win_h, always_on_top=True, clear_color=overlay.colorkey_rgba, x_pos=win_x, y_pos=win_y)
dpg.set_viewport_resize_callback(lambda: None)
dpg.setup_dearpygui()

COLORS = [(255, 0, 0), (0, 255, 0), (255, 255, 0), (0, 255, 255), (255, 0, 255), (255, 165, 0)]
WORDS = ["APPLE", "BANANA", "CHERRY", "GRAPE", "LEMON", "MANGO", "ORANGE", "PEACH", "PLUM", "MELON"]
last_update = 0

FONT_SIZE = 20
CHAR_W = 8

def random_color():
    return (random.randint(50, 255), random.randint(50, 255), random.randint(50, 255))

def generate_random_lines():
    num_lines = random.randint(5, 10)
    lines = []
    for i in range(num_lines):
        word = random.choice(WORDS)
        val = random.randint(0, 99)
        lines.append(f"Char{i+1}: {word} - {val}")
    return lines

def draw_all_lines(parent, lines):
    total_h = len(lines) * FONT_SIZE
    with dpg.drawlist(width=400, height=total_h, parent=parent):
        for row, text in enumerate(lines):
            y = row * FONT_SIZE
            c = random_color()
            for i, ch in enumerate(text):
                x = i * CHAR_W
                dpg.draw_text([x, y], ch, color=c, size=FONT_SIZE)

def update_dynamic_text():
    global last_update
    cur_time = time.time()
    if cur_time - last_update < 1.0:
        return
    last_update = cur_time

    for child in dpg.get_item_children("left_column", 1) or []:
        dpg.delete_item(child)
    for child in dpg.get_item_children("right_column", 1) or []:
        dpg.delete_item(child)

    lines = generate_random_lines()
    draw_all_lines("left_column", lines)
    for text in lines:
        dpg.add_text(text, color=random_color(), parent="right_column")

with dpg.window(tag="main", no_title_bar=True, no_move=True, no_resize=True, no_background=True, no_scrollbar=True):
    dpg.bind_item_theme("main", dpg.add_theme(tag="no_border"))
    with dpg.theme_component(dpg.mvAll, parent="no_border"):
        dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 0)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 0, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    dpg.add_text("Alt+Shift+T to toggle transparency", color=(255, 255, 0))
    dpg.add_text("NORMAL MODE (Alt+Shift+T)", tag="status", color=(255, 0, 0))
    dpg.add_separator()

    with dpg.theme(tag="green_checkbox"):
        with dpg.theme_component(dpg.mvCheckbox):
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (0, 255, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (0, 80, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (0, 120, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (0, 160, 0))
    with dpg.group(horizontal=True):
        dpg.add_checkbox(tag='chk_box')
        dpg.bind_item_theme('chk_box', 'green_checkbox')
        dpg.add_text("test", color=(255, 0, 0))
        dpg.add_text("test2", color=(128, 0, 128))

    with dpg.group(horizontal=True):
        dpg.add_checkbox(tag='chk_box1')
        dpg.bind_item_theme('chk_box1', 'green_checkbox')
        dpg.add_text("   test", color=(255, 0, 0))
        dpg.add_text("test2", color=(128, 0, 128))

    dpg.add_separator()
    dpg.add_text("Animated Text", tag="anim_text", color=(255, 0, 0))
    with dpg.plot(height=150, width=-1, no_title=True, no_menus=True, no_box_select=True, no_mouse_pos=True):
        dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis", no_tick_labels=True, no_tick_marks=True)
        with dpg.plot_axis(dpg.mvYAxis, tag="y_axis", no_tick_labels=True, no_tick_marks=True):
            dpg.add_line_series([], [], tag="series")
    with dpg.group(horizontal=True):
        with dpg.child_window(width=400, border=False, tag="left_wrapper"):
            dpg.add_text("NEW STYLE", color=(255, 255, 0))
            with dpg.group(tag="left_column"):
                pass
        with dpg.group():
            with dpg.collapsing_header(label="collapsable", default_open=True):
                with dpg.group(tag="right_column"):
                    pass
    dpg.bind_item_theme("left_column", "no_border")
    dpg.bind_item_theme("right_column", "no_border")


graph_data = []
MAX_POINTS = 100
last_graph_update = 0

def update_graph():
    global last_graph_update
    cur = time.time()
    if cur - last_graph_update < 0.1:
        return
    last_graph_update = cur
    graph_data.append(random.random())
    if len(graph_data) > MAX_POINTS:
        graph_data.pop(0)
    dpg.set_value("series", [list(range(len(graph_data))), graph_data])
    dpg.fit_axis_data("x_axis")
    dpg.fit_axis_data("y_axis")

dpg.set_primary_window("main", True)
dpg.show_viewport()

dpg.render_dearpygui_frame()
win_mgr.apply()

print(f"Initial state: {win_mgr.get_state()}")
while dpg.is_dearpygui_running():
    t = (math.sin(time.time() * 2) + 1) / 2
    r, b = int(255 * (1 - t)), int(255 * t)
    dpg.configure_item("anim_text", color=(r, 0, b))
    update_dynamic_text()
    update_graph()
    overlay.process_hotkey()
    win_mgr.check_and_save()
    dpg.render_dearpygui_frame()

overlay.cleanup()
dpg.destroy_context()
