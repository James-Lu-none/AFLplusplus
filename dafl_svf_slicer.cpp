#include <iostream>
#include <fstream>
#include <sstream>
#include <set>
#include <map>
#include <queue>
#include <vector>
#include <string>
#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include <sys/stat.h>
#include <sys/types.h>

#include "SVF-LLVM/LLVMModule.h"
#include "SVF-LLVM/SVFIRBuilder.h"
#include "WPA/Andersen.h"
#include "MSSA/SVFGBuilder.h"
#include "Graphs/SVFG.h"

using namespace SVF;

bool parseSourceLoc(const std::string& loc, std::string& fl, int& ln) {
    if (loc.empty()) return false;
    size_t brace = loc.find("{");
    if (brace != std::string::npos) { // JSON format
        std::string json_part = loc.substr(brace);
        // Find "fl" key
        size_t fl_key_pos = json_part.find("\"fl\"");
        if (fl_key_pos != std::string::npos) {
            size_t colon_pos = json_part.find(":", fl_key_pos);
            if (colon_pos != std::string::npos) {
                size_t val_start = json_part.find("\"", colon_pos);
                if (val_start != std::string::npos) {
                    size_t val_end = json_part.find("\"", val_start + 1);
                    if (val_end != std::string::npos) {
                        fl = json_part.substr(val_start + 1, val_end - (val_start + 1));
                        size_t last_slash = fl.find_last_of('/');
                        if (last_slash != std::string::npos) {
                            fl = fl.substr(last_slash + 1);
                        }
                    }
                }
            }
        }
        // Find "ln" key
        size_t ln_key_pos = json_part.find("\"ln\"");
        if (ln_key_pos != std::string::npos) {
            size_t colon_pos = json_part.find(":", ln_key_pos);
            if (colon_pos != std::string::npos) {
                size_t val_start = json_part.find_first_not_of(" \t", colon_pos + 1);
                if (val_start != std::string::npos) {
                    size_t val_end = json_part.find_first_of(", \t}", val_start);
                    if (val_end != std::string::npos) {
                        try {
                            ln = std::stoi(json_part.substr(val_start, val_end - val_start));
                        } catch (...) {
                            ln = 0;
                        }
                    }
                }
            }
        }
        return !fl.empty() && ln > 0;
    } else { // Standard format: file.c:123
        size_t colon = loc.rfind(':');
        if (colon != std::string::npos) {
            fl = loc.substr(0, colon);
            size_t last_slash = fl.find_last_of('/');
            if (last_slash != std::string::npos) {
                fl = fl.substr(last_slash + 1);
            }
            try {
                ln = std::stoi(loc.substr(colon + 1));
                return true;
            } catch (...) {
                return false;
            }
        }
    }
    return false;
}

struct TraversalState {
    const SVFGNode* node;
    std::vector<unsigned int> call_stack;

    bool operator==(const TraversalState& other) const {
        return node == other.node && call_stack == other.call_stack;
    }
};

struct TraversalStateHash {
    std::size_t operator()(const TraversalState& state) const {
        std::size_t h = std::hash<const SVFGNode*>{}(state.node);
        for (unsigned int val : state.call_stack) {
            h ^= std::hash<unsigned int>{}(val) + 0x9e3779b9 + (h << 6) + (h >> 2);
        }
        return h;
    }
};

bool isCallEdge(const SVFGEdge* edge, unsigned int& callsiteId) {
    if (auto callDir = SVFUtil::dyn_cast<CallDirSVFGEdge>(edge)) {
        callsiteId = callDir->getCallSiteId();
        return true;
    }
    if (auto callInd = SVFUtil::dyn_cast<CallIndSVFGEdge>(edge)) {
        callsiteId = callInd->getCallSiteId();
        return true;
    }
    return false;
}

bool isRetEdge(const SVFGEdge* edge, unsigned int& callsiteId) {
    if (auto retDir = SVFUtil::dyn_cast<RetDirSVFGEdge>(edge)) {
        callsiteId = retDir->getCallSiteId();
        return true;
    }
    if (auto retInd = SVFUtil::dyn_cast<RetIndSVFGEdge>(edge)) {
        callsiteId = retInd->getCallSiteId();
        return true;
    }
    return false;
}

bool isNodeBlacklisted(const SVFGNode* node, const std::string& target_file) {
    static std::unordered_map<const SVFGNode*, bool> blacklist_cache;
    auto it = blacklist_cache.find(node);
    if (it != blacklist_cache.end()) {
        return it->second;
    }

    bool res = false;
    const ICFGNode* icfg = node->getICFGNode();
    if (icfg) {
        std::string loc = icfg->getSourceLoc();
        std::string fl = "";
        int ln = 0;
        parseSourceLoc(loc, fl, ln);

        std::string fl_lower = fl;
        std::transform(fl_lower.begin(), fl_lower.end(), fl_lower.begin(), ::tolower);

        // Exclude output script and formatting files (general I/O files)
        if (fl_lower.find("output") != std::string::npos ||
            fl_lower.find("vasprintf") != std::string::npos) {
            res = true;
        } else {
            const FunObjVar* funObj = icfg->getFun();
            if (funObj) {
                std::string func_name = funObj->getName();
                
                // Blacklist custom print, string buffering, and logging utilities
                static const std::unordered_set<std::string> blacklist = {
                    "dcputs", "dcputchar", "dcprintf", "dcinit", "dcchkstr", "dcgetstr",
                    "println", "vasprintf", "switchToOrigString", "setOrigString",
                    "setTempString", "strcatext", "strcpyext", "strlenext", "dumpRegs"
                };
                
                if (blacklist.find(func_name) != blacklist.end()) {
                    res = true;
                }
            }
        }
    }
    blacklist_cache[node] = res;
    return res;
}

int main(int argc, char **argv) {
    if (argc < 4) {
        std::cerr << "Usage: dafl_svf_slicer <bitcode_path> <target_location> <output_dir>\n";
        std::cerr << "Example: dafl_svf_slicer target.bc swftophp.c:425 out_dir\n";
        return 1;
    }

    std::string bc_path = argv[1];
    std::string target_loc_input = argv[2];
    std::string output_dir = argv[3];

    // Resolve slicing criterion
    std::string target_str = target_loc_input;
    std::ifstream test_f(target_loc_input);
    if (test_f.good()) {
        std::getline(test_f, target_str);
    }
    test_f.close();

    if (target_str.find(':') == std::string::npos) {
        std::cerr << "Error: Target location '" << target_str << "' must be in file:line format.\n";
        return 1;
    }

    size_t colon_pos = target_str.find(':');
    std::string target_file = target_str.substr(0, colon_pos);
    size_t last_slash = target_file.find_last_of('/');
    if (last_slash != std::string::npos) {
        target_file = target_file.substr(last_slash + 1);
    }
    int target_line = std::stoi(target_str.substr(colon_pos + 1));

    std::cout << "Slicing for target '" << target_file << ":" << target_line << "' begins\n";

    // 🌟 1. SVF 3.3 模組處理
    // 在 SVF 3.3 中，buildSVFModule 僅負責載入 IR（回傳 void）。
    // 我們需要將模組名稱向量傳入，隨後直接調用 builder。
    std::vector<std::string> moduleNameVec = { bc_path };
    LLVMModuleSet* llvmModules = LLVMModuleSet::getLLVMModuleSet();
    llvmModules->buildSVFModule(moduleNameVec);

    // 🌟 2. 建立 SVFIR (PAG)
    // SVF 3.3 預設建構子不需要傳入參數，它會自動抓取當前快取的 LLVMModuleSet
    SVFIRBuilder builder;
    SVFIR* pag = builder.build();

    // 3. Create and run Andersen's pointer analysis
    Andersen* ander = AndersenWaveDiff::createAndersenWaveDiff(pag);
    
    // 4. Build the Sparse Value-Flow Graph (SVFG)
    SVFGBuilder svfgBuilder;
    SVFG* svfg = svfgBuilder.buildFullSVFG(ander);

    // 5. Identify target nodes in SVFG matching the target location
    std::cout << "Debugging first 20 non-empty source locations in SVFG nodes:\n";
    int debug_count = 0;
    std::vector<const SVFGNode*> target_nodes;
    std::set<std::string> all_funcs;
    std::set<std::string> all_nodes;
    for (auto it = svfg->begin(), eit = svfg->end(); it != eit; ++it) {
        const SVFGNode* node = it->second;
        const ICFGNode* icfg = node->getICFGNode();
        if (icfg) {
            std::string loc = icfg->getSourceLoc();
            if (!loc.empty() && loc != "Global ICFGNode" && debug_count < 50) {
                std::string fl = "";
                int ln = 0;
                bool parsed = parseSourceLoc(loc, fl, ln);
                std::cout << "  Raw loc: " << loc << " -> Parsed: " << (parsed ? (fl + ":" + std::to_string(ln)) : "FAILED") << "\n";
                debug_count++;
            }
            std::string fl = "";
            int ln = 0;
            if (parseSourceLoc(loc, fl, ln)) {
                all_nodes.insert(fl + ":" + std::to_string(ln));
                if (fl == target_file && ln == target_line) {
                    target_nodes.push_back(node);
                }
            }
            const FunObjVar* funObj = icfg->getFun();
            if (funObj) {
                std::string func_name = funObj->getName();
                if (!func_name.empty()) {
                    if (!fl.empty()) {
                        all_funcs.insert(fl + ":" + func_name);
                    } else {
                        all_funcs.insert(func_name);
                    }
                }
            }
        }
    }

    std::cout << "Found " << target_nodes.size() << " target SVFG nodes matching '" << target_file << ":" << target_line << "'\n";

    // 6. Backward traversal on SVFG to find the backward data-flow slice
    std::unordered_set<TraversalState, TraversalStateHash> visited_states;
    std::unordered_set<const SVFGNode*> visited;
    std::queue<TraversalState> q;

    for (const SVFGNode* node : target_nodes) {
        if (!isNodeBlacklisted(node, target_file)) {
            TraversalState init_state{node, {}};
            visited_states.insert(init_state);
            visited.insert(node);
            q.push(init_state);
        }
    }

    while (!q.empty()) {
        TraversalState curr = q.front();
        q.pop();

        for (auto edgeIt = curr.node->InEdgeBegin(); edgeIt != curr.node->InEdgeEnd(); ++edgeIt) {
            SVFGEdge* edge = static_cast<SVFGEdge*>(*edgeIt);
            const SVFGNode* src = edge->getSrcNode();

            if (isNodeBlacklisted(src, target_file)) {
                continue;
            }

            std::vector<unsigned int> next_stack = curr.call_stack;
            bool allowed = true;

            unsigned int callsiteId = 0;
            if (isRetEdge(edge, callsiteId)) {
                if (next_stack.size() < 3) {
                    next_stack.push_back(callsiteId);
                } else {
                    allowed = false;
                }
            } else if (isCallEdge(edge, callsiteId)) {
                if (!next_stack.empty()) {
                    if (next_stack.back() == callsiteId) {
                        next_stack.pop_back();
                    } else {
                        allowed = false;
                    }
                }
            } else {
                // Check if crossing functions on a non-call/ret edge
                const ICFGNode* curr_icfg = curr.node->getICFGNode();
                const ICFGNode* src_icfg = src->getICFGNode();
                if (curr_icfg && src_icfg) {
                    const FunObjVar* curr_fun = curr_icfg->getFun();
                    const FunObjVar* src_fun = src_icfg->getFun();
                    if (curr_fun && src_fun && curr_fun != src_fun) {
                        next_stack.clear();
                    }
                }
            }

            if (allowed) {
                TraversalState next_state{src, next_stack};
                if (visited_states.find(next_state) == visited_states.end()) {
                    visited_states.insert(next_state);
                    visited.insert(src);
                    q.push(next_state);
                }
            }
        }
    }

    std::cout << "Backward slice contains " << visited.size() << " SVFG nodes\n";

    // 7. Construct Line-level DFG and collect functions
    std::set<std::string> line_nodes;
    std::unordered_map<std::string, std::set<std::string>> line_edges;
    std::unordered_map<std::string, std::set<std::string>> reversed_line_edges;
    std::set<std::string> funcs;
    funcs.insert("main.c:main"); // Always include main in the target file

    std::unordered_map<unsigned int, std::string> node_to_line;

    for (const SVFGNode* node : visited) {
        const ICFGNode* icfg = node->getICFGNode();
        if (!icfg) continue;
        std::string loc_str = icfg->getSourceLoc();
        std::string fl = "";
        int ln = 0;
        if (parseSourceLoc(loc_str, fl, ln)) {
            std::string line_str = fl + ":" + std::to_string(ln);
            node_to_line[node->getId()] = line_str;
            line_nodes.insert(line_str);
        }

        // 🌟 3. 修正函式獲取與 StringRef 轉 std::string 的相容性問題
        const FunObjVar* funObj = icfg->getFun();
        if (funObj) {
            // 在 SVF 3.3 中，funObj->getName() 回傳 llvm::StringRef 
            // 必須透過 .str() 明確轉換成 std::string
            std::string func_name = funObj->getName();
            if (!func_name.empty()) {
                if (!fl.empty()) {
                    funcs.insert(fl + ":" + func_name);
                } else {
                    funcs.insert(target_file + ":" + func_name);
                }
            }
        }
    }

    // 8. Compute shortest-path distance to target using BFS on the SVFG (backward traversal)
    std::unordered_map<const SVFGNode*, int> svfg_distances;
    std::queue<const SVFGNode*> bfs_q;

    for (const SVFGNode* node : target_nodes) {
        svfg_distances[node] = 0;
        bfs_q.push(node);
    }

    while (!bfs_q.empty()) {
        const SVFGNode* curr = bfs_q.front();
        bfs_q.pop();

        int curr_dist = svfg_distances[curr];
        for (auto edgeIt = curr->InEdgeBegin(); edgeIt != curr->InEdgeEnd(); ++edgeIt) {
            SVFGEdge* edge = static_cast<SVFGEdge*>(*edgeIt);
            const SVFGNode* src = edge->getSrcNode();
            if (visited.find(src) != visited.end()) {
                if (svfg_distances.find(src) == svfg_distances.end()) {
                    svfg_distances[src] = curr_dist + 1;
                    bfs_q.push(src);
                }
            }
        }
    }

    // Map SVFG node distances to Line-level distances
    std::unordered_map<std::string, int> line_distances;
    for (const auto& kv : svfg_distances) {
        const SVFGNode* node = kv.first;
        int dist = kv.second;
        if (node_to_line.find(node->getId()) != node_to_line.end()) {
            std::string line_str = node_to_line[node->getId()];
            if (line_distances.find(line_str) == line_distances.end() || dist < line_distances[line_str]) {
                line_distances[line_str] = dist;
            }
        }
    }

    // Always make sure target line is at distance 0
    std::string target_line_str = target_file + ":" + std::to_string(target_line);
    line_distances[target_line_str] = 0;

    // Compute DFG node scores: score = max_dist - dist + 1
    std::map<std::string, int> dfg_nodes_scores;
    if (!line_distances.empty()) {
        int max_dist = 0;
        for (const auto& kv : line_distances) {
            if (kv.second > max_dist) max_dist = kv.second;
        }
        for (const auto& kv : line_distances) {
            dfg_nodes_scores[kv.first] = max_dist - kv.second + 1;
        }
    }

    // 9. Save outputs
    mkdir(output_dir.c_str(), 0777);
    
    // Save slice_func.txt
    std::ofstream func_file(output_dir + "/slice_func.txt");
    for (const std::string& func : funcs) {
        func_file << func << "\n";
    }
    func_file.close();
        
    // Save slice_dfg.txt
    std::ofstream dfg_file(output_dir + "/slice_dfg.txt");
    std::vector<std::pair<std::string, int>> sorted_scores(dfg_nodes_scores.begin(), dfg_nodes_scores.end());
    std::sort(sorted_scores.begin(), sorted_scores.end(), [](const auto& a, const auto& b) {
        if (a.second != b.second) {
            return a.second < b.second; // Ascending order of score
        }
        return a.first < b.first; // Alphabetical order if scores are equal
    });
    for (const auto& kv : sorted_scores) {
        dfg_file << kv.second << " " << kv.first << "\n";
    }
    dfg_file.close();

    // Save all_funcs.txt
    std::ofstream all_func_file(output_dir + "/all_funcs.txt");
    for (const std::string& func : all_funcs) {
        all_func_file << func << "\n";
    }
    all_func_file.close();

    // Save all_nodes.txt
    std::ofstream all_node_file(output_dir + "/all_nodes.txt");
    for (const std::string& node_str : all_nodes) {
        all_node_file << node_str << "\n";
    }
    all_node_file.close();

    std::cout << "Slicing finished. Outputs written to " << output_dir << "\n";
    std::cout << " - Sliced functions count: " << funcs.size() << "\n";
    std::cout << " - DFG nodes count: " << dfg_nodes_scores.size() << "\n";

    return 0;
}