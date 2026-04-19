import threading
import time
import os
from config import *
from core.models import SharedDistKVStore
from core.shm_handler import get_afl_shm_ptr
from core.cfg_processor import load_bb_lines_map, load_target_bb_map, load_cfg_adj
from llm import trigger_llm_call
from core.logger import log_message

# Shared state for the UI to read
target_timers = [0] * MAX_TARGETS
prev_active_counts = [0] * MAX_TARGETS
monitor_lock = threading.Lock()

# Shared settings that can be updated from the UI
llm_endpoint_state = DEFAULT_LLM_ENDPOINT
llm_model_state = DEFAULT_LLM_MODEL
llm_threshold_state = DEFAULT_LLM_THRESHOLD

def monitor_loop():
    """
    Background loop to check for stuck targets and trigger LLM calls.
    """
    global target_timers, prev_active_counts
    
    # Load metadata
    bb_map = load_bb_lines_map(BB_LINES_MAP_FILE)
    target_bb_map = load_target_bb_map(TARGET_BB_MAP_FILE)
    cfg_adj = load_cfg_adj(CFG_EDGES_FILE)
    
    log_message(f"Monitor Thread: Started. Threshold={DEFAULT_LLM_THRESHOLD}s, Endpoint={DEFAULT_LLM_ENDPOINT}, Model={DEFAULT_LLM_MODEL}")

    current_dist_shm_ptr = None

    while True:
        # Read current settings from shared state
        with monitor_lock:
            llm_endpoint = llm_endpoint_state
            llm_model = llm_model_state
            llm_threshold = llm_threshold_state

        if not current_dist_shm_ptr:
            current_dist_shm_ptr = get_afl_shm_ptr(TARGET_PROCESS_NAME, DIST_KV_SHM_NAME)
            if not current_dist_shm_ptr:
                time.sleep(1)
                continue

        try:
            dist_kv = SharedDistKVStore.from_address(current_dist_shm_ptr)
        except Exception:
            current_dist_shm_ptr = None
            time.sleep(1)
            continue

        with monitor_lock:
            for i in range(MAX_TARGETS):
                entry = dist_kv.entries[i]
                target_bb = target_bb_map.get(i, "N/A")
                
                if target_bb == "N/A":
                    continue

                # Get human readable info for logging
                target_bb_info = f"{target_bb}"
                if target_bb in bb_map:
                    file, start, end = bb_map[target_bb]
                    target_bb_info = f"{file}:{start}-{end} ({target_bb})"

                # Timer logic
                if entry.active_count > prev_active_counts[i]:
                    target_timers[i] = 0
                    prev_active_counts[i] = entry.active_count
                else:
                    # Increment timer (assuming 1s sleep per loop)
                    if entry.active_count > 0: # Only count if it has been hit at least once
                        target_timers[i] += 1
                
                if target_timers[i] >= llm_threshold:
                    # Get next possible basic blocks from CFG
                    last_bb_id = str(entry.last_bb_id)
                    next_bbs = cfg_adj.get(last_bb_id, [])

                    # Snapshot data to pass to the thread
                    data_snapshot = {
                        'last_bb_id': entry.last_bb_id,
                        'path_content': list(entry.path_content[:entry.path_len]),
                        'seed_content': bytes(entry.seed_content[:entry.seed_len]),
                        'next_bbs': next_bbs
                    }
                    
                    log_message(f"Monitor Thread: Target {i} stuck for {target_timers[i]}s. Triggering LLM.")
                    
                    threading.Thread(
                        target=trigger_llm_call, 
                        args=(i, data_snapshot, target_bb_info, llm_endpoint, llm_model),
                        daemon=True
                    ).start()
                    
                    # Reset timer after trigger to avoid spamming while waiting for LLM/Fuzzer progress
                    target_timers[i] = 0

        # Wait 1 second between checks
        time.sleep(1)

def start_monitor():
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    return thread
