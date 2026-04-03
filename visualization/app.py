import dash
from dash import Input, Output, State, html, ALL
import dash_cytoscape as cyto
import os
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from llm import trigger_llm_call
from core.logger import app_logs, log_message

from config import (
    CFG_EDGES_FILE, 
    BB_LINES_MAP_FILE,
    TARGET_BB_MAP_FILE,
    TARGET_PROCESS_NAME, 
    DIST_KV_SHM_NAME, 
    MIN_REFRESH_INTERVAL,
    MAX_TARGETS,
    DEFAULT_LLM_THRESHOLD,
    MIN_LLM_THRESHOLD,
    DEFAULT_LLM_ENDPOINT,
    DEFAULT_LLM_MODEL
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
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body { margin: 0; background-color: #121212; color: white; font-family: sans-serif; }
            .rc-slider-tooltip { display: none !important; }
            .rc-slider-rail { background-color: #333 !important; }
            .rc-slider-track { background-color: #6a5acd !important; }
            .rc-slider-handle { background-color: #6a5acd !important; border: 2px solid #6a5acd !important; }
            .rc-slider-mark-text { color: #888 !important; font-size: 10px !important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Global state for SHM, LLM Timers
current_dist_shm_ptr = None
target_timers = [0] * MAX_TARGETS
prev_active_counts = [0] * MAX_TARGETS

@app.callback(
    Output('interval-display', 'children'),
    Input('interval-setting', 'value')
)
def update_interval_display(val):
    return f"{val} ms"

@app.callback(
    Output('top-n-display', 'children'),
    Input('top-n-input', 'value')
)
def update_top_n_display(val):
    return val

@app.callback(
    Output('llm-threshold-display', 'children'),
    Input('llm-threshold-input', 'value')
)
def update_llm_display(val):
    return f"{val} s"

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
    [State('llm-threshold-input', 'value'),
     State('llm-endpoint-input', 'value'),
     State('llm-model-input', 'value'),
     State('selected-target-idx', 'data')]
)
def update_live_data(n, llm_threshold, llm_endpoint, llm_model, selected_idx):
    global current_dist_shm_ptr, target_timers, prev_active_counts
    
    if llm_threshold is None:
        llm_threshold = DEFAULT_LLM_THRESHOLD
    else:
        llm_threshold = max(MIN_LLM_THRESHOLD, llm_threshold)
    
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
            
        # make target BBs red in the graph
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

        # make targets last BBs yellow in the graph
        if entry.active_count > 0:
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
                # Snapshot data to pass to the thread
                data_snapshot = {
                    'last_bb_id': entry.last_bb_id,
                    'path_content': list(entry.path_content[:entry.path_len]),
                    'seed_content': bytes(entry.seed_content[:entry.seed_len])
                }
                threading.Thread(
                    target=trigger_llm_call, 
                    args=(i, data_snapshot, target_bb_info, llm_endpoint, llm_model),
                    daemon=True
                ).start()
                target_timers[i] = 0

        # Highlighting for Selected Target and Path
        if i == selected_idx:
            # Highlight target BB
            if target_bb != "N/A":
                base_style.append({
                    'selector': f'node[id = "{target_bb}"]',
                    'style': {
                        'label': 'TARGET',
                        'color': '#ffffff',
                        'font-weight': 'bold',
                        'font-size': '24px',
                        'text-outline-color': '#ff4444',
                        'text-outline-width': '2px',
                        'background-color': '#ffffff',
                        'width': '50px',
                        'height': '50px'
                    }
                })
            
            # Highlight execution path (nodes and edges)
            path = list(entry.path_content[:entry.path_len])
            for i_path, bb_id_val in enumerate(path):
                bb_id = str(bb_id_val)
                # Node highlight
                base_style.append({
                    'selector': f'node[id = "{bb_id}"]',
                    'style': {
                        'color': '#fffa00',
                        'font-weight': 'bold',
                        'font-size': '18px',
                        'border-width': '4px',
                        'border-color': '#fffa00',
                        'z-index': 9999
                    }
                })
                # Edge highlight (between current and next)
                if i_path < len(path) - 1:
                    next_bb_id = str(path[i_path + 1])
                    base_style.append({
                        'selector': f'edge[source = "{bb_id}"][target = "{next_bb_id}"]',
                        'style': {
                            'line-color': '#fffa00',
                            'width': '6px',
                            'line-style': 'solid',
                            'target-arrow-color': '#fffa00',
                            'target-arrow-shape': 'triangle',
                            'z-index': 9998
                        }
                    })

        rows.append(html.Tr(
            id={'type': 'target-row', 'index': i},
            n_clicks=0,
            style={
                'cursor': 'pointer',
                'backgroundColor': '#333' if i == selected_idx else 'transparent',
                'borderBottom': '1px solid #444'
            },
            children=[
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
            ]
        ))

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
    Output('selected-target-idx', 'data'),
    [Input({'type': 'target-row', 'index': ALL}, 'n_clicks')],
    [State('selected-target-idx', 'data')]
)
def update_selected_target(n_clicks_list, current_idx):
    ctx = dash.callback_context
    if not ctx.triggered or not n_clicks_list:
        return current_idx
    
    # Identify which target was clicked
    trigger = ctx.triggered[0]
    if not trigger['value'] or trigger['value'] == 0:
        return current_idx
        
    clicked_id = trigger['prop_id'].split('.')[0]
    try:
        import json
        clicked_idx = json.loads(clicked_id)['index']
        return clicked_idx
    except Exception:
        return current_idx

@app.callback(
    Output('target-data-display', 'children'),
    [Input('selected-target-idx', 'data'),
     Input('refresh-timer', 'n_intervals')]
)
def display_target_data(selected_idx, n):
    global current_dist_shm_ptr
    if selected_idx is None or selected_idx < 0 or not current_dist_shm_ptr:
        return "Click a target row in the table to see execution path and seed details."
    
    try:
        dist_kv = SharedDistKVStore.from_address(current_dist_shm_ptr)
        entry = dist_kv.entries[selected_idx]
    except Exception:
        return "Error accessing SHM data."

    bb_map = load_bb_lines_map(BB_LINES_MAP_FILE)
    target_bb_map = load_target_bb_map(TARGET_BB_MAP_FILE)
    
    target_bb = target_bb_map.get(selected_idx, "N/A")
    target_info = f"Target {selected_idx}: {target_bb}"
    if target_bb in bb_map:
        file, start, end = bb_map[target_bb]
        target_info = f"Target {selected_idx}: {file}:{start}-{end} ({target_bb})"

    seed_content = bytes(entry.seed_content[:entry.seed_len])
    path = list(entry.path_content[:entry.path_len])
    
    path_elements = []
    for bb_id_val in path:
        bb_id = str(bb_id_val)
        if bb_id in bb_map:
            f, s, e = bb_map[bb_id]
            path_elements.append(f"{f}:{s}-{e} ({bb_id})")
        else:
            path_elements.append(f"BB {bb_id}")

    return html.Div([
        html.H5(target_info, style={'color': '#ff4444'}),
        html.P(f"Min Distance: {entry.min_distance}", style={'fontSize': '14px'}),
        
        html.B("Execution Path:"),
        html.Div([
            html.P(" -> ".join(path_elements) if path_elements else "No path data recorded.", 
                   style={'color': '#8be9fd', 'fontSize': '11px'})
        ], style={'maxHeight': '150px', 'overflowY': 'auto', 'marginBottom': '10px'}),

        html.B("Seed Content (Hex):"),
        html.Code(seed_content.hex(), style={'color': '#ff79c6', 'display': 'block', 'fontSize': '10px'}),
        html.B("Seed Content (ASCII):"),
        html.P(seed_content.decode(errors='replace'), style={'color': '#50fa7b', 'fontSize': '11px'})
    ])

@app.callback(
    Output('cfg-graph', 'tapNodeData'),
    [Input('cfg-graph', 'tapNodeData')]
)
def reset_node_tap(data):
    # longer use tapNodeData after using selected-target-idx
    return data

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
