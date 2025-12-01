#!/usr/bin/env python3
"""
Dependencies checker for py-libp2p Universal Connectivity Workshop
Checks that all required Python packages and tools are available.
"""

import sys
import subprocess
import importlib
import pkg_resources
from packaging import version

def check_python_version():
    """Check if Python version meets minimum requirements"""
    min_version = "3.8"
    current_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    
    if sys.version_info < (3, 8):
        print(f"[!] Python {min_version} or higher is required. Current version: {current_version}")
        return False
    
    print(f"[OK] Python {current_version} is installed")
    return True

def check_pip():
    """Check if pip is available"""
    try:
        import pip
        pip_version = pip.__version__
        print(f"[OK] pip {pip_version} is installed")
        return True
    except ImportError:
        print("[!] pip is not installed")
        return False

def install_package(package_name, min_version=None):
    """Install a Python package using pip"""
    package_spec = f"{package_name}>={min_version}" if min_version else package_name
    print(f"Installing {package_spec}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_spec, "-q"])
        print(f"[OK] Successfully installed {package_name}")
        return True
    except subprocess.CalledProcessError:
        print(f"[FAIL] Failed to install {package_name}")
        return False

def check_package(package_name, min_version=None, auto_install=False):
    """Check if a Python package is installed with optional version check"""
    try:
        if min_version:
            pkg_resources.require(f"{package_name}>={min_version}")
            installed_version = pkg_resources.get_distribution(package_name).version
            print(f"[OK] {package_name} {installed_version} is installed")
        else:
            importlib.import_module(package_name)
            try:
                installed_version = pkg_resources.get_distribution(package_name).version
                print(f"[OK] {package_name} {installed_version} is installed")
            except:
                print(f"[OK] {package_name} is installed")
        return True
    except (ImportError, pkg_resources.DistributionNotFound, pkg_resources.VersionConflict):
        if min_version:
            print(f"[!] {package_name} >= {min_version} is required")
        else:
            print(f"[!] {package_name} is not installed")
        
        if auto_install:
            return install_package(package_name, min_version)
        return False

def check_command(command, description=None):
    """Check if a system command is available"""
    try:
        result = subprocess.run([command, "--version"], 
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"[OK] {command} is installed")
            return True
        else:
            print(f"[!] {command} is not available")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        desc = f" ({description})" if description else ""
        print(f"[!] {command}{desc} is not installed")
        return False

def install_instructions():
    """Print installation instructions for missing dependencies"""
    print("\n" + "="*60)
    print("ADDITIONAL INSTALLATION INSTRUCTIONS")
    print("="*60)
    print("\nFor Docker (if you plan to use containerized lessons):")
    print("Visit: https://docs.docker.com/get-docker/")

def main():
    """Main dependency checking function"""
    print("Checking dependencies for py-libp2p Universal Connectivity Workshop...")
    print("="*70)
    
    # Check for --auto-install flag
    auto_install = "--auto-install" in sys.argv or "-y" in sys.argv
    
    if auto_install:
        print("Auto-install mode enabled\n")
    
    all_dependencies_met = True
    
    # Check Python version
    if not check_python_version():
        all_dependencies_met = False
    
    # Check pip
    if not check_pip():
        all_dependencies_met = False
        print("\n[ERROR] pip is required but not installed. Please install pip first.")
        sys.exit(1)
    
    # Check core Python packages
    required_packages = [
        ("trio", None),
        ("multiaddr", None),
        ("protobuf", "3.20.0"),
    ]
    
    print("\nChecking required Python packages:")
    packages_to_install = []
    
    for package, min_ver in required_packages:
        if not check_package(package, min_ver, auto_install=False):
            packages_to_install.append((package, min_ver))
            all_dependencies_met = False
    
    # Install missing packages if needed
    if packages_to_install:
        if auto_install:
            print("\nInstalling missing packages...")
            for package, min_ver in packages_to_install:
                if install_package(package, min_ver):
                    all_dependencies_met = True
                else:
                    all_dependencies_met = False
        else:
            print("\n" + "="*70)
            print("Would you like to install missing packages now? (y/n): ", end="")
            response = input().lower().strip()
            
            if response in ['y', 'yes']:
                print("\nInstalling missing packages...")
                for package, min_ver in packages_to_install:
                    if install_package(package, min_ver):
                        all_dependencies_met = True
                    else:
                        all_dependencies_met = False
            else:
                print("\nYou can install them manually with:")
                print("pip install trio multiaddr protobuf")
    
    # Check system tools
    print("\nChecking system tools:")
    if not check_command("git", "version control"):
        print("  (Git is recommended for cloning py-libp2p source)")
    
    check_command("docker", "containerization")
    
    print("\n" + "="*70)
    if all_dependencies_met:
        print("[SUCCESS] All required dependencies are met!")
        print("You're ready to start the workshop!")
    else:
        print("[!] Some required dependencies are missing.")
        install_instructions()
        sys.exit(1)

if __name__ == "__main__":
    main()