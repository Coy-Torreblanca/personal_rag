#!/usr/bin/env python3
"""Test script to verify Alembic setup."""

import os
import sys
import subprocess

def run_command(cmd, cwd=None):
    """Run a command and return output."""
    print(f"Running: {cmd}")
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=cwd
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return False, result.stderr
    print(f"Output: {result.stdout}")
    return True, result.stdout

def main():
    # Change to API directory
    api_dir = os.path.join(os.path.dirname(__file__), "..", "apps", "api")
    
    print("Testing Alembic setup...")
    print("=" * 50)
    
    # Test 1: Check if alembic is installed
    print("\n1. Checking Alembic installation...")
    success, output = run_command("alembic --version", cwd=api_dir)
    if not success:
        print("❌ Alembic not installed or not in PATH")
        return 1
    
    # Test 2: Check current migration state
    print("\n2. Checking current migration state...")
    success, output = run_command("alembic current", cwd=api_dir)
    if not success:
        print("❌ Failed to check current migration state")
        return 1
    
    # Test 3: Create a test migration
    print("\n3. Creating test migration...")
    success, output = run_command(
        "alembic revision --autogenerate -m 'test migration'", 
        cwd=api_dir
    )
    if not success:
        print("❌ Failed to create migration")
        return 1
    
    # Test 4: Apply migration
    print("\n4. Applying migration...")
    success, output = run_command("alembic upgrade head", cwd=api_dir)
    if not success:
        print("❌ Failed to apply migration")
        return 1
    
    # Test 5: Check migration history
    print("\n5. Checking migration history...")
    success, output = run_command("alembic history", cwd=api_dir)
    if not success:
        print("❌ Failed to check migration history")
        return 1
    
    print("\n" + "=" * 50)
    print("✅ All tests passed! Alembic is working correctly.")
    return 0

if __name__ == "__main__":
    sys.exit(main())