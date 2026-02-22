"""
Environment validation script for Isaac Sim setup.
This script checks GPU availability, Isaac Sim modules, and project structure.
"""
import sys
import os
import subprocess
import json

def check_python_version():
    """Verify Python version matches Isaac Sim requirements."""
    version = sys.version_info
    if version.major == 3 and version.minor >= 10:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro} meets requirements.")
        return True
    else:
        print(f"✗ Python {version.major}.{version.minor}.{version.micro} does not meet requirements (need 3.10+).")
        return False

def check_gpu():
    """Check CUDA availability and GPU info."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"✓ GPU detected: {gpu_name} ({gpu_memory:.2f} GB VRAM)")
            return True
        else:
            print("✗ No CUDA-capable GPU detected.")
            return False
    except ImportError:
        print("✗ PyTorch not installed.")
        return False

def check_isaac_modules():
    """Verify essential Isaac Sim modules can be imported."""
    modules_to_check = [
        "omni.isaac.core",
        "omni.replicator.core",
        "omni.usd",
        "carb"
    ]
    
    all_available = True
    for module_name in modules_to_check:
        try:
            __import__(module_name)
            print(f"✓ Module available: {module_name}")
        except ImportError as e:
            print(f"✗ Module unavailable: {module_name} - {e}")
            all_available = False
    
    return all_available

def check_project_structure():
    """Verify project directory structure exists."""
    required_dirs = [
        "scripts",
        "assets/environments",
        "assets/characters",
        "assets/props",
        "config",
        "output"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"✓ Directory exists: {dir_path}")
        else:
            print(f"✗ Missing directory: {dir_path}")
            all_exist = False
    
    return all_exist

def check_config_file():
    """Verify generation config file exists and is valid."""
    config_path = "config/generation_config.yaml"
    if os.path.exists(config_path):
        print(f"✓ Config file exists: {config_path}")
        # Basic validation could be added here
        return True
    else:
        print(f"✗ Missing config file: {config_path}")
        return False

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("Isaac Sim Environment Validation")
    print("=" * 60)
    
    results = []
    
    # Run checks
    results.append(("Python Version", check_python_version()))
    results.append(("GPU Availability", check_gpu()))
    results.append(("Isaac Modules", check_isaac_modules()))
    results.append(("Project Structure", check_project_structure()))
    results.append(("Config File", check_config_file()))
    
    print("=" * 60)
    print("Validation Summary:")
    print("=" * 60)
    
    all_passed = True
    for check_name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{check_name:20} [{status}]")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✓ All checks passed. Environment is ready for development.")
        return 0
    else:
        print("✗ Some checks failed. Please address the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
