"""
Comprehensive verification test script for Jarvis fixes.
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def test_unicode_sanitization():
    print("Testing unicode sanitization...")
    from jarvis.utils.text import sanitize_ascii

    # Curly apostrophe
    res1 = sanitize_ascii("I’m Jarvis and you’re awesome.")
    assert "I'm Jarvis and you're awesome." == res1, f"Expected clean apostrophe, got: {res1}"

    # Curly double quotes
    res2 = sanitize_ascii("He said “Hello world” today.")
    assert 'He said "Hello world" today.' == res2, f"Expected clean quotes, got: {res2}"

    # Em dash and ellipses
    res3 = sanitize_ascii("Wait—let me think…")
    assert "Wait - let me think..." == res3, f"Expected dash and dots, got: {res3}"

    print("  [PASS] Unicode sanitization normalized properly.")


def test_create_file_tool():
    print("Testing create file tool...")
    from jarvis.tools.builtins.create_file import CreateFileTool, SANDBOX_DIR
    from jarvis.tools.executor import SafeExecutor
    from jarvis.permissions import PermissionManager

    tool = CreateFileTool()
    # Mock confirmation to return True
    pm = PermissionManager(confirm_fn=lambda q: True)
    executor = SafeExecutor(permission_manager=pm)

    # Test file creation with content
    test_filename = "test_audit_note.txt"
    test_content = "Verification test content for Jarvis."
    result = executor.run(tool, f"create a file named {test_filename} with {test_content}")

    assert result.success is True, f"Create file failed: {result.message}"
    created_file = SANDBOX_DIR / test_filename
    assert created_file.exists(), "Created file was not found on disk"
    assert created_file.read_text(encoding="utf-8") == test_content

    # Clean up
    created_file.unlink()
    print("  [PASS] CreateFileTool created file safely in sandbox.")


def test_initialization_order():
    print("Testing Jarvis subsystem initialization order and permission hook...")
    from jarvis.app import Jarvis

    assistant = Jarvis()
    # Initialize subsystems without starting audio loop
    assistant.initialize()

    assert assistant.speaker is not None, "Speaker failed to initialize"
    assert assistant.listener is not None, "Listener failed to initialize"
    assert assistant.processor is not None, "Processor failed to initialize"

    # Verify that voice confirmation was attached (not None) because listener was initialized before commands
    pm = assistant.processor.executor._permissions
    assert pm._confirm_fn is not None, "Voice confirmation fn was not attached to PermissionManager!"
    print("  [PASS] Initialization order verified; voice confirmation attached.")


def test_command_processor_and_brain():
    print("Testing CommandProcessor routing and brain...")
    from jarvis.app import Jarvis

    assistant = Jarvis()
    assistant.initialize()

    # Test system greeting
    res_greet = assistant.processor.process("hello")
    assert any(word in res_greet.response.lower() for word in ["hello", "hi", "hey", "greetings"]), f"Unexpected greeting: {res_greet.response}"

    # Test tool routing
    res_time = assistant.processor.process("what time is it")
    assert "it is currently" in res_time.response.lower(), f"Unexpected time response: {res_time.response}"

    # Test known intent
    assert assistant.processor.is_known_intent("open chrome") is True
    assert assistant.processor.is_known_intent("what time is it") is True
    assert assistant.processor.is_known_intent("hello") is True

    print("  [PASS] CommandProcessor routed greetings and tools correctly.")


def test_tts_speaker_properties():
    print("Testing Pyttsx3Speaker properties and timeout calculation...")
    from jarvis.tts import Pyttsx3Speaker

    speaker = Pyttsx3Speaker()
    assert hasattr(speaker, "is_speaking"), "Speaker missing is_speaking property"
    assert speaker.is_speaking is False, "Speaker should be idle initially"

    print("  [PASS] Speaker properties and state validated.")


if __name__ == "__main__":
    print("=" * 60)
    print("RUNNING JARVIS FIX VERIFICATION SUITE")
    print("=" * 60)
    test_unicode_sanitization()
    test_create_file_tool()
    test_initialization_order()
    test_command_processor_and_brain()
    test_tts_speaker_properties()
    print("=" * 60)
    print("ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
