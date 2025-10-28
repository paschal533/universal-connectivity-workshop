# Lesson 2: Transport Layer - TCP Connection

Building on your basic py-libp2p node, in this lesson you'll learn about transport layers and establish your first peer-to-peer connections using TCP with Noise and Yamux multiplexing.

## Learning Objectives

By the end of this lesson, you will:

- Understand py-libp2p's transport abstraction
- Configure TCP transport with security and multiplexing
- Establish a connection to a remote peer
- Handle connection events properly

## Background: Transport Layers in py-libp2p

In py-libp2p, **transports** handle the low-level network communication. A transport defines how data travels between peers. py-libp2p supports multiple transports:

- **TCP**: Reliable, ordered, connection-oriented (like HTTP)
- **QUIC**: Modern UDP-based with built-in encryption
- **WebRTC**: For browser connectivity
- **Memory**: For testing and local communication

Each transport can be enhanced with:

- **Security protocols**: Encrypt communication (e.g., Noise)
- **Multiplexers**: Share one connection for multiple streams (e.g., Yamux)

## Transport Stack

The py-libp2p stack looks like the following when using TCP, Noise, and Yamux:

```
Application protocols (ping, pubsub, etc.)
    ↕
Multiplexer (Yamux)
    ↕
Security (Noise)
    ↕
Transport (TCP)
    ↕
Network (IP)
```

## Your Task

Extend your application to:

1. Parse remote peer addresses from an environment variable
2. Set up a listener for incoming connections
3. Establish a connection to a remote peer
4. Print connection events for verification
5. Handle connection lifecycle properly

## Step-by-Step Instructions

### Step 1: Handle Imports

Alright, we're kicking off with the imports. This is where we pull in the essentials for async programming, logging, environment vars, and the libp2p networking bits. Trio handles our async runtime, logging for debug output, os for env access, typing for list hints, and libp2p/multiaddr for peer discovery and addressing. Clean and standard; no bloat here.

```python
import trio
import logging
import os
from typing import List
from libp2p import new_host
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr
```

### Step 2: Set Up Logging

Next, we configure basic logging at DEBUG level so we can trace what's happening under the hood, super useful for debugging peer connections without drowning in noise. We grab a logger instance tied to this module's name for targeted output.

```python
# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
```

### Step 3: Define the Main Async Function

This is the heart of it: an async main function where all the action happens. We print a startup message to let folks know we're live, then dive into peer setup. Everything's wrapped in async because libp2p and trio play nice with concurrency.

```python
async def main():
    print("Starting Universal Connectivity application...")
```

### Step 4: Parse Remote Peer Addresses from Env

Here, we're grabbing a list of remote peers from an env var called REMOTE_PEERS, it's a comma-separated string of multiaddrs. We split, strip whitespace, and convert each to a Multiaddr object, skipping empties. If nothing's set, we just roll with an empty list. Keeps it flexible for different deployment scenarios.

```python
    # Parse remote peer addresses from environment variable
    remote_addrs: List[Multiaddr] = []
    remote_peers_env = os.getenv("REMOTE_PEERS", "")
   
    if remote_peers_env:
        remote_addrs = [
            Multiaddr(addr.strip())
            for addr in remote_peers_env.split(',')
            if addr.strip()
        ]
```

### Step 5: Configure Listening Address

We pull the listen port from LISTEN_PORT env (default 9000) and build a multiaddr for it—binding to all IPv4 interfaces on TCP. This is our "hey, connect to me here" beacon; straightforward and reusable across runs.

```python
    # Set up listening address with configurable port
    listen_port = os.getenv("LISTEN_PORT", "9000")
    listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{listen_port}")
```

### Step 6: Create the Libp2p Host

Boom, instantiate the host with new_host(), this spins up our local peer identity and networking stack. No custom config yet, so it uses defaults, which is fine for a basic connectivity tester.

```python
    # Create the libp2p host
    host = new_host()
   
    print(f"Local peer id: {host.get_id()}")
```

### Step 7: Run the Host and Start Listening

Enter the async context manager for `host.run()`, passing our listen addr. This kicks off the listener and keeps the host alive. We then loop through our addrs and print 'em handy for verifying we're exposed correctly.

```python
    # Start the host and begin listening for connections
    async with host.run(listen_addrs=[listen_addr]):
        # Print our listening addresses
        addrs = host.get_addrs()
        for addr in addrs:
            print(f"Listening on: {addr}")
```

### Step 8: Connect to Remote Peers

Now the outbound magic: for each remote addr, we check for a /p2p segment (required for peer ID), extract peer info, and attempt a connect. If it works, we log the win and track the peer ID; errors get printed but don't crash us. Graceful, right?

```python
        # Connect to all remote peers if any specified
        connected_peers = []
        for addr in remote_addrs:
            try:
                # Validate that the multiaddress contains /p2p
                if not addr.get("p2p"):
                    print(f"Invalid multiaddress {addr}: Missing /p2p/<peer_id>")
                    continue
               
                # Extract peer info from multiaddr
                peer_info = info_from_p2p_addr(addr)
               
                # Connect to the peer
                print(f"Attempting to connect to {peer_info.peer_id} at {addr}")
                await host.connect(peer_info)
                print(f"Connected to: {peer_info.peer_id} via {addr}")
                connected_peers.append(peer_info.peer_id)
               
            except Exception as e:
                print(f"Failed to connect to {addr}: {e}")
```

### Step 9: Main Loop for Keeping Connections Alive

This is the "stay awake" part: print a waiting message, then enter an infinite loop sleeping 1s at a time. Every tick, we check if any tracked peers have dropped (by comparing to current connections) and log graceful closes, cleaning the list. It's a simple heartbeat without blocking incoming stuff.

```python
        # Keep the program running to maintain connections and accept new ones
        try:
            print("Waiting for incoming connections...")
            while True:
                await trio.sleep(1)
               
                # Check connection status for outbound connections
                if connected_peers:
                    current_peers = list(host.get_network().connections.keys())
                    disconnected = [p for p in connected_peers if p not in current_peers]
                   
                    for peer_id in disconnected:
                        print(f"Connection to {peer_id} closed gracefully")
                        connected_peers.remove(peer_id)
```

### Step 10: Handle Shutdown

Wrap the loop in a try-except for KeyboardInterrupt (Ctrl+C), just print a shutdown note and let the context manager clean up the host. Keeps it polite and non-abrupt.

```python
        except KeyboardInterrupt:
            print("Shutting down...")
```

### Step 11: Entry Point

Finally, the classic if __name__ guard: fire up trio.run(main) to bootstrap the async world. This ensures we only run if scripted directly, not on import.

```python
if __name__ == "__main__":
    trio.run(main)
```

### Step 12: Test Your Implementation

#### Manual Testing

1. **Run Node 1 (Server)**:

   - In the first terminal, set the listening port and run the program without `REMOTE_PEERS` to act as the server:

     ```powershell
     $env:LISTEN_PORT = "9000"
     $env:REMOTE_PEERS = $null
     python app/main.py
     ```

   - Note the peer ID and listening address, e.g., `/ip4/0.0.0.0/tcp/9000/p2p/QmRBWnrT7wP2w8JGe3YprMxjPxMvgXFtT1LLNE5JbGFNn9`.

2. **Run Node 2 (Client)**:

   - In the second terminal, set the listening port to a different value (to avoid conflicts) and set `REMOTE_PEERS` to connect to Node 1:

     ```powershell
     $env:LISTEN_PORT = "9001"
     $env:REMOTE_PEERS = "/ip4/127.0.0.1/tcp/9000/p2p/QmRBWnrT7wP2w8JGe3YprMxjPxMvgXFtT1LLNE5JbGFNn9"
     python app/main.py
     ```

   - Replace the peer ID with the actual peer ID from Node 1’s output.

3. **Verify Output**:

   - Node 1 should print its peer ID, listening address, and indicate it’s waiting for connections.
   - Node 2 should print its peer ID, listening address, and confirm a successful connection to Node 1, e.g., `Connected to: QmRBWnrT7wP2w8JGe3YprMxjPxMvgXFtT1LLNE5JbGFNn9 via /ip4/127.0.0.1/tcp/9000/p2p/QmRBWnrT7wP2w8JGe3YprMxjPxMvgXFtT1LLNE5JbGFNn9`.


### Step 13: Success Criteria

Your implementation should:

- ✅ Display the startup message and local peer ID
- ✅ Successfully parse remote peer addresses from the environment variable
- ✅ Listen on a TCP port (e.g., 9000)
- ✅ Successfully connect to the remote peer
- ✅ Print connection establishment messages
- ✅ Handle connection closure gracefully

## Hints

## Hint - Complete Solution

Here's the complete working solution:

```python
import trio
import logging
import os
from typing import List

from libp2p import new_host
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def main():
    print("Starting Universal Connectivity application...")
    
    # Parse remote peer addresses from environment variable
    remote_addrs: List[Multiaddr] = []
    remote_peers_env = os.getenv("REMOTE_PEERS", "")
    
    if remote_peers_env:
        remote_addrs = [
            Multiaddr(addr.strip()) 
            for addr in remote_peers_env.split(',') 
            if addr.strip()
        ]
    
    # Set up listening address with configurable port
    listen_port = os.getenv("LISTEN_PORT", "9000")
    listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{listen_port}")
    
    # Create the libp2p host
    host = new_host()
    
    print(f"Local peer id: {host.get_id()}")
    
    # Start the host and begin listening for connections
    async with host.run(listen_addrs=[listen_addr]):
        # Print our listening addresses
        addrs = host.get_addrs()
        for addr in addrs:
            print(f"Listening on: {addr}")
        
        # Connect to all remote peers if any specified
        connected_peers = []
        for addr in remote_addrs:
            try:
                # Validate that the multiaddress contains /p2p
                if not addr.get("p2p"):
                    print(f"Invalid multiaddress {addr}: Missing /p2p/<peer_id>")
                    continue
                
                # Extract peer info from multiaddr
                peer_info = info_from_p2p_addr(addr)
                
                # Connect to the peer
                print(f"Attempting to connect to {peer_info.peer_id} at {addr}")
                await host.connect(peer_info)
                print(f"Connected to: {peer_info.peer_id} via {addr}")
                connected_peers.append(peer_info.peer_id)
                
            except Exception as e:
                print(f"Failed to connect to {addr}: {e}")
        
        # Keep the program running to maintain connections and accept new ones
        try:
            print("Waiting for incoming connections...")
            while True:
                await trio.sleep(1)
                
                # Check connection status for outbound connections
                if connected_peers:
                    current_peers = list(host.get_network().connections.keys())
                    disconnected = [p for p in connected_peers if p not in current_peers]
                    
                    for peer_id in disconnected:
                        print(f"Connection to {peer_id} closed gracefully")
                        connected_peers.remove(peer_id)
        
        except KeyboardInterrupt:
            print("Shutting down...")

if __name__ == "__main__":
    trio.run(main)
```

## What's Next?

Excellent! You've successfully configured TCP transport and established peer-to-peer connections using py-libp2p. You now understand:

- **Transport Layer**: How py-libp2p handles network communication
- **Security**: Noise protocol for encrypted connections
- **Multiplexing**: Yamux for stream multiplexing
- **Connection Management**: Establishing and monitoring connections
- **Async Programming**: Managing asynchronous operations in Python

In the next lesson, you'll add your first protocol (ping) and connect to the instructor's server for your first checkpoint!

Key concepts you've learned:

- **py-libp2p Host Creation**: Setting up the networking stack
- **Listening and Connecting**: Managing incoming and outgoing connections
- **Multiaddresses**: libp2p's addressing format
- **Connection Events**: Handling establishment and closure

Next up: Adding the ping protocol and achieving your first checkpoint!