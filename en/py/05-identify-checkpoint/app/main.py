import argparse
import logging
import os
import struct
import time
from typing import Dict, List, Optional, Set

from cryptography.hazmat.primitives.asymmetric import x25519
import multiaddr
import trio

from libp2p import generate_new_rsa_identity, new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.id import ID as PeerID
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.yamux.yamux import Yamux
from libp2p.stream_muxer.yamux.yamux import PROTOCOL_ID as YAMUX_PROTOCOL_ID

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)
logging.getLogger("async_service").setLevel(logging.WARNING)

# Protocol constants
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
IDENTIFY_PROTOCOL_ID = TProtocol("/ipfs/id/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60
PING_INTERVAL = 2.0  # seconds between pings
AGENT_VERSION = "universal-connectivity/0.1.0"
PROTOCOL_VERSION = "/ipfs/0.1.0"

# Global state for connected peers
connected_peers: Set[PeerID] = set()
peer_info_cache: Dict[PeerID, Dict] = {}
# Global host reference for handlers
current_host = None


def create_noise_keypair():
    """Create a Noise protocol keypair for secure communication"""
    try:
        x25519_private_key = x25519.X25519PrivateKey.generate()

        class NoisePrivateKey:
            def __init__(self, key):
                self._key = key

            def to_bytes(self):
                return self._key.private_bytes_raw()

            def public_key(self):
                return NoisePublicKey(self._key.public_key())

            def get_public_key(self):
                return NoisePublicKey(self._key.public_key())

        class NoisePublicKey:
            def __init__(self, key):
                self._key = key

            def to_bytes(self):
                return self._key.public_bytes_raw()

        return NoisePrivateKey(x25519_private_key)
    except Exception as e:
        logging.error(f"Failed to create Noise keypair: {e}")
        return None


def encode_identify_response(peer_id: PeerID, listen_addrs: List[str]) -> bytes:
    """
    Encode an identify response message.
    This is a simplified version - in production, you'd use protobuf.
    """
    try:
        # Create a simple identify response
        protocols = [
            PING_PROTOCOL_ID.encode('utf-8'),
            IDENTIFY_PROTOCOL_ID.encode('utf-8'),
            b"/noise",
            b"/yamux/1.0.0"
        ]
        
        # Build message components
        peer_id_bytes = str(peer_id).encode('utf-8')
        agent_bytes = AGENT_VERSION.encode('utf-8')
        protocol_version_bytes = PROTOCOL_VERSION.encode('utf-8')
        
        # Simple message format: length-prefixed fields
        message = b""
        
        # Add peer ID
        message += struct.pack(">I", len(peer_id_bytes))
        message += peer_id_bytes
        
        # Add agent version
        message += struct.pack(">I", len(agent_bytes))
        message += agent_bytes
        
        # Add protocol version
        message += struct.pack(">I", len(protocol_version_bytes))
        message += protocol_version_bytes
        
        # Add protocols
        message += struct.pack(">I", len(protocols))
        for proto in protocols:
            message += struct.pack(">I", len(proto))
            message += proto
        
        # Add listen addresses
        addr_bytes = []
        for addr in listen_addrs:
            addr_bytes.append(addr.encode('utf-8'))
        
        message += struct.pack(">I", len(addr_bytes))
        for addr in addr_bytes:
            message += struct.pack(">I", len(addr))
            message += addr
        
        return message
    except Exception as e:
        logging.error(f"Failed to encode identify response: {e}")
        return b""


def decode_identify_response(data: bytes) -> Optional[Dict]:
    """
    Decode an identify response message.
    This is a simplified version - in production, you'd use protobuf.
    """
    try:
        if len(data) < 4:
            return None
            
        offset = 0
        
        # Read peer ID
        if offset + 4 > len(data):
            return None
        peer_id_len = struct.unpack(">I", data[offset:offset+4])[0]
        offset += 4
        
        if offset + peer_id_len > len(data):
            return None
        peer_id = data[offset:offset+peer_id_len].decode('utf-8')
        offset += peer_id_len
        
        # Read agent version
        if offset + 4 > len(data):
            return None
        agent_len = struct.unpack(">I", data[offset:offset+4])[0]
        offset += 4
        
        if offset + agent_len > len(data):
            return None
        agent_version = data[offset:offset+agent_len].decode('utf-8')
        offset += agent_len
        
        # Read protocol version
        if offset + 4 > len(data):
            return None
        proto_ver_len = struct.unpack(">I", data[offset:offset+4])[0]
        offset += 4
        
        if offset + proto_ver_len > len(data):
            return None
        protocol_version = data[offset:offset+proto_ver_len].decode('utf-8')
        offset += proto_ver_len
        
        # Read protocols
        if offset + 4 > len(data):
            return None
        num_protocols = struct.unpack(">I", data[offset:offset+4])[0]
        offset += 4
        
        protocols = []
        for _ in range(num_protocols):
            if offset + 4 > len(data):
                break
            proto_len = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4
            
            if offset + proto_len > len(data):
                break
            protocol = data[offset:offset+proto_len].decode('utf-8')
            protocols.append(protocol)
            offset += proto_len
        
        # Read listen addresses
        if offset + 4 > len(data):
            return {
                'peer_id': peer_id,
                'agent_version': agent_version,
                'protocol_version': protocol_version,
                'protocols': protocols,
                'listen_addrs': []
            }
        
        num_addrs = struct.unpack(">I", data[offset:offset+4])[0]
        offset += 4
        
        listen_addrs = []
        for _ in range(num_addrs):
            if offset + 4 > len(data):
                break
            addr_len = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4
            
            if offset + addr_len > len(data):
                break
            addr = data[offset:offset+addr_len].decode('utf-8')
            listen_addrs.append(addr)
            offset += addr_len
        
        return {
            'peer_id': peer_id,
            'agent_version': agent_version,
            'protocol_version': protocol_version,
            'protocols': protocols,
            'listen_addrs': listen_addrs
        }
    except Exception as e:
        logging.error(f"Failed to decode identify response: {e}")
        return None


async def handle_identify(stream: INetStream) -> None:
    """Handle incoming identify requests"""
    peer_id = stream.muxed_conn.peer_id
    print(f"[IDENTIFY] New identify request from {peer_id}")
    logging.info(f"Identify handler called for peer {peer_id}")
    
    try:
        # For the identify protocol, we typically send our info immediately
        # Use the global host reference
        global current_host
        if current_host:
            listen_addrs = [str(addr) for addr in current_host.get_addrs()]
            peer_id_for_response = current_host.get_id()
        else:
            # Fallback
            listen_addrs = []
            peer_id_for_response = peer_id
        
        # Create identify response
        response = encode_identify_response(peer_id_for_response, listen_addrs)
        
        if response:
            await stream.write(response)
            print(f"[IDENTIFY] Sent identify info to {peer_id}")
            logging.info(f"Sent identify response to {peer_id}")
        else:
            print(f"[IDENTIFY] Failed to create identify response for {peer_id}")
            
    except Exception as e:
        print(f"[IDENTIFY] Error handling identify from {peer_id}: {e}")
        logging.exception("Identify handler error")
    finally:
        try:
            await stream.close()
        except Exception as e:
            logging.debug(f"Error closing identify stream: {e}")


async def send_identify_request(host, target_peer_id: PeerID) -> Optional[Dict]:
    """Send an identify request to a peer and return their info"""
    try:
        print(f"[IDENTIFY] Sending identify request to {target_peer_id}")
        stream = await host.new_stream(target_peer_id, [IDENTIFY_PROTOCOL_ID])
        
        # For identify protocol, the response is sent immediately by the handler
        # We don't need to send anything, just read the response
        
        # Read the identify response
        try:
            with trio.fail_after(RESP_TIMEOUT):
                response_data = await stream.read(4096)  # Read up to 4KB
        except trio.TooSlowError:
            print(f"[IDENTIFY] Identify request to {target_peer_id} timed out")
            return None
        except Exception as e:
            print(f"[IDENTIFY] Error reading identify response from {target_peer_id}: {e}")
            return None
        
        await stream.close()
        
        if response_data:
            peer_info = decode_identify_response(response_data)
            if peer_info:
                # Store in cache
                peer_info_cache[target_peer_id] = peer_info
                
                # Print the information
                print(f"[IDENTIFY] Identified peer: {peer_info['peer_id']}")
                print(f"[IDENTIFY] Agent: {peer_info['agent_version']}")
                print(f"[IDENTIFY] Protocol version: {peer_info['protocol_version']}")
                print(f"[IDENTIFY] Supports {len(peer_info['protocols'])} protocols:")
                for proto in peer_info['protocols']:
                    print(f"[IDENTIFY]   - {proto}")
                if peer_info['listen_addrs']:
                    print(f"[IDENTIFY] Listen addresses:")
                    for addr in peer_info['listen_addrs']:
                        print(f"[IDENTIFY]   - {addr}")
                
                return peer_info
            else:
                print(f"[IDENTIFY] Failed to decode identify response from {target_peer_id}")
        else:
            print(f"[IDENTIFY] No response received from {target_peer_id}")
            
    except Exception as e:
        print(f"[IDENTIFY] Failed to send identify request to {target_peer_id}: {e}")
        logging.exception("Identify request error")
    
    return None


async def handle_ping(stream: INetStream) -> None:
    """Handle incoming ping requests"""
    peer_id = stream.muxed_conn.peer_id
    print(f"[PING] New ping stream from {peer_id}")
    logging.info(f"Ping handler called for peer {peer_id}")

    ping_count = 0
    
    try:
        while True:
            try:
                data = await stream.read(PING_LENGTH)
                
                if not data or len(data) == 0:
                    print(f"[PING] Connection closed by {peer_id}")
                    break
                
                ping_count += 1
                print(f"[PING] Received ping {ping_count} from {peer_id}: {len(data)} bytes")
                
                # Echo the data back
                await stream.write(data)
                
            except Exception as e:
                print(f"[PING] Error in ping loop with {peer_id}: {e}")
                break
                
    except Exception as e:
        print(f"[PING] Error handling ping from {peer_id}: {e}")
        logging.exception("Ping handler error")
    finally:
        try:
            await stream.close()
        except Exception as e:
            logging.debug(f"Error closing ping stream: {e}")
    
    print(f"[PING] Ping session completed with {peer_id} ({ping_count} pings)")


async def send_ping(host, target_peer_id: PeerID) -> bool:
    """Send a single ping to a peer"""
    try:
        stream = await host.new_stream(target_peer_id, [PING_PROTOCOL_ID])
        
        payload = os.urandom(PING_LENGTH)
        start_time = time.time()
        
        await stream.write(payload)
        
        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)
        
        end_time = time.time()
        rtt = (end_time - start_time) * 1000
        
        await stream.close()
        
        if response and len(response) >= PING_LENGTH and response[:PING_LENGTH] == payload:
            print(f"[PING] Ping to {target_peer_id}: RTT {rtt:.2f}ms")
            return True
        else:
            print(f"[PING] Ping to {target_peer_id}: response mismatch")
            return False
            
    except trio.TooSlowError:
        print(f"[PING] Ping to {target_peer_id}: timeout")
    except Exception as e:
        print(f"[PING] Ping to {target_peer_id}: error - {e}")
    
    return False


async def periodic_ping_task(host, nursery):
    """Periodically ping all connected peers"""
    while True:
        await trio.sleep(PING_INTERVAL)
        for peer_id in list(connected_peers):
            nursery.start_soon(send_ping, host, peer_id)


async def run_universal_connectivity(remote_peers: List[str], port: int = 0):
    """Run the universal connectivity application"""
    print("🚀 Starting Universal Connectivity Application...")
    
    # Create host with proper security and muxing
    key_pair = generate_new_rsa_identity()
    noise_privkey = create_noise_keypair()
    
    if not noise_privkey:
        print("❌ Failed to create Noise keypair")
        return 1
    
    noise_transport = NoiseTransport(key_pair, noise_privkey=noise_privkey)
    sec_opt = {TProtocol("/noise"): noise_transport}
    muxer_opt = {TProtocol(YAMUX_PROTOCOL_ID): Yamux}
    
    host = new_host(key_pair=key_pair, sec_opt=sec_opt, muxer_opt=muxer_opt)
    
    # Store global host reference for handlers
    global current_host
    current_host = host
    
    # Set up protocol handlers
    host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)
    host.set_stream_handler(IDENTIFY_PROTOCOL_ID, handle_identify)
    
    # Start listening
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")
    
    async with host.run(listen_addrs=[listen_addr]):
        print(f"🎯 Local peer ID: {host.get_id()}")
        print(f"🎧 Listening on: {host.get_addrs()}")
        print(f"🔐 Security: Noise encryption")
        print(f"📡 Muxer: Yamux stream multiplexing")
        print(f"🏃 Protocols: {PING_PROTOCOL_ID}, {IDENTIFY_PROTOCOL_ID}")
        
        # Use a nursery to manage background tasks
        async with trio.open_nursery() as nursery:
            # Start periodic ping task
            nursery.start_soon(periodic_ping_task, host, nursery)
            
            # Connect to remote peers
            for remote_addr_str in remote_peers:
                try:
                    remote_addr = multiaddr.Multiaddr(remote_addr_str)
                    peer_info = info_from_p2p_addr(remote_addr)
                    target_peer_id = peer_info.peer_id
                    
                    print(f"🔗 Connecting to: {target_peer_id}")
                    print(f"📍 Address: {remote_addr}")
                    
                    # Connect to peer
                    await host.connect(peer_info)
                    connected_peers.add(target_peer_id)
                    
                    print(f"✅ Connected to: {target_peer_id}")
                    
                    # Send identify request
                    await trio.sleep(0.1)  # Small delay to let connection stabilize
                    nursery.start_soon(send_identify_request, host, target_peer_id)
                    
                except Exception as e:
                    print(f"❌ Failed to connect to {remote_addr_str}: {e}")
                    logging.exception(f"Connection error to {remote_addr_str}")
            
            if not connected_peers:
                print("⚠️  No peers connected. Waiting for incoming connections...")
            
            print("\n🎉 Universal Connectivity Application is running!")
            print("📊 Status:")
            print(f"   Connected peers: {len(connected_peers)}")
            print(f"   Peer info cached: {len(peer_info_cache)}")
            print("\n📝 Press Ctrl+C to exit")
            
            try:
                await trio.sleep_forever()
            except KeyboardInterrupt:
                print("\n🛑 Shutting down...")
                # The nursery will cancel all tasks when exiting
    
    # Clear global reference
    current_host = None
    return 0


def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(
        description="Universal Connectivity Application - libp2p identify and ping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start server and wait for connections
  python main.py
  
  # Start server on specific port
  python main.py --port 8000
  
  # Connect to remote peer
  python main.py --remote /ip4/127.0.0.1/tcp/8000/p2p/QmPeer...
  
  # Connect to multiple peers
  python main.py --remote /ip4/127.0.0.1/tcp/8000/p2p/QmPeer1,/ip4/127.0.0.1/tcp/8001/p2p/QmPeer2
  
  # Use environment variable for remote peers
  REMOTE_PEERS="/ip4/127.0.0.1/tcp/8000/p2p/QmPeer..." python main.py
        """
    )
    
    parser.add_argument(
        "--port", "-p", 
        type=int, 
        default=0,
        help="Port to listen on (default: random port)"
    )
    
    parser.add_argument(
        "--remote", "-r",
        type=str,
        help="Remote peer addresses (comma-separated)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get remote peers from arguments or environment
    remote_peers = []
    
    if args.remote:
        remote_peers = [addr.strip() for addr in args.remote.split(',') if addr.strip()]
    elif remote_peers_env := os.getenv("REMOTE_PEERS"):
        remote_peers = [addr.strip() for addr in remote_peers_env.split(',') if addr.strip()]
    
    try:
        return trio.run(run_universal_connectivity, remote_peers, args.port)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        return 0
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        logging.exception("Fatal error")
        return 1


if __name__ == "__main__":
    exit(main())
