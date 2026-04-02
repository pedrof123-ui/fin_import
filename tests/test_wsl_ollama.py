#!/usr/bin/env python3
"""
Test Ollama connectivity from WSL to Windows host
Quick diagnostic tool for WSL + Ollama setup
"""

import asyncio
import os
import subprocess
import httpx


def get_windows_host_ip() -> str:
    """Get Windows host IP from WSL"""
    try:
        result = subprocess.run(
            ['ip', 'route', 'show', 'default'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'default' in line:
                    parts = line.split()
                    if 'via' in parts:
                        via_index = parts.index('via')
                        if via_index + 1 < len(parts):
                            return parts[via_index + 1]
    except:
        pass
    return None


async def test_ollama_connection(host: str, port: int = 11434):
    """Test connection to Ollama"""
    url = f"http://{host}:{port}"
    
    print(f"\n{'='*80}")
    print(f"TESTING OLLAMA CONNECTION")
    print(f"{'='*80}")
    print(f"\nTarget: {url}")
    
    # Test 1: Basic connectivity
    print(f"\n1. Testing basic connectivity...")
    try:
        result = subprocess.run(
            ['nc', '-zv', host, str(port)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"   ✅ Port {port} is open on {host}")
        else:
            print(f"   ❌ Port {port} is closed on {host}")
            print(f"      Make sure Ollama is running on Windows")
            return False
    except FileNotFoundError:
        print(f"   ⚠️  'nc' command not found, skipping port check")
    except Exception as e:
        print(f"   ⚠️  Port check failed: {e}")
    
    # Test 2: HTTP connectivity
    print(f"\n2. Testing HTTP API...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/api/tags")
            
            if response.status_code == 200:
                print(f"   ✅ Ollama API responding")
                
                # Test 3: List models
                print(f"\n3. Available models:")
                data = response.json()
                models = data.get('models', [])
                
                if models:
                    for model in models:
                        name = model.get('name', 'unknown')
                        size = model.get('size', 0)
                        size_gb = size / (1024**3)
                        print(f"      • {name} ({size_gb:.1f} GB)")
                else:
                    print(f"      ⚠️  No models installed")
                    print(f"      Run: ollama pull llama3.1:8b")
                
                return True
            else:
                print(f"   ❌ Ollama returned status {response.status_code}")
                return False
                
    except httpx.ConnectError:
        print(f"   ❌ Cannot connect to {url}")
        print(f"\n   Possible issues:")
        print(f"      1. Ollama not running on Windows")
        print(f"      2. Windows Firewall blocking WSL")
        print(f"      3. Ollama not listening on correct port")
        return False
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


async def main():
    """Main test function"""
    
    print(f"\n{'='*80}")
    print(f"WSL + OLLAMA CONNECTIVITY TEST")
    print(f"{'='*80}")
    
    # Detect environment
    print(f"\n📋 Environment Detection:")
    
    # Check if in WSL
    try:
        with open('/proc/version', 'r') as f:
            version = f.read()
            if 'microsoft' in version.lower():
                print(f"   ✅ Running in WSL")
                in_wsl = True
            else:
                print(f"   ℹ️  Not in WSL (native Linux)")
                in_wsl = False
    except:
        print(f"   ℹ️  Cannot determine if WSL")
        in_wsl = False
    
    # Get Windows host IP
    if in_wsl:
        print(f"\n📍 Windows Host Detection:")
        win_host = get_windows_host_ip()
        if win_host:
            print(f"   ✅ Windows host IP: {win_host}")
        else:
            print(f"   ❌ Could not detect Windows host IP")
            win_host = input("\n   Enter Windows host IP manually: ").strip()
    else:
        win_host = 'localhost'
        print(f"\n   Using localhost (not in WSL)")
    
    # Test connection
    success = await test_ollama_connection(win_host)
    
    # Summary
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    
    if success:
        print(f"\n✅ Ollama is accessible at http://{win_host}:11434")
        print(f"\n🎯 Next steps:")
        print(f"   1. Set in your .env file:")
        print(f"      OLLAMA_HOST={win_host}")
        print(f"      (or the mapper will auto-detect it)")
        print(f"\n   2. Or let auto-detection handle it (recommended)")
        print(f"\n   3. Pull your model if needed:")
        print(f"      ollama pull deepseek-r1:8b")
    else:
        print(f"\n❌ Cannot connect to Ollama")
        print(f"\n🔧 Troubleshooting:")
        print(f"   1. On Windows, run: ollama serve")
        print(f"   2. Check Windows Firewall:")
        print(f"      - Allow incoming on port 11434")
        print(f"      - Or disable for Private networks")
        print(f"   3. Test from WSL:")
        print(f"      nc -zv {win_host} 11434")
        print(f"   4. Check Ollama is listening on all interfaces:")
        print(f"      Set OLLAMA_HOST=0.0.0.0 on Windows")
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
