# Lesson 4: QUIC Transport

Now that you understand TCP transport, let's explore QUIC - a modern UDP-based transport protocol that provides built-in encryption and multiplexing. You'll learn about py-libp2p's multi-transport capabilities by connecting to a remote peer with both TCP and QUIC simultaneously.

## Learning Objectives

By the end of this lesson, you will:
- Understand the advantages of QUIC over TCP
- Configure multi-transport py-libp2p hosts
- Handle connections over different transport protocols
- Connect to remote peers using QUIC multiaddresses

## Background: QUIC Transport

QUIC (Quick UDP Internet Connections) is a modern transport protocol that offers several advantages over TCP:

- **Built-in Security**: Encryption is integrated into the protocol (no separate TLS layer needed)
- **Reduced Latency**: Fewer round-trips for connection establishment
- **Better Multiplexing**: Streams don't block each other (no head-of-line blocking)
- **Connection Migration**: Connections can survive network changes
- **UDP-based**: Can traverse NATs more easily than TCP

## Transport Comparison

Remember back in Lesson 2, you learned that the libp2p stack looks like the following when using TCP, Noise, and Yamux:

```
Application protocols (ping, gossipsub, etc.)
    ↕
Multiplexer (Yamux)
    ↕
Security (Noise)
    ↕
Transport (TCP)
    ↕
Network (IP)
```

In this lesson you will add the ability to connect to remote peers using the QUIC transport. Because it has integrated encryption and multiplexing, the libp2p stack looks like the following when using QUIC:

```
Application protocols (ping, gossipsub, etc.)
    ↕
──────────────┐
Multiplexer   │
Security    (QUIC)
Transport     │
──────────────┘
    ↕
Network (IP)
```

## Your Task

Extend your ping application to support both TCP and QUIC transports:

1. **Add QUIC Transport**: Configure QUIC alongside your existing TCP transport
2. **Multi-Transport Configuration**: Create a host that can handle both protocols
3. **Connect via QUIC**: Use a QUIC multiaddress to connect to the remote peer
4. **Handle Transport Events**: Display connection information for both transports

## Step-by-Step Instructions

### Step 1: Handle Imports

We're loading up the basics for logging, system ops, timing, async with Trio, multiaddrs for addressing, and libp2p core for hosts and identities. Then there's a sneaky try-except to optionally import QUIC transport, sets a flag if it's available, otherwise bails gracefully with a print. Keeps things modular without hard failures.

```python
import logging
import sys

import os
import time

import trio
from multiaddr import Multiaddr

from libp2p import new_host, generate_new_rsa_identity
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr

# Try to import QUIC transport - if this fails, QUIC isn't supported in this version
try:
    from libp2p.transport.quic.transport import QUICTransport
    QUIC_AVAILABLE = True
except ImportError as e:
    print(f"QUIC transport not available: {e}")
    QUIC_AVAILABLE = False
    QUICTransport = None
```

### Step 2: Configure Logging

Setting the root logger to WARNING to keep output chill, then dialing back specific noisy loggers like multiaddr and libp2p.

```python
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)
logging.getLogger("async_service").setLevel(logging.WARNING)
```

### Step 3: Define Ping Constants

Quick globals for the ping protocol ID (standard IPFS ping) and payload length (32 bytes). These make the pings consistent and easy to tweak without hunting through code.

```python
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
```

### Step 4: Define the QUICPingApp Class

Our main player: a class for the QUIC-based ping app. Init sets up placeholders for the host, peer ID, and a running flag, simple state tracking to keep things humming.

```python
class QUICPingApp:
    """
    A libp2p application that uses QUIC transport for ping functionality.
    """
    
    def __init__(self):
        self.quic_host = None
        self.peer_id = None
        self.running = True
```

### Step 5: Create QUIC Host Method

This async method spins up a QUIC enabled host if available: generates an RSA keypair, builds the QUIC transport, swaps it into the swarm, and wires it up. Bails early if QUIC's a no-go, with a nice success print or traceback on fail.

```python
    async def create_quic_host(self):
        """Create a QUIC host."""
        if not QUIC_AVAILABLE:
            print("❌ QUIC transport not available, cannot proceed")
            return None
            
        try:
            # Generate keypair for QUIC host
            key_pair = generate_new_rsa_identity()
            
            # Create QUIC transport
            quic_transport = QUICTransport(key_pair.private_key)
            
            host = new_host(key_pair=key_pair)
            
            swarm = host.get_network()
            swarm.transport = quic_transport
            
            # Set up QUIC transport with the swarm if method exists
            if hasattr(quic_transport, 'set_swarm'):
                quic_transport.set_swarm(swarm)
            
            print("✅ QUIC host created successfully")
            return host
            
        except Exception as e:
            print(f"❌ Failed to create QUIC host: {e}")
            import traceback
            traceback.print_exc()
            return None
```

### Step 6: Handle Incoming Ping Method

Async handler for pings over a stream: loops reading 32-byte payloads, echoes them back, times the RTT, and logs it with the peer ID. Breaks on empty data, closes gracefully on errors, keeps the connection tidy.

```python
    async def handle_ping(self, stream: INetStream) -> None:
        """Handle incoming ping requests over QUIC."""
        try:
            while True:
                start_time = time.time()
                data = await stream.read(PING_LENGTH)
                
                if not data:
                    break
                
                await stream.write(data)
                rtt_ms = (time.time() - start_time) * 1000
                peer_id = stream.muxed_conn.peer_id
                print(f"📨 Received QUIC ping from {peer_id}, RTT: {int(rtt_ms)} ms")
                
        except Exception as e:
            print(f"❌ Ping handler error: {e}")
        finally:
            try:
                await stream.close()
            except:
                pass
```

### Step 7: Send Ping Method

The outbound ping loop: crafts a 32-byte payload, writes it, reads the echo with a 5s timeout, checks for match, and logs RTT or mismatch/timeout. Sleeps 1s between rounds, respects the running flag, and cleans up on exit.

```python
    async def send_ping(self, stream: INetStream):
        """Send ping to remote peer and measure RTT over QUIC."""
        try:
            payload = b"\x01" * PING_LENGTH
            peer_id = stream.muxed_conn.peer_id
            
            while self.running:
                start_time = time.time()
                await stream.write(payload)
                
                with trio.fail_after(5):
                    response = await stream.read(PING_LENGTH)
                
                if response == payload:
                    rtt_ms = (time.time() - start_time) * 1000
                    print(f"🏓 QUIC ping to {peer_id}, RTT: {int(rtt_ms)} ms")
                else:
                    print(f"❌ QUIC ping response mismatch from {peer_id}")
                
                # Wait 1 second between pings
                await trio.sleep(1)
                
        except trio.TooSlowError:
            print(f"⏱️ QUIC ping timeout to {peer_id}")
        except Exception as e:
            print(f"❌ QUIC ping failed to {peer_id}: {e}")
        finally:
            try:
                await stream.close()
            except:
                pass
```

### Step 8: Dial Peer Method

Async dialer: parses the multiaddr, connects to the peer info, opens a ping stream on the protocol, and kicks off the send_ping loop. Logs the journey with emojis for that extra flair on success or fail.

```python
    async def dial_peer(self, addr_str: str):
        """Dial a peer using QUIC."""
        try:
            addr = Multiaddr(addr_str)
            print(f"🔄 Dialing peer at: {addr} via QUIC")
            
            # Parse peer info from multiaddr
            info = info_from_p2p_addr(addr)
            await self.quic_host.connect(info)
            
            print(f"✅ Connected to: {info.peer_id} via QUIC")
            
            # Open ping stream
            stream = await self.quic_host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
            
            # Start ping loop
            await self.send_ping(stream)
            
        except Exception as e:
            print(f"❌ Failed to connect via QUIC to {addr_str}: {e}")
```

### Step 9: Run Host Method

Boots the host: sets the ping handler, runs it async with a QUIC listen addr (dynamic UDP port), prints listening addrs, then sleeps forever to keep it alive. Catches errors and re-raises for upstream handling.

```python
    async def run_host(self, host, listen_addr: Multiaddr):
        """Run the QUIC host with error handling."""
        try:
            # Set ping handler
            host.set_stream_handler(PING_PROTOCOL_ID, self.handle_ping)
            
            async with host.run(listen_addrs=[listen_addr]):
                # Print listening addresses
                addrs = host.get_addrs()
                if addrs:
                    print(f"🎧 QUIC listening on:")
                    for addr in addrs:
                        print(f"  {addr}")
                
                await trio.sleep_forever()
                
        except Exception as e:
            print(f"❌ QUIC host failed: {e}")
            raise
```

### Step 10: Print Connection Command Method

Helper to spit out a copy-paste command for connecting from another terminal: filters QUIC addrs, tweaks localhost, and prints env-set/run instructions. Only if host's up. Otherwise, a polite error.

```python
    def print_connection_command(self):
        """Print ready-to-use command for connecting from another terminal."""
        if not self.quic_host:
            print("❌ No QUIC host available to generate connection command")
            return
        
        print("ℹ️ No remote peers specified. To connect from another terminal, copy-paste this:")
        quic_addrs = [str(addr) for addr in self.quic_host.get_addrs() if "/quic" in str(addr)]
        for addr in quic_addrs:
            dial_addr = addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")
            print(f"$env:REMOTE_PEERS='{dial_addr}'; python app/main.py")
        
        print("⏳ Waiting for incoming connections...")
```

### Step 11: Main Run Method

The app's conductor: prints startup, creates the host (exits if fail), grabs peer ID, parses REMOTE_PEERS (QUIC-only), then uses a nursery to spawn host runner and dialers in parallel. If no remotes, prints connect command. Catches broad errors.

```python
    async def run(self):
        """Main application loop for QUIC ping."""
        print("🚀 Starting QUIC Ping Application...")
        
        # Create QUIC host
        if not QUIC_AVAILABLE:
            print("❌ QUIC transport not available, exiting...")
            return
        
        print("🔧 Attempting to create QUIC host...")
        self.quic_host = await self.create_quic_host()
        if not self.quic_host:
            print("❌ Failed to create QUIC host, exiting...")
            return
        
        self.peer_id = self.quic_host.get_id()
        print(f"🆔 Local QUIC peer ID: {self.peer_id}")
        
        # Parse remote peers from environment variable
        remote_peers = []
        if "REMOTE_PEERS" in os.environ:
            remote_peers = [
                addr.strip() 
                for addr in os.environ["REMOTE_PEERS"].split(",")
                if addr.strip() and "/quic" in addr
            ]
        
        try:
            async with trio.open_nursery() as nursery:
                # Start QUIC host
                quic_addr = Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1")
                nursery.start_soon(self.run_host, self.quic_host, quic_addr)
                
                # Give host time to start
                await trio.sleep(1)
                
                # Connect to remote peers if specified
                if remote_peers:
                    print(f"🔗 Connecting to {len(remote_peers)} remote peer(s)...")
                    for addr_str in remote_peers:
                        nursery.start_soon(self.dial_peer, addr_str)
                
                else:
                    self.print_connection_command()
                
        except Exception as e:
            print(f"❌ Application error: {e}")
            raise
```

### Step 12: Main Entry Point Function

Async main: instantiates the app, runs it with try-except for interrupts and errors (with helpful QUIC troubleshooting tips on crash), and always prints a stop message. Keeps the shutdown user-friendly.

```python
async def main():
    """Application entry point."""
    app = QUICPingApp()
    
    try:
        await app.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        app.running = False
    except Exception as e:
        print(f"💥 Application error: {e}")
        print("\n🔍 Analysis:")
        print("Your py-libp2p version uses a single-transport architecture.")
        print("The QUIC transport exists but may not be fully stable.")
        print("\n🔧 Solutions:")
        print("1. Build py-libp2p with QUIC support enabled")
        print("2. Use a newer version of py-libp2p with better QUIC support")
        print("3. Check QUIC configuration and network permissions")
    finally:
        print("🏁 Application stopped")
```

### Step 13: Script Runner

Standard guard: if run directly, fire up Trio to execute main. Lets it import cleanly elsewhere if needed.

```python
if __name__ == "__main__":
    trio.run(main)
```

## Testing Your Implementation

### Test QUIC Ping APP:

```bash
# Terminal 1 - Start server
python main.py

# Terminal 2 - Connect as client (replace PORT and PEER_ID with actual ID from server)
$env:REMOTE_PEERS='/ip4/127.0.0.1/udp/<PORT>/quic-v1/p2p/<PEER_ID>'; python app/main.py
```

### Docker Workshop Commands:

1. Set the environment variables:
   ```bash
   export PROJECT_ROOT=/path/to/workshop
   export LESSON_PATH=en/py/04-quic-transport
   ```

2. Change into the lesson directory:
    ```bash
    cd $PROJECT_ROOT/$LESSON_PATH
    ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run with Docker Compose:
   ```bash
   docker rm -f workshop-lesson ucw-checker-04-quic-transport
   docker network rm -f workshop-net
   docker network create --driver bridge --subnet 172.16.16.0/24 workshop-net
   docker compose --project-name workshop up --build --remove-orphans
   ```

5. Run the Python script to check your output:
   ```bash
   python check.py
   ```

## Success Criteria

Your implementation should:
- ✅ Display the startup message and local peer ID
- ✅ Successfully dial the remote peer using QUIC
- ✅ Establish a QUIC connection
- ✅ Send and receive ping messages over QUIC
- ✅ Display round-trip times in milliseconds
- ✅ Identify transport type (TCP vs QUIC) in connection messages

## Hints

## Hint - QUIC Multiaddress Format

QUIC multiaddresses use UDP instead of TCP and include the QUIC protocol after the port number.
- TCP: `/ip4/127.0.0.1/tcp/9092`
- QUIC: `/ip4/127.0.0.1/udp/9092/quic-v1`

## Hint - Error Handling

py-libp2p uses async/await patterns, so make sure to properly handle exceptions in async contexts:

```python
try:
    await host.connect(addr)
except Exception as e:
    print(f"Connection failed: {e}")
```

## Hint - Here is the complete code 

```python
import logging
import sys

import os
import time

import trio
from multiaddr import Multiaddr

from libp2p import new_host, generate_new_rsa_identity
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr

# Try to import QUIC transport - if this fails, QUIC isn't supported in this version
try:
    from libp2p.transport.quic.transport import QUICTransport
    QUIC_AVAILABLE = True
except ImportError as e:
    print(f"QUIC transport not available: {e}")
    QUIC_AVAILABLE = False
    QUICTransport = None

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)
logging.getLogger("async_service").setLevel(logging.WARNING)

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32

class QUICPingApp:
    """
    A libp2p application that uses QUIC transport for ping functionality.
    """
    
    def __init__(self):
        self.quic_host = None
        self.peer_id = None
        self.running = True
        
    async def create_quic_host(self):
        """Create a QUIC host."""
        if not QUIC_AVAILABLE:
            print("❌ QUIC transport not available, cannot proceed")
            return None
            
        try:
            # Generate keypair for QUIC host
            key_pair = generate_new_rsa_identity()
            
            # Create QUIC transport
            quic_transport = QUICTransport(key_pair.private_key)
            
            host = new_host(key_pair=key_pair)
            
            swarm = host.get_network()
            swarm.transport = quic_transport
            
            # Set up QUIC transport with the swarm if method exists
            if hasattr(quic_transport, 'set_swarm'):
                quic_transport.set_swarm(swarm)
            
            print("✅ QUIC host created successfully")
            return host
            
        except Exception as e:
            print(f"❌ Failed to create QUIC host: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def handle_ping(self, stream: INetStream) -> None:
        """Handle incoming ping requests over QUIC."""
        try:
            while True:
                start_time = time.time()
                data = await stream.read(PING_LENGTH)
                
                if not data:
                    break
                
                await stream.write(data)
                rtt_ms = (time.time() - start_time) * 1000
                peer_id = stream.muxed_conn.peer_id
                print(f"📨 Received QUIC ping from {peer_id}, RTT: {int(rtt_ms)} ms")
                
        except Exception as e:
            print(f"❌ Ping handler error: {e}")
        finally:
            try:
                await stream.close()
            except:
                pass
    
    async def send_ping(self, stream: INetStream):
        """Send ping to remote peer and measure RTT over QUIC."""
        try:
            payload = b"\x01" * PING_LENGTH
            peer_id = stream.muxed_conn.peer_id
            
            while self.running:
                start_time = time.time()
                await stream.write(payload)
                
                with trio.fail_after(5):
                    response = await stream.read(PING_LENGTH)
                
                if response == payload:
                    rtt_ms = (time.time() - start_time) * 1000
                    print(f"🏓 QUIC ping to {peer_id}, RTT: {int(rtt_ms)} ms")
                else:
                    print(f"❌ QUIC ping response mismatch from {peer_id}")
                
                # Wait 1 second between pings
                await trio.sleep(1)
                
        except trio.TooSlowError:
            print(f"⏱️ QUIC ping timeout to {peer_id}")
        except Exception as e:
            print(f"❌ QUIC ping failed to {peer_id}: {e}")
        finally:
            try:
                await stream.close()
            except:
                pass
    
    async def dial_peer(self, addr_str: str):
        """Dial a peer using QUIC."""
        try:
            addr = Multiaddr(addr_str)
            print(f"🔄 Dialing peer at: {addr} via QUIC")
            
            # Parse peer info from multiaddr
            info = info_from_p2p_addr(addr)
            await self.quic_host.connect(info)
            
            print(f"✅ Connected to: {info.peer_id} via QUIC")
            
            # Open ping stream
            stream = await self.quic_host.new_stream(info.peer_id, [PING_PROTOCOL_ID])
            
            # Start ping loop
            await self.send_ping(stream)
            
        except Exception as e:
            print(f"❌ Failed to connect via QUIC to {addr_str}: {e}")
    
    async def run_host(self, host, listen_addr: Multiaddr):
        """Run the QUIC host with error handling."""
        try:
            # Set ping handler
            host.set_stream_handler(PING_PROTOCOL_ID, self.handle_ping)
            
            async with host.run(listen_addrs=[listen_addr]):
                # Print listening addresses
                addrs = host.get_addrs()
                if addrs:
                    print(f"🎧 QUIC listening on:")
                    for addr in addrs:
                        print(f"  {addr}")
                
                await trio.sleep_forever()
                
        except Exception as e:
            print(f"❌ QUIC host failed: {e}")
            raise
    
    def print_connection_command(self):
        """Print ready-to-use command for connecting from another terminal."""
        if not self.quic_host:
            print("❌ No QUIC host available to generate connection command")
            return
        
        print("ℹ️ No remote peers specified. To connect from another terminal, copy-paste this:")
        quic_addrs = [str(addr) for addr in self.quic_host.get_addrs() if "/quic" in str(addr)]
        for addr in quic_addrs:
            dial_addr = addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")
            print(f"$env:REMOTE_PEERS='{dial_addr}'; python app/main.py")
        
        print("⏳ Waiting for incoming connections...")
    
    async def run(self):
        """Main application loop for QUIC ping."""
        print("🚀 Starting QUIC Ping Application...")
        
        # Create QUIC host
        if not QUIC_AVAILABLE:
            print("❌ QUIC transport not available, exiting...")
            return
        
        print("🔧 Attempting to create QUIC host...")
        self.quic_host = await self.create_quic_host()
        if not self.quic_host:
            print("❌ Failed to create QUIC host, exiting...")
            return
        
        self.peer_id = self.quic_host.get_id()
        print(f"🆔 Local QUIC peer ID: {self.peer_id}")
        
        # Parse remote peers from environment variable
        remote_peers = []
        if "REMOTE_PEERS" in os.environ:
            remote_peers = [
                addr.strip() 
                for addr in os.environ["REMOTE_PEERS"].split(",")
                if addr.strip() and "/quic" in addr
            ]
        
        try:
            async with trio.open_nursery() as nursery:
                # Start QUIC host
                quic_addr = Multiaddr("/ip4/0.0.0.0/udp/0/quic-v1")
                nursery.start_soon(self.run_host, self.quic_host, quic_addr)
                
                # Give host time to start
                await trio.sleep(1)
                
                # Connect to remote peers if specified
                if remote_peers:
                    print(f"🔗 Connecting to {len(remote_peers)} remote peer(s)...")
                    for addr_str in remote_peers:
                        nursery.start_soon(self.dial_peer, addr_str)
                
                else:
                    self.print_connection_command()
                
        except Exception as e:
            print(f"❌ Application error: {e}")
            raise

async def main():
    """Application entry point."""
    app = QUICPingApp()
    
    try:
        await app.run()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        app.running = False
    except Exception as e:
        print(f"💥 Application error: {e}")
        print("\n🔍 Analysis:")
        print("Your py-libp2p version uses a single-transport architecture.")
        print("The QUIC transport exists but may not be fully stable.")
        print("\n🔧 Solutions:")
        print("1. Build py-libp2p with QUIC support enabled")
        print("2. Use a newer version of py-libp2p with better QUIC support")
        print("3. Check QUIC configuration and network permissions")
    finally:
        print("🏁 Application stopped")

if __name__ == "__main__":
    trio.run(main)
```

## What's Next?

Great work! You've successfully implemented multi-transport support with QUIC in Python. You now understand:

- **QUIC Advantages**: Built-in security, reduced latency, better multiplexing
- **Multi-Transport Configuration**: Running multiple transports simultaneously
- **Transport Flexibility**: py-libp2p's ability to adapt to different network conditions
- **Modern Protocols**: How py-libp2p embraces cutting-edge networking technology

Key concepts you've learned:
- **QUIC Protocol**: Modern UDP-based transport with integrated security
- **Multi-Transport**: Supporting multiple protocols simultaneously
- **Transport Abstraction**: How py-libp2p handles different transports uniformly
- **Connection Flexibility**: Choosing the best transport for each connection

In the next lesson, you'll reach your second checkpoint by implementing the Identify protocol, which allows peers to exchange information about their capabilities and supported protocols!