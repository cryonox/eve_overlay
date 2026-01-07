import dearpygui.dearpygui as dpg
import webbrowser

PILOTS = [
    {"name": "Vexor Navy Issue", "color": (255, 80, 80), "tag_color": (255, 0, 0), "url": "https://zkillboard.com/character/123/"},
    {"name": "BluePilot42", "color": (100, 150, 255), "tag_color": None, "url": "https://zkillboard.com/character/456/"},
    {"name": "NeutralDude", "color": (200, 200, 200), "tag_color": (128, 128, 128), "url": "https://zkillboard.com/character/789/"},
    {"name": "GreenFriendly", "color": (80, 255, 80), "tag_color": (0, 200, 0), "url": "https://zkillboard.com/character/101/"},
    {"name": "OrangeWarning", "color": (255, 165, 0), "tag_color": None, "url": "https://zkillboard.com/character/102/"},
]


def on_click(sender, app_data, user_data):
    dpg.set_value(sender, False)
    webbrowser.open(user_data)

def create_pilot_theme(base_color):
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Text, base_color)
            dpg.add_theme_color(dpg.mvThemeCol_Header, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (80, 80, 80, 150))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (80, 80, 80, 150))
    return theme

def draw_pilot_row(parent, pilot, idx):

    TAG_W = 4
    row_h = dpg.get_text_size(pilot["name"])[1]
    
    with dpg.group(horizontal=True, parent=parent):
        if pilot["tag_color"]:
            with dpg.drawlist(width=TAG_W, height=row_h):
                dpg.draw_rectangle([0, 0], [TAG_W, row_h], fill=pilot["tag_color"], color=pilot["tag_color"])
        else:
            dpg.add_spacer(width=TAG_W)
        
        sel_tag = f"pilot_{idx}"
        dpg.add_selectable(label=pilot["name"], tag=sel_tag, callback=on_click, user_data=pilot["url"])
        dpg.bind_item_theme(sel_tag, create_pilot_theme(pilot["color"]))

dpg.create_context()

with dpg.font_registry():
    default_font = dpg.add_font("C:/Windows/Fonts/arial.ttf", 16)
dpg.bind_font(default_font)

dpg.create_viewport(title="Pilot List Test", width=400, height=300)
dpg.setup_dearpygui()

with dpg.window(tag="main", label="Pilots"):
    dpg.add_text("Pilot List - Click to open zkill", color=(255, 255, 0))
    dpg.add_separator()
    with dpg.group(tag="pilot_list"):
        pass

dpg.set_primary_window("main", True)
dpg.show_viewport()
dpg.render_dearpygui_frame()

for i, p in enumerate(PILOTS):
    draw_pilot_row("pilot_list", p, i)

while dpg.is_dearpygui_running():
    dpg.render_dearpygui_frame()

dpg.destroy_context()
