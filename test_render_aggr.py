import dearpygui.dearpygui as dpg
import random

ALLIANCES = [
    {"name": "Goonswarm Federation", "color": (255, 80, 80)},
    {"name": "Pandemic Horde", "color": (100, 150, 255)},
    {"name": "TEST Alliance Please Ignore", "color": (80, 255, 80)},
    {"name": "Brave Collective", "color": (255, 165, 0)},
    {"name": "Northern Coalition.", "color": (200, 100, 255)},
]

CORPS = [
    {"name": "KarmaFleet", "alliance": "Goonswarm Federation"},
    {"name": "Ascendance", "alliance": "Goonswarm Federation"},
    {"name": "Pandemic Horde Inc.", "alliance": "Pandemic Horde"},
    {"name": "Dreddit", "alliance": "TEST Alliance Please Ignore"},
    {"name": "Brand Newbros", "alliance": "TEST Alliance Please Ignore"},
    {"name": "Brave Newbies Inc.", "alliance": "Brave Collective"},
    {"name": "NC. Corp", "alliance": "Northern Coalition."},
    {"name": "Random Corp 1", "alliance": None},
    {"name": "Random Corp 2", "alliance": None},
]

collapse_state = {"corps": False}

def gen_data():
    alliance_map = {a["name"]: a["color"] for a in ALLIANCES}
    active_alliances = random.sample(ALLIANCES, random.randint(2, len(ALLIANCES)))
    active_alliance_names = {a["name"] for a in active_alliances}
    alliance_counts = {a["name"]: random.randint(5, 50) for a in active_alliances}
    corp_data = []
    for c in CORPS:
        if random.random() < 0.3:
            continue
        cnt = random.randint(1, 20)
        alliance = c["alliance"] if c["alliance"] in active_alliance_names else None
        color = alliance_map.get(alliance, (200, 200, 200))
        corp_data.append({"name": c["name"], "alliance": alliance, "count": cnt, "color": color})
    return alliance_counts, corp_data, alliance_map

def create_text_theme(color):
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, color)
    return theme

def create_header_theme():
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvCollapsingHeader):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (40, 40, 40, 200))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (60, 60, 60, 200))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (50, 50, 50, 200))
    return theme

def create_compact_theme():
    with dpg.theme() as theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 2, 1)
    return theme

def save_collapse_state():
    if dpg.does_item_exist("corp_header"):
        collapse_state["corps"] = dpg.get_value("corp_header")
    for a in ALLIANCES:
        tag = f"alliance_corps_{a['name']}"
        if dpg.does_item_exist(tag):
            collapse_state[a["name"]] = dpg.get_value(tag)

def render_aggregated(alliance_counts, corp_data, alliance_map):
    save_collapse_state()
    
    if dpg.does_item_exist("content"):
        dpg.delete_item("content")
    
    header_theme = create_header_theme()
    
    corps_by_alliance = {}
    no_alliance_corps = []
    for c in corp_data:
        if c["alliance"]:
            corps_by_alliance.setdefault(c["alliance"], []).append(c)
        else:
            no_alliance_corps.append(c)
    
    with dpg.group(tag="content", parent="main"):
        total = sum(alliance_counts.values())
        dpg.add_text(f"Total Pilots: {total}", tag="header_txt")
        dpg.bind_item_theme("header_txt", create_text_theme((0, 255, 0)))
        dpg.add_separator()
        
        with dpg.group(horizontal=True):
            with dpg.group(tag="left_col", width=200):
                dpg.add_text("Alliances:", tag="alliance_label")
                dpg.bind_item_theme("alliance_label", create_text_theme((255, 255, 0)))
                
                sorted_alliances = sorted(alliance_counts.items(), key=lambda x: -x[1])
                for alliance, cnt in sorted_alliances:
                    color = alliance_map.get(alliance, (200, 200, 200))
                    tag = f"alliance_{alliance}"
                    dpg.add_text(f"  {alliance}: {cnt}", tag=tag)
                    dpg.bind_item_theme(tag, create_text_theme(color))
            
            with dpg.group(tag="right_col"):
                is_open = collapse_state.get("corps", False)
                with dpg.collapsing_header(label="Corporations", default_open=is_open, tag="corp_header"):
                    dpg.bind_item_theme("corp_header", header_theme)
                    
                    for alliance in sorted(corps_by_alliance.keys()):
                        corps = sorted(corps_by_alliance[alliance], key=lambda x: -x["count"])
                        color = alliance_map.get(alliance, (200, 200, 200))
                        alliance_open = collapse_state.get(alliance, False)
                        tag = f"alliance_corps_{alliance}"
                        with dpg.collapsing_header(label=f"{alliance}", default_open=alliance_open, tag=tag, indent=10):
                            dpg.bind_item_theme(tag, header_theme)
                            for i, c in enumerate(corps):
                                ctag = f"corp_{alliance}_{i}"
                                dpg.add_text(f"  {c['name']}: {c['count']}", tag=ctag)
                                dpg.bind_item_theme(ctag, create_text_theme(color))
                    
                    if no_alliance_corps:
                        for i, c in enumerate(no_alliance_corps):
                            ctag = f"corp_none_{i}"
                            dpg.add_text(f"  {c['name']}: {c['count']}", tag=ctag)
                            dpg.bind_item_theme(ctag, create_text_theme((200, 200, 200)))

def refresh_data(sender, app_data, user_data):
    alliance_counts, corp_data, alliance_map = gen_data()
    render_aggregated(alliance_counts, corp_data, alliance_map)

dpg.create_context()

with dpg.font_registry():
    default_font = dpg.add_font("C:/Windows/Fonts/arial.ttf", 16)
dpg.bind_font(default_font)

dpg.create_viewport(title="Aggregated Mode Test", width=550, height=400)
dpg.setup_dearpygui()

with dpg.window(tag="main", label="Aggregated View"):
    dpg.add_button(label="Refresh Data", callback=refresh_data)
    dpg.add_separator()

compact_theme = create_compact_theme()
dpg.bind_item_theme("main", compact_theme)

dpg.set_primary_window("main", True)
dpg.show_viewport()
dpg.render_dearpygui_frame()

alliance_counts, corp_data, alliance_map = gen_data()
render_aggregated(alliance_counts, corp_data, alliance_map)

while dpg.is_dearpygui_running():
    dpg.render_dearpygui_frame()

dpg.destroy_context()
