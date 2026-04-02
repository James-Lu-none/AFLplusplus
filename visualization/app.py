import dash
from dash import Input, Output, State, html
import dash_cytoscape as cyto
import os
from collections import deque
from datetime import datetime

from config import (
    CFG_EDGES_FILE, 
    BB_LINES_MAP_FILE,
    TARGET_BB_MAP_FILE,
    TARGET_PROCESS_NAME, 
    DIST_KV_SHM_NAME, 
    MIN_REFRESH_INTERVAL,
    MAX_TARGETS,
    DEFAULT_TOP_N,
    DEFAULT_LLM_THRESHOLD
)
from core.models import SharedDistKVStore
from core.shm_handler import (
    get_afl_shm_ptr, 
    start_collector, 
    accumulated_map, 
    map_lock,
    dist_shm_ptr
)
from core.cfg_processor import load_cfg_data, load_cfg_with_graphviz, load_bb_lines_map, load_target_bb_map
from components.visuals import get_default_stylesheet, generate_coverage_heatmap
from components.ui_layout import create_layout

# Initialize Dash app
app = dash.Dash(__name__)

# Global state for SHM, LLM Timers, and Logs
current_dist_shm_ptr = None
target_timers = [0] * MAX_TARGETS
prev_active_counts = [0] * MAX_TARGETS
app_logs = deque(maxlen=100)

def log_message(msg):
    """Adds a timestamped message to the log buffer."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    app_logs.appendleft(f"[{timestamp}] {msg}")

def trigger_llm_call(target_idx, entry, bb_info):
    """
    Placeholder for triggering an LLM call when a target is stuck.
    """
    msg = f"Target {target_idx} (BB {entry.last_bb_id}) is stuck. Triggering LLM... BB Info: {bb_info}"
    print(f"[LLM TRIGGER] {msg}")
    log_message(f"LLM TRIGGER: {msg}")
    # In a real scenario, you would call your LLM API here.
    pass

@app.callback(
    Output('refresh-timer', 'interval'),
    [Input('interval-setting', 'value')]
)
def update_refresh_rate(value):
    if value is None or value < MIN_REFRESH_INTERVAL:
        return 1000
    return value

@app.callback(
    [Output('cfg-graph', 'stylesheet'),
     Output('live-status-info', 'children'),
     Output('coverage-heatmap', 'figure'),
     Output('coverage-stats', 'children'),
     Output('log-panel', 'children')],
    [Input('refresh-timer', 'n_intervals')],
    [State('llm-threshold-input', 'value')]
)
def update_live_data(n, llm_threshold):
    global current_dist_shm_ptr, target_timers, prev_active_counts
    
    if llm_threshold is None:
        llm_threshold = DEFAULT_LLM_THRESHOLD
    
    if not current_dist_shm_ptr:
        current_dist_shm_ptr = get_afl_shm_ptr(TARGET_PROCESS_NAME, DIST_KV_SHM_NAME)
        if not current_dist_shm_ptr:
            return dash.no_update, "SHM not found. Check AFL++ status.", dash.no_update, ""

    try:
        dist_kv = SharedDistKVStore.from_address(current_dist_shm_ptr)
    except Exception:
        current_dist_shm_ptr = None
        return dash.no_update, "Error reading SHM.", dash.no_update, ""

    base_style = get_default_stylesheet()
    status_elements = []

    # Distance Entries Table
    table_header = [
        html.Thead(html.Tr([
            html.Th("Target", style={'textAlign': 'left', 'padding': '5px', 'borderBottom': '1px solid #444'}),
            html.Th("Target BB", style={'textAlign': 'left', 'padding': '5px', 'borderBottom': '1px solid #444'}),
            html.Th("Min Dist", style={'textAlign': 'left', 'padding': '5px', 'borderBottom': '1px solid #444'}),
            html.Th("Last BB", style={'textAlign': 'left', 'padding': '5px', 'borderBottom': '1px solid #444'}),
            html.Th("Seed Len", style={'textAlign': 'left', 'padding': '5px', 'borderBottom': '1px solid #444'}),
            html.Th("Timer (s)", style={'textAlign': 'left', 'padding': '5px', 'borderBottom': '1px solid #444'})
        ]))
    ]

    rows = []
    bb_map = load_bb_lines_map(BB_LINES_MAP_FILE)
    target_bb_map = load_target_bb_map(TARGET_BB_MAP_FILE)
    
    for i in range(MAX_TARGETS):
        entry = dist_kv.entries[i]
        # Show all entries as per user's manual change, but show hit count
        curr_bb = str(entry.last_bb_id)
        
        target_bb = target_bb_map.get(i, "N/A")
        target_bb_info = f"{target_bb}"
        if target_bb in bb_map:
            file, start, end = bb_map[target_bb]
            target_bb_info = f"{file}:{start}-{end} ({target_bb})"
            
        # Highlight target BBs in the graph as red
        if target_bb != "N/A":
            base_style.append({
                'selector': f'node[id = "{target_bb}"]',
                'style': {
                    'background-color': '#ff4444', 
                    'width': '35px', 
                    'height': '35px', 
                    'border-width': '2px', 
                    'border-color': 'white'
                }
            })

        # Highlight top targets with active seeds in the graph
        if entry.active_count > 0 and i < 5:
            base_style.append({
                'selector': f'node[id = "{curr_bb}"]',
                'style': {
                    'background-color': '#ffc107', 
                    'width': '45px', 
                    'height': '45px', 
                    'border-width': '2px', 
                    'border-color': 'white'
                }
            })
        
        # Timer logic: Reset if active_count increases, else increment
        if target_bb_info != "N/A": 
            if entry.active_count > prev_active_counts[i]:
                target_timers[i] = 0
                prev_active_counts[i] = entry.active_count
            else:
                # Estimate elapsed time based on refresh interval (approx 1s if configured)
                # Actually we can just increment by 1 if we assume check happens every 1s
                target_timers[i] += 1
            
            if target_timers[i] >= llm_threshold:
                trigger_llm_call(i, entry, target_bb_info)
                target_timers[i] = 0

        rows.append(html.Tr([
            html.Td(f"T{i}", style={'padding': '5px', 'color': '#00ff00' if entry.active_count > 0 else '#888'}),
            html.Td(f"{target_bb_info}", style={'padding': '5px', 'fontSize': '10px', 'color': '#ff4444', 'wordBreak': 'break-all', 'whiteSpace': 'normal'}),
            html.Td(f"{entry.min_distance}", style={'padding': '5px'}),
            html.Td(f"{curr_bb}", style={'padding': '5px'}),
            html.Td(f"{entry.seed_len}", style={'padding': '5px'}),
            html.Td(f"{target_timers[i]}s", style={
                'padding': '5px', 
                'color': '#ff4444' if target_timers[i] > llm_threshold / 2 else '#00ff00',
                'fontWeight': 'bold' if target_timers[i] > llm_threshold / 2 else 'normal'
            })
        ]))

    if not rows:
        status_elements = [html.P("No active targets found.", style={'color': '#888'})]
    else:
        table_body = [html.Tbody(rows)]
        status_elements = [
            html.Table(
                table_header + table_body, 
                style={
                    'width': '100%', 
                    'fontSize': '12px', 
                    'borderCollapse': 'collapse',
                    'marginTop': '10px'
                }
            )
        ]

    # Coverage Heatmap
    fig, stats_text = generate_coverage_heatmap(accumulated_map, map_lock)

    log_content = [html.Div(log) for log in app_logs]

    return base_style, status_elements, fig, stats_text, log_content

@app.callback(
    Output('node-data-display', 'children'),
    [Input('cfg-graph', 'tapNodeData')],
    [State('refresh-timer', 'n_intervals')]
)
def display_node_data(data, n):
    global current_dist_shm_ptr
    if not data or not current_dist_shm_ptr:
        return "Click a node to see if it's the current bottleneck seed."
    
    try:
        dist_kv = SharedDistKVStore.from_address(current_dist_shm_ptr)
    except Exception:
        return "Error accessing SHM data."

    clicked_bb = data['id']
    bb_map = load_bb_lines_map(BB_LINES_MAP_FILE)
    
    source_info = f"BB {clicked_bb}"
    if clicked_bb in bb_map:
        file, start, end = bb_map[clicked_bb]
        source_info = f"{file}:{start}-{end} ({clicked_bb})"

    for i in range(MAX_TARGETS):
        entry = dist_kv.entries[i]
        if entry.active_count > 0 and str(entry.last_bb_id) == clicked_bb:
            content = bytes(entry.seed_content[:entry.seed_len])
            return html.Div([
                html.P(f"Seed associated with {source_info}:"),
                html.Code(content.hex(), style={'color': '#ff79c6'}),
                html.P(f"Seed in ASCII: {content.decode(errors='replace')}", style={'color': '#8be9fd'})
            ])
            
    return f"No active seed stopped at {source_info} currently."

@app.callback(
    Output('cfg-graph', 'elements'),
    [Input('top-n-input', 'value'),
     Input('cfg-enabled-toggle', 'value')]
)
def update_cfg_elements(top_n, cfg_enabled):
    if not cfg_enabled or 'enabled' not in cfg_enabled:
        return []
    
    if top_n is None:
        top_n = DEFAULT_TOP_N
    return load_cfg_with_graphviz(CFG_EDGES_FILE, top_n)

@app.callback(
    Output('cfg-graph', 'style'),
    [Input('cfg-enabled-toggle', 'value')]
)
def toggle_cfg_visibility(cfg_enabled):
    base_style = {'width': '100%', 'height': '100%', 'border': '1px solid #444'}
    if not cfg_enabled or 'enabled' not in cfg_enabled:
        base_style['display'] = 'none'
    return base_style

app.layout = create_layout(get_default_stylesheet())

if __name__ == '__main__':
    # Start the SHM collector thread
    start_collector()
    
    # Run Dash app
    app.run(host='0.0.0.0', port=8050, debug=False)
