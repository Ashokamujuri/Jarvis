"""Quick integration test for Jarvis tool routing and imports."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def run_tests():
    print("=" * 55)
    print("  Jarvis Integration Test")
    print("=" * 55)

    # --- Import checks ---
    print("\n[1] Import checks...")
    try:
        from jarvis.app import Jarvis
        from jarvis.commands.processor import CommandProcessor
        from jarvis.tools.builtins import register_all
        from jarvis.tools.registry import ToolRegistry
        from jarvis.tools.builtins.open_app import OpenApplicationTool
        from jarvis.tools.builtins.web_search import BrowserTool
        from jarvis.personality import SYSTEM_PROMPT
        from jarvis.permissions import PermissionManager, RiskLevel
        from jarvis.utils import sanitize_ascii, match_any_keyword
        print("  All imports: OK")
    except Exception as e:
        print(f"  IMPORT ERROR: {e}")
        import traceback; traceback.print_exc()
        return False

    # --- Tool routing tests ---
    print("\n[2] Tool routing tests...")
    reg = ToolRegistry()
    register_all(reg)

    tests = [
        # False-positive guard phrases — must NOT route to any tool
        ("run properly",                   None),
        ("start over",                     None),
        ("run the code",                   None),
        # Blocked apps (not in APPROVED_APPS) — matches() returns False -> None
        ("open notepad",                   None),
        ("launch calculator",              None),
        ("open powershell",                None),
        # Approved apps — must route to open_application
        ("open chrome",                    "open_application"),
        ("open file explorer",             "open_application"),
        ("open spotify",                   "open_application"),
        ("open microsoft edge",            "open_application"),
        ("open settings",                  "open_application"),
        ("open command prompt",            "open_application"),
        # Other tools — unchanged
        ("open youtube",                   "browser"),
        ("search for python tutorials",    "browser"),
        ("what time is it",                "get_time"),
        ("remember that my name is Ashok", "memory"),
        ("what do you remember",           "memory"),
        ("create a file named test.txt",   "create_file"),
    ]

    all_pass = True
    for text, expected in tests:
        tool = reg.find_match(text)
        got = tool.name if tool else None
        status = "PASS" if got == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] \"{text}\" -> {got!r} (expected: {expected!r})")

    # --- Text sanitization ---
    print("\n[3] Text sanitization tests...")
    from jarvis.utils import sanitize_ascii
    cases = [
        ("\u2018I\u2019m fine\u2019",  "'I'm fine'"),
        ("Hello \u2014 world",          "Hello  -  world"),   # em dash -> " - " (space + hyphen + space)
        ("That\u2026 is great",         "That... is great"),
    ]
    for inp, expected in cases:
        result = sanitize_ascii(inp)
        status = "PASS" if result == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
            print(f"  [{status}] sanitize({inp!r}) -> {result!r} (expected: {expected!r})")
        else:
            print(f"  [{status}] sanitize: OK")

    # --- Allowlist enforcement (execute-level) ---
    print("\n[4] Allowlist enforcement tests...")
    from jarvis.tools.builtins.open_app import OpenApplicationTool
    app_tool = OpenApplicationTool()
    enforce_tests = [
        # (phrase,           should_succeed)
        ("open notepad",     False),   # blocked
        ("open calculator",  False),   # blocked
        ("open powershell",  False),   # blocked
        ("open firefox",     False),   # blocked
        ("open some xyz",    False),   # unknown
    ]
    for phrase, expect_success in enforce_tests:
        result = app_tool.execute(phrase)
        ok = result.success == expect_success
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        label = "BLOCKED" if not expect_success else "ALLOWED"
        print(f"  [{status}] execute({phrase!r}) -> {label}: {result.message[:55]}")

    # --- Personality / system prompt ---
    print("\n[5] Personality system prompt...")
    from jarvis.personality import SYSTEM_PROMPT
    if SYSTEM_PROMPT and len(SYSTEM_PROMPT) > 100:
        print("  [PASS] SYSTEM_PROMPT loaded correctly")
    else:
        print("  [FAIL] SYSTEM_PROMPT is empty or too short!")
        all_pass = False

    print("\n" + "=" * 55)
    if all_pass:
        print("  All tests PASSED!")
    else:
        print("  Some tests FAILED - check output above.")
    print("=" * 55)
    return all_pass


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
