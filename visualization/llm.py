import os
import re
import binascii
import threading
from ollama import Client
from config import *
from core.logger import log_message

def load_bb_lines_map():
    with open(BB_LINES_MAP_FILE, 'r') as f:
        bb_map = {}
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 4:
                continue
            bb_id, file, start, end = parts
            # remove % from bb_id
            bb_id = bb_id.replace('%', '')
            try:
                bb_id_val = int(bb_id)
                start_line = int(start)
                end_line = int(end)
                bb_map[bb_id_val] = (file, start_line, end_line)
            except ValueError:
                continue
    return bb_map

def get_bb_source_code(bb_id, bb_map, source_code_path, range_size=5):
    if bb_id not in bb_map:
        return f"No trace info for BB {bb_id}"
    file, start, end = bb_map[bb_id]
    found = False
    for root, dirs, files in os.walk(source_code_path):
        if file in files:
            file = os.path.join(root, file)
            found = True
            break
    if not found or not os.path.exists(file):
        return f"Source file {file} not found"
    with open(file, 'r') as f:
        lines = f.readlines()
        return '\n'.join(lines[max(1, start-range_size):min(len(lines), end+range_size)])

import re
import binascii

def extract_and_convert_hex(llm_output):
    pattern = r"<SEED>(.*?)</SEED>|#### Proposed New Seed \(Hex\):\s+```\s*(.*?)\s*```"
    match = re.search(pattern, llm_output, re.DOTALL | re.IGNORECASE)
    
    if match:
        hex_str = (match.group(1) or match.group(2)).strip().replace(" ", "").replace("\n", "")
        
        try:
            seed_bytes = binascii.unhexlify(hex_str)
            return seed_bytes
        except binascii.Error as e:
            log_message(f"Hex format error: {e}")
            return None
    else:
        fallback_pattern = r"[0-9a-fA-F]{10,}"
        matches = re.findall(fallback_pattern, llm_output)
        if matches:
            try:
                return binascii.unhexlify(matches[-1])
            except:
                log_message("Failed to convert fallback hex string to bytes.")
                pass
    
    return None

llm_seed_counter = 0
counter_lock = threading.Lock()

def save_llm_seed(seed_content, output_dir, target_idx):
    global llm_seed_counter

    with counter_lock:
        current_id = llm_seed_counter
        llm_seed_counter += 1
    
    relative_time_sec = int(time.time() - FUZZING_START_TIME)

    llm_queue_dir = os.path.join(output_dir, "llm_node", "queue")
    os.makedirs(llm_queue_dir, exist_ok=True)
    file_name = f"id:{current_id:06d},src:{target_idx:06d},time:{relative_time_sec:06d},op:llm_gen"
    log_message(f"Saving LLM-generated seed to {file_name} in AFL queue...")
    file_path = os.path.join(llm_queue_dir, file_name)
    try:
        with open(file_path, "wb") as f:
            f.write(seed_content)
        log_message(f"Injected: {file_name}")
    except Exception as e:
        log_message(f"Save Seed Failed: {e}")

# Limit concurrent LLM calls to prevent choking the endpoint
llm_semaphore = threading.BoundedSemaphore(1)

def trigger_llm_call(target_idx, data, bb_info, endpoint, model):
    """
    Triggers an LLM call when a target is stuck in a thread-safe manner.
    """
    last_bb_id = data.get('last_bb_id', 'N/A')
    path_content = data.get('path_content', [])
    seed_content = data.get('seed_content', b'')
    
    msg = f"Target {target_idx} (BB {last_bb_id}) is stuck. Triggering LLM ({model}) via {endpoint}... BB Info: {bb_info}"
    log_message(f"LLM TRIGGER: {msg}")
    
    source_code_path = os.getenv("SOURCE_CODE_PATH")
    if source_code_path is None:
        log_message("SOURCE_CODE_PATH is not set.")
        return

    # get source code snippet for last 5 basic blocks in path
    bb_map = load_bb_lines_map()
    code_snippet = []
    # use the snapshotted path_content
    for bb_id in path_content[-5:]:
        code_snippet.append(f"BB {bb_id}:\n{get_bb_source_code(bb_id, bb_map, source_code_path, range_size=5)}")
    code_snippet = '\n'.join(code_snippet)

    # construct prompt from seed, cfg, and bb_info
    prompt = f"""
    You are a expert in fuzzing and program analysis. please analyze the following information and suggest a new seed that might help the fuzzer reach new paths.
    
    current basic block ID: {last_bb_id}
    current basic block info: {bb_info}
    current seed: {seed_content}
    current seed_hex: {seed_content.hex()}

    source code of last 5 basic blocks in path:
    {code_snippet}
    
    now Please provide the final generated seed strictly enclosed within <SEED> and </SEED> tags. Do not include spaces in the hex string.
    """
    try:
        if not endpoint:
            log_message("LLM Error: Endpoint not specified.")
            return
        if not model:
            log_message("LLM Error: Model not specified.")
            return
            
        with llm_semaphore:
            client = Client(host=endpoint)
            response = client.generate(model=model, prompt=prompt)
            log_message(f"LLM Request prompt for Target {target_idx}:\n {prompt}")
            if 'response' in response:
                log_message(f"LLM Response received for Target {target_idx}:\n {response['response']}")
                # transform response from hex format to bytes
                parsed_seed_content = extract_and_convert_hex(response['response'])
                if parsed_seed_content is not None:
                    log_message(f"Parsed LLM Seed (Hex) for Target {target_idx}: {parsed_seed_content.hex()}")
                    save_llm_seed(parsed_seed_content, os.getenv("AFL_OUT_DIR"), target_idx)
                else:
                    log_message(f"Failed to extract valid hex seed from LLM response for Target {target_idx}.")
            else:
                log_message(f"LLM Error: Unexpected response format from {endpoint}")
    except Exception as e:
        error_msg = f"LLM Call Failed ({endpoint}, {model}): {str(e)}"
        log_message(error_msg)
