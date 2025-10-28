# Lesson 3: Ping Checkpoint 🏆

Welcome to your first checkpoint! In this lesson, you'll implement the ping protocol using `py-libp2p` with the Trio library to establish bidirectional connectivity with a remote peer and measure round-trip times. This lesson builds on basic libp2p concepts and introduces protocol handling and event-driven networking.

## Learning Objectives

By the end of this lesson, you will:
- Understand the purpose and mechanics of the ping protocol in libp2p.
- Implement a working ping protocol using `py-libp2p` and Trio.
- Handle ping requests and responses to measure network performance.
- Successfully connect to remote peers and validate your solution.

## Background: The Ping Protocol

The ping protocol in libp2p serves several purposes:
- **Connectivity Testing**: Verifies bidirectional communication between peers.
- **Latency Measurement**: Measures round-trip time (RTT) to assess network performance.
- **Keep-Alive**: Sends periodic messages to maintain active connections.
- **Network Quality**: Provides insights into connection stability and reliability.

The libp2p ping protocol (`/ipfs/ping/1.0.0`) exchanges 32-byte payloads between peers, with the receiver echoing the data back to measure round-trip time.

## Your Task

Building on your TCP transport implementation from Lesson 2, you need to:

1. **Configure Ping Settings**: Set up ping with a 1-second interval and 5-second timeout
2. **Handle Ping Events**: Process `ping::Event` and display round-trip times

## Step-by-Step Instructions

### Step 1: Handle Imports

We're loading up argparse for CLI args, logging and time for basics, multiaddr and trio for networking/async, and a bunch from libp2p for host creation, identities, streams, peer info, security (Noise), muxing (Yamux), and crypto primitives. Solid foundation for a secure P2P ping setup.

```python
import argparse
import logging
import time

import multiaddr
import trio

from libp2p import (
    new_host,
    generate_new_rsa_identity,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.yamux.yamux import Yamux, PROTOCOL_ID as YAMUX_PROTOCOL_ID
from cryptography.hazmat.primitives.asymmetric import x25519
```

### Step 2: Configure Logging

Basic logging at WARNING level to keep output quiet, but we suppress noise from multiaddr, libp2p, and async_service specifically. Then bump the root logger to INFO for our app's key events balances verbosity without spam.

```python
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)
logging.getLogger("async_service").setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.INFO)
```

### Step 3: Define Ping Constants

Here we set the protocol ID for our custom ping (IPFS-style), payload length (32 bytes), and response timeout (5s). These drive the ping/pong mechanics—keeps it standardized and tunable.

```python
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 5
```

### Step 4: NoisePrivateKey Class

Custom wrapper for X25519 private keys used in Noise, adds to_bytes for serialization and public_key/get_public_key methods. It's a thin layer to fit libp2p's expectations without reinventing crypto wheels.

```python
class NoisePrivateKey:
    def __init__(self, key):
        self._key = key
    
    def to_bytes(self):
        return self._key.private_bytes_raw()
    
    def public_key(self):
        return NoisePublicKey(self._key.public_key())
    
    def get_public_key(self):
        return self.public_key()
```

### Step 5: NoisePublicKey Class

Companion to the private key: wraps the public X25519 key and exposes to_bytes for raw export. Simple and focused pairs perfectly with the private side for full keypair handling.

```python
class NoisePublicKey:
    def __init__(self, key):
        self._key = key
    
    def to_bytes(self):
        return self._key.public_bytes_raw()
```

### Step 6: Create Secure Host Function

This spins up a libp2p host with explicit security: generates RSA for identity, X25519 for Noise, builds the Noise transport, and wires in Noise security + Yamux muxing options. Returns a ready-to-rock host explicit config ensures encrypted, multiplexed TCP streams.

```python
def create_secure_host():
    """
    Create a libp2p host with explicit Noise encryption and Yamux multiplexing
    over TCP.
    """
    # Generate RSA keypair for libp2p identity
    key_pair = generate_new_rsa_identity()
    
    # Generate X25519 keypair for Noise protocol
    x25519_private_key = x25519.X25519PrivateKey.generate()
    noise_privkey = NoisePrivateKey(x25519_private_key)
    
    # Create Noise transport
    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_privkey)
    
    # Configure security (Noise) and multiplexing (Yamux)
    sec_opt = {TProtocol("/noise"): noise_transport}
    muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): Yamux}
    
    return new_host(
        key_pair=key_pair,
        sec_opt=sec_opt,
        muxer_opt=muxer_opt
    )
```

### Step 7: Server-Side Ping Handler

Async handler for incoming ping streams: reads a fixed-length payload, echoes it back if valid, logs the exchange, and closes the stream. Catches errors with reset/close—handles one ping per stream, no loops, keeping it lightweight for the server.

```python
async def handle_ping(stream: INetStream) -> None:
    """
    Server-side ping handler: echoes data back.
    This handles ONE ping per stream, as the client opens a new stream per ping.
    REMOVED the `while True:` loop.
    """
    peer_id = stream.muxed_conn.peer_id
    try:
        payload = await stream.read(PING_LENGTH)
        
        if payload is not None and len(payload) > 0:
            logging.info(f"received ping from {peer_id}")
            await stream.write(payload)
            logging.info(f"responded with pong to {peer_id}")
        else:
            # Stream closed unexpectedly
            logging.info(f"Stream from {peer_id} closed before ping received")

    except Exception as e:
        # Log the specific exception
        logging.warning(f"Error handling ping from {peer_id}: {repr(e)}")
        await stream.reset()
    finally:
        # A single ping is done, close the stream from the server side too
        await stream.close()
        logging.info(f"Closed ping stream from {peer_id}")
```

### Step 8: Client-Side Send Ping Function

Client's ping sender: crafts a dummy payload, times the write/read roundtrip, measures RTT in ms, and prints success/failure. Times out gracefully or catches errors, closes stream after, precise for one-off pings.

```python
async def send_ping(stream: INetStream) -> None:
    """Client-side: sends one ping and calculates RTT."""
    try:
        payload = b"\x01" * PING_LENGTH
        peer_id = stream.muxed_conn.peer_id
        
        logging.info(f"sending ping to {peer_id}")

        # 2. Handle Ping Events: Measure RTT
        start_time = trio.current_time()
        await stream.write(payload)

        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)
        
        end_time = trio.current_time()
        rtt_ms = (end_time - start_time) * 1000

        if response == payload:
            print(f"ping: Success from {peer_id}, RTT = {rtt_ms:.2f} ms")
        else:
            print(f"ping: Failed, response mismatch from {peer_id}")

    except trio.TooSlowError:
        print(f"ping: Timeout to {stream.muxed_conn.peer_id} after {RESP_TIMEOUT}s")
    except Exception as e:
        print(f"ping: Error occurred : {repr(e)}")
    finally:
        await stream.close()
```

### Step 9: Ping Looper Function

Client's loop: every 1s, opens a fresh stream to the peer, sends a ping via send_ping, and handles failures with reset. Infinite async loop meets the 1s interval goal without blocking the host.

```python
async def ping_looper(host, peer_id, protocols):
    """
    Client-side: Continuously pings a peer every 1 second.
    This fulfills Goal 1: 1-second interval
    """
    while True:
        stream = None
        try:
            stream = await host.new_stream(peer_id, protocols)
            await send_ping(stream)
        except Exception as e:
            print(f"Failed to open stream or ping: {repr(e)}")
            if stream:
                await stream.reset()
        
        # Wait 1 second before the next ping
        await trio.sleep(1.0)
```

### Step 10: Run Function

Core async runner: finds a free port if needed, sets listen addrs, creates secure host, and runs it in context. Starts peerstore cleanup. If no dest (server mode), sets ping handler and prints addrs. If dest (client), connects, then spawns ping looper. Sleeps forever to keep alive, handles both modes cleanly.

```python
async def run(port: int, destination: str) -> None:
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if port <= 0:
        port = find_free_port()

    listen_addrs = get_available_interfaces(port)
    host = create_secure_host()

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        if not destination:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            all_addrs = host.get_addrs()
            print("Security: Noise encryption enabled")
            print("Multiplexing: Yamux enabled")
            print("Listener ready, listening on:\n")
            for addr in all_addrs:
                print(f"{addr}")

            print("\nWaiting for incoming connection...")

        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            print(f"Connected to {info.peer_id}")
            
            print("Starting 1-second ping interval...")
            nursery.start_soon(ping_looper, host, info.peer_id, [PING_PROTOCOL_ID])

        # Keep both client and server alive
        await trio.sleep_forever()
```

### Step 11: Main Function

CLI entry: sets up argparse for port (default 8000) and optional dest multiaddr, with a helpful description. Runs the async run func via trio, catches Ctrl+C for a clean exit.

```python
def main() -> None:
    description = """
    This program demonstrates a simple p2p ping application using libp2p
    with a 1-second interval and RTT measurement.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=8000, type=int, help="source port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="destination multiaddr string",
    )
    args = parser.parse_args()

    try:
        trio.run(run, *(args.port, args.destination))
    except KeyboardInterrupt:
        print("\nGoodbye!")
```

### Step 12: Entry Point

Guard the main() call—runs if direct execution, skips on import. Keeps it module-friendly.

```python
if __name__ == "__main__":
    main()
```

## Testing Your Implementation

#### Test Basic Ping:
```bash
# Terminal 1 - Start server
python main.py -p 8000

# Terminal 2 - Connect as client (replace PEER_ID with actual ID from server)
python main.py -d /ip4/127.0.0.1/tcp/8000/p2p/PEER_ID
```

### Docker Workshop Commands:

```bash
export PROJECT_ROOT=/path/to/workshop
export LESSON_PATH=uc-workshop/en/py/03-ping-checkpoint
cd $PROJECT_ROOT/$LESSON_PATH

# Clean up
docker rm -f workshop-lesson ucw-checker-03-ping-checkpoint
docker network rm -f workshop-net

# Run workshop
docker network create --driver bridge --subnet 172.16.16.0/24 workshop-net
docker compose --project-name workshop up --build --remove-orphans

# Check results
python check.py
```

## Success Criteria

Your implementation should:
- ✅ Display the startup message and local peer ID
- ✅ Successfully establish connections with remote peers
- ✅ Handle incoming ping requests and send appropriate responses
- ✅ Send ping requests and measure round-trip times
- ✅ Output logs in the expected format for validation
- ✅ Work with both basic and secure (Noise + Yamux) configurations

## Hints

## Hint - Complete Solution

Here's the complete working solution:

```python
import argparse
import logging
import time

import multiaddr
import trio

from libp2p import (
    new_host,
    generate_new_rsa_identity,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.yamux.yamux import Yamux, PROTOCOL_ID as YAMUX_PROTOCOL_ID
from cryptography.hazmat.primitives.asymmetric import x25519

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)
logging.getLogger("async_service").setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.INFO)


PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 5

class NoisePrivateKey:
    def __init__(self, key):
        self._key = key
    
    def to_bytes(self):
        return self._key.private_bytes_raw()
    
    def public_key(self):
        return NoisePublicKey(self._key.public_key())
    
    def get_public_key(self):
        return self.public_key()

class NoisePublicKey:
    def __init__(self, key):
        self._key = key
    
    def to_bytes(self):
        return self._key.public_bytes_raw()

def create_secure_host():
    """
    Create a libp2p host with explicit Noise encryption and Yamux multiplexing
    over TCP.
    """
    # Generate RSA keypair for libp2p identity
    key_pair = generate_new_rsa_identity()
    
    # Generate X25519 keypair for Noise protocol
    x25519_private_key = x25519.X25519PrivateKey.generate()
    noise_privkey = NoisePrivateKey(x25519_private_key)
    
    # Create Noise transport
    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_privkey)
    
    # Configure security (Noise) and multiplexing (Yamux)
    sec_opt = {TProtocol("/noise"): noise_transport}
    muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): Yamux}
    
    return new_host(
        key_pair=key_pair,
        sec_opt=sec_opt,
        muxer_opt=muxer_opt
    )


async def handle_ping(stream: INetStream) -> None:
    """
    Server-side ping handler: echoes data back.
    This handles ONE ping per stream, as the client opens a new stream per ping.
    REMOVED the `while True:` loop.
    """
    peer_id = stream.muxed_conn.peer_id
    try:
        payload = await stream.read(PING_LENGTH)
        
        if payload is not None and len(payload) > 0:
            logging.info(f"received ping from {peer_id}")
            await stream.write(payload)
            logging.info(f"responded with pong to {peer_id}")
        else:
            # Stream closed unexpectedly
            logging.info(f"Stream from {peer_id} closed before ping received")

    except Exception as e:
        # Log the specific exception
        logging.warning(f"Error handling ping from {peer_id}: {repr(e)}")
        await stream.reset()
    finally:
        # A single ping is done, close the stream from the server side too
        await stream.close()
        logging.info(f"Closed ping stream from {peer_id}")


async def send_ping(stream: INetStream) -> None:
    """Client-side: sends one ping and calculates RTT."""
    try:
        payload = b"\x01" * PING_LENGTH
        peer_id = stream.muxed_conn.peer_id
        
        logging.info(f"sending ping to {peer_id}")

        # 2. Handle Ping Events: Measure RTT
        start_time = trio.current_time()
        await stream.write(payload)

        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)
        
        end_time = trio.current_time()
        rtt_ms = (end_time - start_time) * 1000

        if response == payload:
            print(f"ping: Success from {peer_id}, RTT = {rtt_ms:.2f} ms")
        else:
            print(f"ping: Failed, response mismatch from {peer_id}")

    except trio.TooSlowError:
        print(f"ping: Timeout to {stream.muxed_conn.peer_id} after {RESP_TIMEOUT}s")
    except Exception as e:
        print(f"ping: Error occurred : {repr(e)}")
    finally:
        await stream.close()


async def ping_looper(host, peer_id, protocols):
    """
    Client-side: Continuously pings a peer every 1 second.
    This fulfills Goal 1: 1-second interval
    """
    while True:
        stream = None
        try:
            stream = await host.new_stream(peer_id, protocols)
            await send_ping(stream)
        except Exception as e:
            print(f"Failed to open stream or ping: {repr(e)}")
            if stream:
                await stream.reset()
        
        # Wait 1 second before the next ping
        await trio.sleep(1.0)


async def run(port: int, destination: str) -> None:
    from libp2p.utils.address_validation import (
        find_free_port,
        get_available_interfaces,
        get_optimal_binding_address,
    )

    if port <= 0:
        port = find_free_port()

    listen_addrs = get_available_interfaces(port)
    host = create_secure_host()

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Start the peer-store cleanup task
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

        if not destination:
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            all_addrs = host.get_addrs()
            print("Security: Noise encryption enabled")
            print("Multiplexing: Yamux enabled")
            print("Listener ready, listening on:\n")
            for addr in all_addrs:
                print(f"{addr}")

            print("\nWaiting for incoming connection...")

        else:
            maddr = multiaddr.Multiaddr(destination)
            info = info_from_p2p_addr(maddr)
            await host.connect(info)
            print(f"Connected to {info.peer_id}")
            
            print("Starting 1-second ping interval...")
            nursery.start_soon(ping_looper, host, info.peer_id, [PING_PROTOCOL_ID])

        # Keep both client and server alive
        await trio.sleep_forever()


def main() -> None:
    description = """
    This program demonstrates a simple p2p ping application using libp2p
    with a 1-second interval and RTT measurement.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=8000, type=int, help="source port number")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help="destination multiaddr string",
    )
    args = parser.parse_args()

    try:
        trio.run(run, *(args.port, args.destination))
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
```

## Troubleshooting

**Common Issues:**

1. **Import Errors**: Ensure py-libp2p is installed: `pip install libp2p`
2. **Connection Refused**: Check if the server is running and ports are available
3. **Peer ID Mismatch**: Copy the exact peer ID from server output
4. **Timeout Issues**: Increase RESP_TIMEOUT if network is slow
5. **Windows Path Issues**: Use forward slashes in multiaddrs: `/ip4/127.0.0.1/tcp/8000`

**Debug Tips:**
- Add `import logging; logging.basicConfig(level=logging.DEBUG)` for detailed logs
- Use `netstat -an | grep :8000` (Linux/Mac) or `netstat -an | findstr :8000` (Windows) to check if port is listening
- Test with basic version first, then advance to secure version

## What's Next?

Congratulations! You've successfully implemented the libp2p ping protocol 🎉

You've learned:
- **Protocol Implementation**: How to handle libp2p protocols with stream handlers
- **Async Programming**: Using Trio for concurrent networking operations
- **Security**: Adding Noise encryption and Yamux multiplexing
- **Connection Management**: Establishing and maintaining peer connections

In the next lesson, you'll explore more advanced libp2p features like DHT (Distributed Hash Table) and content routing!