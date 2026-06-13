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
        size_t fl_pos = json_part.find("\"fl\":\"");
        if (fl_pos != std::string::npos) {
            size_t fl_end = json_part.find("\"", fl_pos + 6);
            if (fl_end != std::string::npos) {
                fl = json_part.substr(fl_pos + 6, fl_end - (fl_pos + 6));
                size_t last_slash = fl.find_last_of('/');
                if (last_slash != std::string::npos) {
                    fl = fl.substr(last_slash + 1);
                }
            }
        }
        size_t ln_pos = json_part.find("\"ln\":");
        if (ln_pos != std::string::npos) {
            size_t ln_end = json_part.find_first_of(",}", ln_pos + 5);
            if (ln_end != std::string::npos) {
                ln = std::stoi(json_part.substr(ln_pos + 5, ln_end - (ln_pos + 5)));
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
                if (fl == target_file && ln == target_line) {
                    target_nodes.push_back(node);
                }
            }
        }
    }

    std::cout << "Found " << target_nodes.size() << " target SVFG nodes matching '" << target_file << ":" << target_line << "'\n";

    // 6. Backward traversal on SVFG to find the backward data-flow slice
    std::unordered_set<const SVFGNode*> visited;
    std::queue<const SVFGNode*> q;

    for (const SVFGNode* node : target_nodes) {
        visited.insert(node);
        q.push(node);
    }

    while (!q.empty()) {
        const SVFGNode* curr = q.front();
        q.pop();

        for (auto edgeIt = curr->InEdgeBegin(); edgeIt != curr->InEdgeEnd(); ++edgeIt) {
            SVFGEdge* edge = static_cast<SVFGEdge*>(*edgeIt);
            const SVFGNode* src = edge->getSrcNode();
            if (visited.find(src) == visited.end()) {
                visited.insert(src);
                q.push(src);
            }
        }
    }

    std::cout << "Backward slice contains " << visited.size() << " SVFG nodes\n";

    // 7. Construct Line-level DFG and collect functions
    std::set<std::string> line_nodes;
    std::unordered_map<std::string, std::set<std::string>> line_edges;
    std::unordered_map<std::string, std::set<std::string>> reversed_line_edges;
    std::set<std::string> funcs;
    funcs.insert(target_file + ":main"); // Always include main in the target file

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

    // Add edges in Line-level DFG
    for (const SVFGNode* node : visited) {
        if (node_to_line.find(node->getId()) == node_to_line.end()) continue;
        std::string src_line = node_to_line[node->getId()];

        for (auto edgeIt = node->OutEdgeBegin(); edgeIt != node->OutEdgeEnd(); ++edgeIt) {
            SVFGEdge* edge = static_cast<SVFGEdge*>(*edgeIt);
            const SVFGNode* dst = edge->getDstNode();
            if (visited.find(dst) != visited.end()) {
                if (node_to_line.find(dst->getId()) != node_to_line.end()) {
                    std::string dst_line = node_to_line[dst->getId()];
                    if (src_line != dst_line) {
                        line_edges[src_line].insert(dst_line);
                        reversed_line_edges[dst_line].insert(src_line);
                    }
                }
            }
        }
    }

    // 8. Compute shortest-path distance to target using BFS on reversed graph
    std::string target_line_str = target_file + ":" + std::to_string(target_line);
    if (line_nodes.find(target_line_str) == line_nodes.end()) {
        line_nodes.insert(target_line_str);
    }

    std::unordered_map<std::string, int> distances;
    std::queue<std::string> bfs_q;

    distances[target_line_str] = 0;
    bfs_q.push(target_line_str);

    while (!bfs_q.empty()) {
        std::string curr = bfs_q.front();
        bfs_q.pop();

        int curr_dist = distances[curr];
        if (reversed_line_edges.find(curr) != reversed_line_edges.end()) {
            for (const std::string& pred : reversed_line_edges[curr]) {
                if (distances.find(pred) == distances.end()) {
                    distances[pred] = curr_dist + 1;
                    bfs_q.push(pred);
                }
            }
        }
    }

    // Compute DFG node scores: score = max_dist - dist + 1
    std::map<std::string, int> dfg_nodes_scores;
    if (!distances.empty()) {
        int max_dist = 0;
        for (const auto& kv : distances) {
            if (kv.second > max_dist) max_dist = kv.second;
        }
        for (const auto& kv : distances) {
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
    for (const auto& kv : dfg_nodes_scores) {
        dfg_file << kv.second << " " << kv.first << "\n";
    }
    dfg_file.close();

    std::cout << "Slicing finished. Outputs written to " << output_dir << "\n";
    std::cout << " - Sliced functions count: " << funcs.size() << "\n";
    std::cout << " - DFG nodes count: " << dfg_nodes_scores.size() << "\n";

    return 0;
}