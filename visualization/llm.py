import os
from ollama import Client
from config import BB_LINES_MAP_FILE

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

def get_bb_source_code(bb_id, bb_map, source_code_path):
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
        return ''.join(lines[start-1:end])

def trigger_llm_call(target_idx, entry, bb_info, endpoint, model):
    """
    Triggers an LLM call when a target is stuck, with error handling.
    """
    from app import log_message
    msg = f"Target {target_idx} (BB {entry.last_bb_id}) is stuck. Triggering LLM ({model}) via {endpoint}... BB Info: {bb_info}"
    print(f"[LLM TRIGGER] {msg}")
    log_message(f"LLM TRIGGER: {msg}")
    
    source_code_path = os.getenv("SOURCE_CODE_PATH")
    if source_code_path is None:
        log_message("SOURCE_CODE_PATH is not set.")
        return
    # get source code snippet for last 5 basic blocks in path
    bb_map = load_bb_lines_map()
    code_snippet = []
    for bb_id in entry.path_content[:5]:
        code_snippet.append(f"BB {bb_id}: {get_bb_source_code(bb_id, bb_map, source_code_path)}")
    code_snippet = '\n'.join(code_snippet)

    seed_content = bytes(entry.seed_content[:entry.seed_len])
    # construct prompt from seed, cfg, and bb_info
    prompt = f"""
    You are a expert in fuzzing and program analysis. please analyze the following information and suggest a new seed that might help the fuzzer reach new paths.
    
    current basic block ID: {entry.last_bb_id}
    current basic block info: {bb_info}
    current seed: {seed_content}
    current seed_hex: {seed_content.hex()}

    source code of last 5 basic blocks in path:
    {code_snippet}

    current stucked condition: 
    
    now please provide a new seed in hex format
    """
    try:
        if not endpoint:
            log_message("LLM Error: Endpoint not specified.")
            return
        if not model:
            log_message("LLM Error: Model not specified.")
            return
            
        client = Client(host=endpoint)
        response = client.generate(model=model, prompt=prompt)
        if 'response' in response:
            log_message(f"LLM Response received for Target {target_idx}")
            print(response['response'])
        else:
            log_message(f"LLM Error: Unexpected response format from {endpoint}")
    except Exception as e:
        error_msg = f"LLM Call Failed ({endpoint}, {model}): {str(e)}"
        print(f"[LLM ERROR] {error_msg}")
        log_message(error_msg)
