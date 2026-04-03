from dash import html, dcc
import dash_cytoscape as cyto
from config import DEFAULT_REFRESH_INTERVAL, DEFAULT_TOP_N, MIN_REFRESH_INTERVAL, DEFAULT_CFG_ENABLED, DEFAULT_LLM_THRESHOLD, MIN_LLM_THRESHOLD, DEFAULT_LLM_ENDPOINT, DEFAULT_LLM_MODEL, MAX_TARGETS

def create_layout(initial_stylesheet):
    """
    Creates the main Dash layout.
    """
    def slider_row(label, slider_id, display_id, min_val, max_val, step, default):
        return html.Div(style={'marginBottom': '20px'}, children=[
            html.Div(style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center'}, children=[
                html.Label(label, style={'fontSize': '12px', 'color': '#bbb'}),
                html.Span(id=display_id, style={'color': '#00ff00', 'fontWeight': 'bold', 'fontSize': '14px', 'fontFamily': 'monospace'})
            ]),
            dcc.Slider(
                id=slider_id, min=min_val, max=max_val, step=step, value=default,
                marks={i: str(i) for i in range(min_val, max_val + 1, step)}, updatemode='drag'
            )
        ])
    
    return html.Div(
        style={'backgroundColor': '#121212', 'color': 'white', 'height': '100vh', 'padding': '10px', 'boxSizing': 'border-box', 'margin': '0', 'overflow': 'hidden'},
        children=[
            html.Div(style={'display': 'flex', 'gap': '15px', 'width': '100%', 'height': '100%', 'overflow': 'hidden'}, children=[
                # Graph visualization on the left
                html.Div(id='cfg-graph-container', style={'flex': '1 1 70%', 'minWidth': '0', 'display': 'flex', 'flexDirection': 'column'}, children=[
                    # Wrapper for the graph to make it resizable from the bottom
                    html.Div(
                        style={
                            'flex': '0 0 auto', 
                            'height': '70%', 
                            'minHeight': '100px', 
                            'resize': 'vertical', 
                            'overflow': 'hidden',
                            'borderBottom': '2px solid #444',
                            'paddingBottom': '2px'
                        },
                        children=[
                            cyto.Cytoscape(
                                id='cfg-graph',
                                elements=[],
                                autoungrabify=True,
                                autolock=True,
                                userZoomingEnabled=True,
                                userPanningEnabled=True,
                                layout={'name': 'preset'},
                                style={'width': '100%', 'height': '100%', 'border': 'none'},
                                stylesheet=initial_stylesheet
                            ),
                        ]
                    ),
                    # Log panel fills the rest and stays at bottom
                    html.Div(
                        id='log-panel', 
                        style={
                            'flex': '1', 
                            'backgroundColor': '#000', 
                            'color': '#00ff00', 
                            'fontFamily': 'monospace', 
                            'fontSize': '12px', 
                            'padding': '10px', 
                            'overflowY': 'auto', 
                            'border': '1px solid #444',
                            'borderTop': 'none',
                            'borderRadius': '0 0 5px 5px',
                            'whiteSpace': 'pre-wrap'
                        },
                        children="Monitoring started..."
                    )
                ]),
                
                # Live status and node info on the right
                html.Div(
                    style={
                        'flex': '0 0 30%', 
                        'minWidth': '350px',
                        'padding': '10px', 
                        'backgroundColor': '#1e1e1e', 
                        'display': 'flex', 
                        'flexDirection': 'column',
                        'overflowY': 'auto',
                        'maxHeight': '100%',
                        'border': '1px solid #444',
                        'borderRadius': '5px'
                    }, 
                    children=[
                        # refresh settings panel at the top
                        html.Div(
                            style={'padding': '10px', 'border': '1px solid #444', 'marginBottom': '10px'}, 
                            children=[
                                html.H4("Refresh Settings", style={'marginTop': '0'}),
        
                                slider_row(
                                    "Refresh Interval (ms):", "interval-setting", "interval-display", 
                                    500, 5000, 500, 1000
                                ),
                                
                                slider_row(
                                    "Filter Top N Nodes (0 = All):", "top-n-input", "top-n-display", 
                                    0, 1000, 5, 10
                                ),
                                
                                slider_row(
                                    "LLM Feedback Threshold (sec):", "llm-threshold-input", "llm-threshold-display", 
                                    1, 3600, 1, 60
                                ),
                            ]
                        ),

                        # clicked target info
                        html.Div(children=[
                            html.H4("Clicked Target Info"),
                            html.Div(
                                id='target-data-display', 
                                style={
                                    'wordBreak': 'break-all', 
                                    'fontFamily': 'monospace', 
                                    'fontSize': '12px', 
                                    'minHeight': '150px'
                                }
                            ),
                            html.Hr(),
                        ]),

                        # live status display
                        html.Div(children=[
                            html.H3("Live Status"),
                            html.Div(id='live-status-info'),
                            html.Hr(),
                        ]),
                        
                        # coverage heatmap visualization at the bottom
                        html.Div(style={'marginTop': 'auto'}, children=[
                            html.H4("Coverage Map"),
                            html.Div(
                                id='coverage-stats', 
                                style={'fontSize': '14px', 'color': '#00ff00', 'marginBottom': '5px'}
                            ),
                            dcc.Graph(
                                id='coverage-heatmap',
                                config={'displayModeBar': False},
                                style={'height': '300px'}
                            )
                        ])
                    ]
                )
            ]),
            
            dcc.Interval(id='refresh-timer', interval=DEFAULT_REFRESH_INTERVAL, n_intervals=0),
            dcc.Store(id='selected-target-idx', data=-1)
        ]
    )
