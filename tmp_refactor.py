import sys

def modify_app_py(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()

    # We need to find the `else:` corresponding to `if pde_report_mode == "Template Summary + Method Sheets (V2)":`
    # Let's locate `if pde_report_mode == "Template Summary + Method Sheets (V2)":`
    
    # 1. Gather ratings df init code
    df_init_code = [
        '                    df_rows = []\n',
        '                    for r in ratings:\n',
        '                        df_rows.append({\n',
        '                            "Q#": r.get("question_id", ""),\n',
        '                            "Question": r.get("question_text", ""),\n',
        '                            "Rating": r.get("selected_rating", ""),\n',
        '                            "Evidence": r.get("source_reasoning", ""),\n',
        '                            "Confidence": r.get("confidence", 0.0),\n',
        '                            "Missing": "Yes" if r.get("missing_info") else "No"\n',
        '                        })\n',
        '                    df = pd.DataFrame(df_rows)\n',
        '\n'
    ]

    # Find where to insert df_init_code
    v2_if_idx = -1
    for i, line in enumerate(lines):
        if 'if pde_report_mode == "Template Summary + Method Sheets (V2)":' in line:
            v2_if_idx = i
            break
            
    if v2_if_idx != -1:
        lines = lines[:v2_if_idx] + df_init_code + lines[v2_if_idx:]
    else:
        print("Couldn't find if statement")
        return

    # After insertion, the index of `else:` will have shifted by len(df_init_code) (12 lines)
    # The `else:` we want is at original line 1758 (0-based 1757) -> roughly 1757 + 12 = 1769
    # Let's find it. It's the `else:` tightly followed by `# --- Override Notes (if rules fired) ---`
    
    else_idx = -1
    for i in range(v2_if_idx, len(lines)):
        if lines[i].strip() == "else:" and "override_reasons =" in lines[i+2]:
            else_idx = i
            break

    if else_idx == -1:
        print("Couldn't find else statement")
        return

    # Delete the `else:`
    del lines[else_idx]
    
    # Now unindent all lines below it until we hit the `# --- Download & Reset ---`
    for i in range(else_idx, len(lines)):
        if "--- Download & Reset ---" in lines[i]:
            break
        if lines[i].startswith("    "): # remove 4 spaces
            lines[i] = lines[i][4:]

    with open(filepath, 'w') as f:
        f.writelines(lines)
    print("Success")

modify_app_py("/Users/rajasekharbandreddy/Downloads/caltrans/app.py")
