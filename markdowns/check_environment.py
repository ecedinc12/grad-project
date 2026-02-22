#!/usr/bin/env python3
"""
Environment verification script for Isaac Sim 4.2+ setup.
Checks for required drivers, dependencies, and Isaac Sim availability.
"""

import sys
import subprocess
import shutil
import os
from pathlib import Path

def run_command(cmd, capture_output=True):
    """Run shell command and return result."""
    try:
        if capture_output:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        else:
            result = subprocess.run(cmd, shell=True, text=True, check=False)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_nvidia_driver():
    """Check if NVIDIA driver is installed and working."""
    print("🔍 Checking NVIDIA driver...")
    success, stdout, stderr = run_command("nvidia-smi")
    if success:
        print("✅ NVIDIA driver detected")
        # Extract driver version
        for line in stdout.split('\n'):
            if "Driver Version" in line:
                print(f"   {line.strip()}")
        return True
    else:
        print("❌ NVIDIA driver not found or not working")
        print(f"   Error: {stderr}")
        return False

def check_cuda():
    """Check if CUDA is available."""
    print("🔍 Checking CUDA...")
    # Check nvcc
    success, stdout, stderr = run_command("nvcc --version")
    if success:
        for line in stdout.split('\n'):
            if "release" in line.lower():
                print(f"✅ CUDA detected: {line.strip()}")
                return True
    # Alternative check via nvidia-smi
    success, stdout, stderr = run_command("nvidia-smi -q | grep 'CUDA Version'")
    if success and stdout:
        print(f"✅ CUDA detected: {stdout.strip()}")
        return True
    
    print("❌ CUDA not found")
    return False

def check_isaac_sim():
    """Check if Isaac Sim is accessible."""
    print("🔍 Checking Isaac Sim installation...")
    
    # Check common installation paths
    possible_paths = [
        "/isaac-sim",
        "/opt/isaac-sim",
        os.path.expanduser("~/isaac-sim"),
        os.path.expanduser("~/omniverse/isaac-sim"),
        "/usr/local/isaac-sim",
    ]
    
    isaac_path = None
    for path in possible_paths:
        if os.path.exists(path):
            isaac_path = path
            break
    
    if isaac_path:
        print(f"✅ Isaac Sim directory found at: {isaac_path}")
        
        # Check for the launcher script
        launcher_script = os.path.join(isaac_path, "isaac-sim.sh")
        if os.path.exists(launcher_script):
            print(f"✅ Launcher script found: {launcher_script}")
            
            # Check if it's executable
            if os.access(launcher_script, os.X_OK):
                print(f"✅ Launcher script is executable")
            else:
                print(f"⚠️  Launcher script is not executable. Run: chmod +x {launcher_script}")
        else:
            print(f"⚠️  Launcher script not found at expected location")
            # Check for alternative launcher names
            alt_scripts = ["runheadless.native.sh", "runheadless.sh", "run.sh"]
            for alt in alt_scripts:
                alt_path = os.path.join(isaac_path, alt)
                if os.path.exists(alt_path):
                    print(f"✅ Found alternative launcher: {alt_path}")
                    break
            
        return True, isaac_path
    else:
        print("❌ Isaac Sim installation not found in common locations")
        print("   Searched in:")
        for path in possible_paths:
            print(f"     - {path}")
        return False, None

def check_python_deps():
    """Check for essential Python packages."""
    print("🔍 Checking Python dependencies...")
    
    required_packages = [
        "torch",
        "numpy",
        "PIL",
        "yaml",
        "tqdm",
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.lower() if package == "PIL" else package)
            print(f"✅ {package}")
        except ImportError:
            missing.append(package)
            print(f"❌ {package}")
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        return False
    return True

def check_omniverse_python():
    """Check if we can import Omniverse Python modules."""
    print("🔍 Checking Omniverse Python bindings...")
    
    # First, check if we're likely in Isaac Sim's Python environment
    # by looking for the kit module which is always present
    try:
        import omni.kit
        print("✅ omni.kit module found - likely inside Isaac Sim Python environment")
        
        # Try to import key modules
        modules_to_check = [
            "omni.isaac.core",
            "omni.replicator.core",
            "omni.usd",
        ]
        
        missing_modules = []
        for module in modules_to_check:
            try:
                __import__(module)
                print(f"✅ {module}")
            except ImportError as e:
                missing_modules.append(module)
                print(f"❌ {module}: {e}")
        
        if missing_modules:
            print(f"\n⚠️  Some Omniverse modules are missing: {', '.join(missing_modules)}")
            print("   This may indicate an incomplete Isaac Sim installation")
            return False
        else:
            print("✅ All required Omniverse modules are available")
            return True
            
    except ImportError:
        print("❌ Not in Isaac Sim Python environment")
        print("   Omniverse modules are only available inside Isaac Sim's Python environment")
        print("   To check properly, run this script from within Isaac Sim:")
        print("   ./isaac-sim.sh --headless --python ../markdowns/check_environment.py")
        return False

def check_docker():
    """Check if Docker is available (optional for containerized Isaac Sim)."""
    print("🔍 Checking Docker...")
    success, stdout, stderr = run_command("docker --version")
    if success:
        print(f"✅ Docker detected: {stdout.strip()}")
        return True
    else:
        print("⚠️  Docker not found (optional for containerized setup)")
        return False

def main():
    print("=" * 60)
    print("Isaac Sim 4.2+ Environment Verification")
    print("=" * 60)
    
    all_checks_passed = True
    
    # 1. Check NVIDIA driver
    if not check_nvidia_driver():
        all_checks_passed = False
    
    # 2. Check CUDA
    if not check_cuda():
        all_checks_passed = False
    
    # 3. Check Isaac Sim installation
    isaac_found, isaac_path = check_isaac_sim()
    if not isaac_found:
        all_checks_passed = False
    
    # 4. Check Python dependencies
    if not check_python_deps():
        all_checks_passed = False
    
    # 5. Check Omniverse Python modules
    if not check_omniverse_python():
        print("⚠️  Note: This check is expected to fail outside Isaac Sim environment")
        # Don't fail overall for this check
    
    # 6. Check Docker (optional)
    check_docker()
    
    print("\n" + "=" * 60)
    
    if all_checks_passed:
        print("✅ All critical checks passed!")
        print("\nNext steps:")
        print("1. Navigate to Isaac Sim directory:")
        print(f"   cd {isaac_path if isaac_path else '/path/to/isaac-sim'}")
        print("2. Launch Isaac Sim in headless mode to verify:")
        print("   ./isaac-sim.sh --headless --ext-folder /path/to/grad-project")
        print("3. Set up project structure:")
        print("   python markdowns/setup_project.py")
    else:
        print("❌ Some critical checks failed.")
        print("\nInstallation commands you may need:")
        print("\n1. Install NVIDIA driver (if missing):")
        print("   # For Ubuntu/Debian:")
        print("   sudo apt update")
        print("   sudo apt install nvidia-driver-550  # or latest version")
        print("   sudo reboot")
        print("\n2. Install CUDA Toolkit:")
        print("   # Follow instructions from https://developer.nvidia.com/cuda-downloads")
        print("   wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb")
        print("   sudo dpkg -i cuda-keyring_1.1-1_all.deb")
        print("   sudo apt update")
        print("   sudo apt install cuda-toolkit-12-4")
        print("\n3. Install Isaac Sim:")
        print("   # Download from NVIDIA Omniverse:")
        print("   # https://www.nvidia.com/en-us/omniverse/download/")
        print("   # Extract to ~/isaac-sim or /opt/isaac-sim")
        print("\n4. Install Python dependencies:")
        print("   pip install torch numpy Pillow pyyaml tqdm")
        print("\n5. Set up project structure:")
        print("   python markdowns/setup_project.py")
    
    print("\n" + "=" * 60)
    return 0 if all_checks_passed else 1

if __name__ == "__main__":
    sys.exit(main())
