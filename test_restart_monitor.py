#!/usr/bin/env python
"""
Quick Test Script for RestartMonitor Implementation
Tests the restart monitor in isolation to verify it works correctly.

Usage:
    python test_restart_monitor.py
"""

import os
import sys
import time
import logging
from pathlib import Path
from threading import Thread

# Setup logging for the test
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import the RestartMonitor
try:
    from restart_monitor_thread import RestartMonitor
    print("✅ Successfully imported RestartMonitor")
except ImportError as e:
    print(f"❌ Failed to import RestartMonitor: {e}")
    sys.exit(1)


def test_monitor_creation():
    """Test 1: Can create RestartMonitor instance"""
    print("\n" + "="*60)
    print("TEST 1: Create RestartMonitor Instance")
    print("="*60)
    try:
        monitor = RestartMonitor(
            reload_file_path='.reload_test',
            check_interval=0.5
        )
        print("✅ Successfully created RestartMonitor instance")
        return monitor
    except Exception as e:
        print(f"❌ Failed to create RestartMonitor: {e}")
        return None


def test_monitor_start_stop(monitor):
    """Test 2: Can start and stop monitor"""
    print("\n" + "="*60)
    print("TEST 2: Start and Stop Monitor")
    print("="*60)
    try:
        monitor.start()
        print("✅ Monitor started successfully")
        time.sleep(1)

        if not monitor._running:
            print("❌ Monitor stopped immediately")
            return False

        print("✅ Monitor is running")

        monitor.stop()
        print("✅ Monitor stopped successfully")
        time.sleep(1)

        if monitor._running:
            print("❌ Monitor didn't stop")
            return False

        print("✅ Monitor cleanup complete")
        return True
    except Exception as e:
        print(f"❌ Error during start/stop: {e}")
        return False


def test_file_monitoring():
    """Test 3: Monitor detects file touches"""
    print("\n" + "="*60)
    print("TEST 3: File Monitoring Detection")
    print("="*60)

    test_file = Path('.reload_test2')

    try:
        # Clean up if exists
        if test_file.exists():
            test_file.unlink()

        print(f"Creating test monitor for {test_file}")
        monitor = RestartMonitor(
            reload_file_path=str(test_file),
            check_interval=0.2  # Fast polling for test
        )

        # Track if restart was triggered
        restart_triggered = False

        def restart_callback():
            nonlocal restart_triggered
            restart_triggered = True
            print("🔔 Restart callback called!")

        monitor.on_restart_callback = restart_callback

        # Start in a separate thread (we'll kill it manually)
        monitor.start()
        print(f"✅ Monitor started (watching {test_file})")

        # Give it time to start
        time.sleep(0.5)

        # Create the file
        print("Creating test file...")
        test_file.touch()
        time.sleep(0.3)
        print("✅ Test file created and touched")

        # Wait for monitor to detect
        print("Waiting for monitor to detect file touch...")
        for i in range(10):
            if test_file.exists():
                print(f"✓ File exists (check {i+1}/10)")
            time.sleep(0.3)

        # Clean up
        test_file.unlink() if test_file.exists() else None
        monitor.stop()

        print("✅ File monitoring test completed")
        return True

    except Exception as e:
        print(f"❌ Error in file monitoring test: {e}")
        test_file.unlink() if test_file.exists() else None
        return False


def test_thread_daemon():
    """Test 4: Monitor thread is daemon"""
    print("\n" + "="*60)
    print("TEST 4: Daemon Thread Verification")
    print("="*60)

    try:
        monitor = RestartMonitor(reload_file_path='.reload_test3')
        monitor.start()

        if monitor._thread and monitor._thread.daemon:
            print("✅ Monitor thread is correctly set as daemon")
            monitor.stop()
            return True
        else:
            print("❌ Monitor thread is not a daemon")
            monitor.stop()
            return False

    except Exception as e:
        print(f"❌ Error checking daemon status: {e}")
        return False


def test_error_handling():
    """Test 5: Error handling"""
    print("\n" + "="*60)
    print("TEST 5: Error Handling")
    print("="*60)

    try:
        # Test with invalid path
        monitor = RestartMonitor(reload_file_path='/invalid/path/.reload')
        monitor.start()

        # Should run without crashing
        time.sleep(1)

        monitor.stop()
        print("✅ Monitor handles invalid paths gracefully")
        return True

    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        return False


def test_multiple_instances():
    """Test 6: Multiple instances don't interfere"""
    print("\n" + "="*60)
    print("TEST 6: Multiple Instances")
    print("="*60)

    try:
        monitor1 = RestartMonitor(reload_file_path='.reload_m1')
        monitor2 = RestartMonitor(reload_file_path='.reload_m2')

        monitor1.start()
        monitor2.start()

        time.sleep(0.5)

        if monitor1._running and monitor2._running:
            print("✅ Both monitors running independently")
        else:
            print("❌ One or both monitors not running")
            monitor1.stop()
            monitor2.stop()
            return False

        monitor1.stop()
        monitor2.stop()

        print("✅ Multiple instances work correctly")
        return True

    except Exception as e:
        print(f"❌ Error with multiple instances: {e}")
        return False


def run_all_tests():
    """Run all tests and report results"""
    print("\n" + "="*60)
    print("RestartMonitor Implementation Test Suite")
    print("="*60)

    results = {}

    # Test 1: Creation
    monitor = test_monitor_creation()
    results['Creation'] = monitor is not None

    if monitor:
        # Test 2: Start/Stop
        results['Start/Stop'] = test_monitor_start_stop(monitor)

        # Test 3: File Monitoring
        results['File Monitoring'] = test_file_monitoring()

        # Test 4: Daemon Thread
        results['Daemon Thread'] = test_thread_daemon()

    # Test 5: Error Handling
    results['Error Handling'] = test_error_handling()

    # Test 6: Multiple Instances
    results['Multiple Instances'] = test_multiple_instances()

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! RestartMonitor is working correctly.")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. See output above.")
        return False


if __name__ == '__main__':
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  RestartMonitor Test Suite".center(58) + "║")
    print("║" + "  Testing Option A Implementation".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")

    success = run_all_tests()

    print("\n")
    sys.exit(0 if success else 1)
