import dash
from dash import Input, Output, State, html
import dash_cytoscape as cyto
import os

from config import (
    CFG_EDGES_FILE, 
    TARGET_PROCESS_NAME, 
    DIST_KV_SHM_NAME, 
    MIN_REFRESH_INTERVAL,
    MAX_TARGETS
)
from core.models import SharedDistKVStore
from core.shm_handler import (
    get_afl_shm_ptr, 
    start_collector, 
    accumulated_map, 
    map_lock,
    dist_shm_ptr
)
from core.cfg_processor import load_cfg_data, load_cfg_with_graphviz
from components.visuals import get_default_stylesheet, generate_coverage_heatmap
from components.ui_layout import create_layout

# Initialize Dash app
app = dash.Dash(__name__)

# Global state for SHM
# Note: dist_shm_ptr is managed here to avoid circular imports if needed, 
# although it could also be in shm_handler.
current_dist_shm_ptr = None

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
     Output('coverage-stats', 'children')],
    [Input('refresh-timer', 'n_intervals')]
)
def update_live_data(n):
    global current_dist_shm_ptr
    
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

    # Highlight top targets with active seeds
    for i in range(5):
        entry = dist_kv.entries[i]
        if entry.is_active:
            curr_bb = str(entry.last_bb_id)
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
            
            status_elements.append(html.P([
                html.Span(f"Target {i}: ", style={'color': '#00ff00'}),
                html.Span(f"Dist {entry.min_distance} | BB {curr_bb}")
            ]))

    # Coverage Heatmap
    fig, stats_text = generate_coverage_heatmap(accumulated_map, map_lock)

    return base_style, status_elements, fig, stats_text

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
    
    for i in range(MAX_TARGETS):
        entry = dist_kv.entries[i]
        if entry.is_active and str(entry.last_bb_id) == clicked_bb:
            content = bytes(entry.seed_content[:entry.seed_len])
            return html.Div([
                html.P(f"Seed associated with BB {clicked_bb}:"),
                html.Code(content.hex(), style={'color': '#ff79c6'}),
                html.P(f"Seed in ASCII: {content.decode(errors='replace')}", style={'color': '#8be9fd'})
            ])
            
    return f"No active seed stopped at BB {clicked_bb} currently."

# Initial load of CFG
elements = load_cfg_with_graphviz(CFG_EDGES_FILE)
app.layout = create_layout(elements, get_default_stylesheet())

if __name__ == '__main__':
    # Start the SHM collector thread
    start_collector()
    
    # Run Dash app
    app.run(host='0.0.0.0', port=8050, debug=False)
